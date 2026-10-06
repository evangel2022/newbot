# ADR-030: Web Search Tool and Its Provider Seam

- Status: Accepted
- Date: 2026-10-06
- Supersedes: none

## Context

The reference documents built-in web tools enabled by default: `web_fetch` and `web_search`,
disabled together by `tools.web.enable: false`, with search selecting one of several providers
(DuckDuckGo by default, plus API-backed and self-hosted options), a `maxResults` bound, and the
shared SSRF guard. newbot already has `web_fetch` (S3). Phase 5's tool model lists web
"fetch/search", so search was the missing half.

## Decision

Add a web search tool behind a provider interface, with one backend.

- `domain/search.py` adds `SearchResult(title, url, snippet)`; `ports/search.py` adds
  `SearchPort.search(query, *, limit)`. The tool depends on the port, so the backend is an edge
  adapter.
- `adapters/search/duckduckgo.py` implements the default provider. It GETs DuckDuckGo's HTML
  endpoint, resolving and pinning every hop through `NetworkGuard` (S3), follows redirects
  against the original host, and parses `result__a`/`result__snippet` with a tolerant
  `html.parser` extractor that decodes the `uddg` redirect parameter.
- `tools/web_search.py` adds `WebSearchTool` (name `web_search`, arguments `query` and an
  optional `max_results`). It validates the bound at the boundary and renders ranked
  title/URL/snippet blocks.
- `[tools.web]` gains `enable` (default true) and `search.provider`/`search.maxResults`.
  `provider` is validated to `duckduckgo`, so an unimplemented provider fails at config load
  rather than at the first search. `enable: false` removes both `web_fetch` and `web_search`.
- The composition root builds `WebSearchTool(DuckDuckGoSearch(guard))` when web tools are
  enabled, reusing the same `NetworkGuard` as the registry, and `my` reports whether web search
  is enabled.

## Consequences

**Positive**

- The agent can discover current sources, completing the web tool group; results carry URLs so
  the model can cite or fetch them.
- The provider seam is an explicit extension point: a second provider is one adapter plus a
  config value, with no tool or core change.
- Every hop is SSRF-checked and DNS-pinned, matching `web_fetch` and HTTP MCP (S3).

**Negative / accepted costs (deliberate differences, B)**

- **B -- one provider.** Only DuckDuckGo is implemented; API-backed and self-hosted providers,
  proxy, and user-agent settings are deferred.
- **B -- HTML backend.** DuckDuckGo exposes no keyless JSON results API, so the adapter scrapes
  its HTML endpoint. The extractor tolerates the documented `result__a`/`result__snippet`
  markup, but a page redesign can break it; a provider that returns JSON is the durable fix.

**Deferred (C)**

- Additional providers, proxy/user-agent configuration, and result caching.

## Alternatives considered

- **DuckDuckGo's Instant Answer JSON API.** Rejected as the default: it returns abstracts and
  related topics, not ranked web results.
- **Put the HTTP/parse logic in the tool.** Rejected: it would make the tool provider-specific
  and leave no seam for the documented provider list.
- **Fail open on a parse error (return the raw page).** Rejected: silent, model-hostile output;
  a non-2xx response is a typed `ToolError`.
