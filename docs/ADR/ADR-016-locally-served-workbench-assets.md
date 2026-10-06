# ADR-016: Locally Served Workbench Assets

- Status: Accepted
- Date: 2026-10-05
- Supersedes: none

## Context

`docs/architecture.md` R3 states that the local installation owns executable client assets and a
remote host must never replace them, and §16.14 makes `adapters/transports` responsible for "own
wire protocol and local client assets". ROADMAP Phase 4 lists local client assets as a deliverable
and makes "local client assets are always served locally and never replaced by a remote host" an
exit criterion. `.agent/review-guide.md` sharpens the rule: missing local assets must "fail
locally, never fall back to remote code".

ADR-013 established the browser as the workbench's target client, but the transport served only
`/health`, `/capabilities`, `/ticket`, `/messages`, and `/stream` — no HTML. A browser therefore
could not use the workbench at all, and there was no local asset boundary to protect.

## Decision

The workbench serves a read-only asset directory bundled with the package at
`adapters/transports/assets/`.

- `GET /` returns `index.html`; `GET /assets/<name>` returns the named asset. The initial asset set
  is a minimal client (`index.html`, `app.js`, `style.css`) that uses only the existing
  `/capabilities`, `/ticket`, `/stream`, and `/messages` surface.
- Resolution is confined to the asset root: the request path is percent-decoded, joined to the
  bundled root, fully resolved (following symlinks), and rejected unless the result stays inside
  the root. Traversal, absolute names, symlink escapes, and missing files are a local `404`; the
  transport never redirects to or proxies a remote host.
- Files with known extensions (`.html`, `.js`, `.css`) get explicit content types; other files
  under the root are served as `application/octet-stream`. Assets are read-only and require no
  token, consistent with the other read-only workbench routes (S5).
- The asset set is fixed at build time; there is no configurable asset root, because a
  configurable root invites remote or replacement code. No new capability is advertised — assets
  are always present.

## Consequences

**Positive**

- The workbench is usable from its documented target client, and every byte of client code comes
  from the local installation.
- Path resolution reuses the containment discipline of the other guards; R3 is enforced by
  construction rather than by convention.
- Assets live next to the transport that serves them, so there is one owner.

**Negative / accepted costs**

- Assets are bundled into the distribution, so an upgraded install is required to change them, and
  the wheel grows by the size of the client.
- A deployment that wants a different client must change the package rather than configuration.
- A browser client is not the only way to use the workbench; the JSON/WebSocket surface remains
  the contract, so the client can lag the protocol without blocking operators.

## Alternatives considered

- **Fetch assets from a CDN or the remote host.** Rejected: it directly violates R3 and the review
  guide, and would let a network peer supply executable code to a loopback surface.
- **A configurable asset root.** Rejected: configuration could point at remote or user-writable
  code, defeating the guarantee.
- **Advertise a `ui` capability.** Rejected: the assets are always present, so negotiation adds a
  contract without a fallback decision to make.
- **Serve no HTML.** Rejected: the browser target from ADR-013 could not use the workbench.
