"""DuckDuckGo HTML search backend, validated and pinned per request (S3)."""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, urljoin, urlsplit

import httpx

from newbot.domain.errors import ToolError
from newbot.domain.search import SearchResult
from newbot.policy.network import NetworkGuard, PinnedTarget

_ENDPOINT = "https://html.duckduckgo.com/html/"
DEFAULT_TIMEOUT_SECONDS = 20.0
_MAX_REDIRECTS = 3
_MAX_HTML_CHARS = 500_000
_REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})
_VOID_TAGS = frozenset({"br", "hr", "img", "input", "meta", "link", "wbr"})


class DuckDuckGoSearch:
    """Searches DuckDuckGo's HTML endpoint through the network guard."""

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

    async def search(self, query: str, *, limit: int) -> tuple[SearchResult, ...]:
        url = f"{_ENDPOINT}?q={quote_plus(query)}"
        if self._client is not None:
            html = await self._fetch(self._client, url)
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                html = await self._fetch(client, url)
        return _parse(html, limit)

    async def _fetch(self, client: httpx.AsyncClient, url: str) -> str:
        current = url
        for _ in range(_MAX_REDIRECTS + 1):
            target = await self._guard.resolve(current)
            try:
                response = await client.get(
                    target.connect_url,
                    headers={"Host": _host_header(current)},
                    extensions=_tls_extensions(target),
                    follow_redirects=False,
                )
            except (httpx.HTTPError, httpx.InvalidURL) as exc:
                raise ToolError(f"search failed for {current!r}: {exc}") from exc
            location = response.headers.get("location")
            if response.status_code in _REDIRECT_STATUS and location:
                current = urljoin(current, location)
                continue
            if response.is_error:
                raise ToolError(f"search returned HTTP {response.status_code}")
            return response.text[:_MAX_HTML_CHARS]
        raise ToolError(f"too many redirects searching {url!r}")


def _host_header(url: str) -> str:
    """The ``Host`` header httpx derives for the original URL."""
    return httpx.URL(url).netloc.decode("ascii")


def _tls_extensions(target: PinnedTarget) -> dict[str, str]:
    if target.scheme == "https":
        return {"sni_hostname": target.host}
    return {}


class _ResultParser(HTMLParser):
    """Extracts result anchors and snippets from a DuckDuckGo results page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._results: list[dict[str, str]] = []
        self._field: str | None = None
        self._depth = 0
        self._href = ""
        self._text: list[str] = []

    @property
    def results(self) -> list[dict[str, str]]:
        return self._results

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if self._field is not None:
            if tag not in _VOID_TAGS:
                self._depth += 1
            return
        attributes = {name: (value or "") for name, value in attrs}
        classes = attributes.get("class", "").split()
        if tag == "a" and "result__a" in classes:
            self._begin("title", attributes.get("href", ""))
        elif "result__snippet" in classes:
            self._begin("snippet", "")

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        return None

    def handle_endtag(self, tag: str) -> None:
        if self._field is None:
            return
        self._depth -= 1
        if self._depth <= 0:
            self._finish()

    def handle_data(self, data: str) -> None:
        if self._field is not None:
            self._text.append(data)

    def _begin(self, field: str, href: str) -> None:
        self._field = field
        self._depth = 1
        self._href = href
        self._text = []

    def _finish(self) -> None:
        text = " ".join("".join(self._text).split())
        if self._field == "title":
            url = _resolve_href(self._href)
            if text and url:
                self._results.append({"title": text, "url": url, "snippet": ""})
        elif text and self._results and not self._results[-1]["snippet"]:
            self._results[-1]["snippet"] = text
        self._field = None
        self._depth = 0
        self._href = ""
        self._text = []


def _resolve_href(href: str) -> str:
    if href.startswith("//"):
        href = f"https:{href}"
    parts = urlsplit(href)
    if parts.netloc.endswith("duckduckgo.com") and parts.path.startswith("/l/"):
        target = parse_qs(parts.query).get("uddg")
        if target:
            return target[0]
    return href


def _parse(html: str, limit: int) -> tuple[SearchResult, ...]:
    parser = _ResultParser()
    parser.feed(html)
    parser.close()
    results = [
        SearchResult(title=item["title"], url=item["url"], snippet=item["snippet"])
        for item in parser.results
    ]
    return tuple(results[:limit])
