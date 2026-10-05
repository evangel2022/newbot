"""Guarded HTTP fetch tool (S3)."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urljoin

import httpx

from newbot.domain.errors import ToolError
from newbot.domain.tool import ToolSpec
from newbot.policy.network import NetworkGuard, PinnedTarget
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
    """Fetches a public http(s) URL, validating and pinning every hop."""

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
            target = await self._guard.resolve(current)
            try:
                async with client.stream(
                    "GET",
                    target.connect_url,
                    headers={"Host": _host_header(current)},
                    extensions=_tls_extensions(target),
                    follow_redirects=False,
                ) as response:
                    location = response.headers.get("location")
                    if response.status_code in _REDIRECT_STATUS and location:
                        current = urljoin(current, location)
                        continue
                    body = await _read_body(response, _MAX_BODY_CHARS)
                    if response.is_error:
                        return ToolOutput(
                            text=f"HTTP {response.status_code}\n{body}".strip(),
                            is_error=True,
                        )
                    return ToolOutput(text=body or "(empty response)")
            except (httpx.HTTPError, httpx.InvalidURL) as exc:
                raise ToolError(f"fetch failed for {current!r}: {exc}") from exc
        raise ToolError(f"too many redirects fetching {url!r}")


def _host_header(url: str) -> str:
    """The ``Host`` header httpx derives for the original URL.

    Deriving it from httpx keeps IDNA, IPv6 bracketing, and the port identical
    to what the request would send if it were not pinned to an address.
    """
    return httpx.URL(url).netloc.decode("ascii")


async def _read_body(response: httpx.Response, limit: int) -> str:
    """Read at most ``limit`` characters, bounding the buffered body size."""
    parts: list[str] = []
    total = 0
    truncated = False
    async for piece in response.aiter_text():
        if total + len(piece) > limit:
            parts.append(piece[: limit - total])
            truncated = True
            break
        parts.append(piece)
        total += len(piece)
    text = bound_text("".join(parts), limit=limit)
    if truncated:
        return f"{text}\n...[truncated]"
    return text


def _tls_extensions(target: PinnedTarget) -> dict[str, str]:
    if target.scheme == "https":
        return {"sni_hostname": target.host}
    return {}
