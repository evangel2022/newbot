"""Guarded HTTP fetch tool (S3)."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urljoin

import httpx

from newbot.domain.errors import ToolError
from newbot.domain.tool import ToolSpec
from newbot.policy.network import NetworkGuard
from newbot.policy.redaction import bound_text
from newbot.ports.tools import ToolContext
from newbot.tools.base import ToolOutput, require_string

DEFAULT_TIMEOUT_SECONDS = 20.0
_MAX_REDIRECTS = 5
_MAX_BODY_CHARS = 8_000
_REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})

_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "Absolute http(s) URL to fetch."}
    },
    "required": ["url"],
    "additionalProperties": False,
}


class WebFetchTool:
    """Fetches a public http(s) URL, validating every redirect target."""

    def __init__(
        self,
        guard: NetworkGuard,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._guard = guard
        self._timeout = timeout_seconds
        self._client = client
        self.spec = ToolSpec(
            name="web_fetch",
            description="Fetch a public http(s) URL and return its text content.",
            parameters=_SCHEMA,
        )

    async def invoke(
        self, arguments: Mapping[str, object], ctx: ToolContext
    ) -> ToolOutput:
        url = require_string(arguments, "url")
        if self._client is not None:
            return await self._fetch(self._client, url)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await self._fetch(client, url)

    async def _fetch(self, client: httpx.AsyncClient, url: str) -> ToolOutput:
        current = url
        for _ in range(_MAX_REDIRECTS + 1):
            await self._guard.ensure_allowed(current)
            try:
                response = await client.get(current, follow_redirects=False)
            except httpx.HTTPError as exc:
                raise ToolError(f"fetch failed for {current!r}: {exc}") from exc
            location = response.headers.get("location")
            if response.status_code in _REDIRECT_STATUS and location:
                current = urljoin(str(response.url), location)
                continue
            body = bound_text(response.text, limit=_MAX_BODY_CHARS)
            if response.is_error:
                return ToolOutput(
                    text=f"HTTP {response.status_code}\n{body}".strip(), is_error=True
                )
            return ToolOutput(text=body or "(empty response)")
        raise ToolError(f"too many redirects fetching {url!r}")
