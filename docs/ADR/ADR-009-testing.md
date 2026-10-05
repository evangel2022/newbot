# ADR-009: Test by Surface, Protect Real Contracts

- Status: Accepted
- Date: 2026-10-05
- Supersedes: —

## Context

An agent runtime has untrusted boundaries (model output, external platforms, user input, network),
several integration layers (providers, transports, stores), and a small pure core. Testing every
imagined internal state produces a slow suite that locks in implementation details and rarely
catches real regressions. Testing nothing leaves the security and reliability contracts unproven.

## Decision

Choose tests by the surface that changed, and require each test to protect a reachable contract.

- **Layers.** `tests/unit` (pure, fast, fake ports for `domain`/`core`), `tests/integration`
  (real store/provider/transport boundaries), `tests/e2e` (public surfaces: CLI, HTTP/WS,
  packaged import).
- **By surface.** Core logic → unit tests against fake ports; provider → mocked API path plus a
  safe real call when possible; transport → transport tests plus host startup; tools → tool unit
  tests plus an agent-run path when the schema changes; security guard → boundary tests with real
  invalid input (traversal, private URL, escape); config → load-error tests for missing env refs
  and invalid files.
- **Real boundaries only.** Test invalid input where an untrusted boundary actually accepts it,
  security properties where a capability exposes them, and recovery where the product promises
  it. Do not test impossible internal states or unsupported combinations (T2).
- **Contract, not steps.** Avoid exhaustive mock permutations and assertions that mirror private
  implementation steps (T4). Prefer one evidence path per meaningful contract.
- **Reuse evidence.** Carry verification forward with the intervening diff and the reason the
  proved contract is unaffected; do not blindly re-run everything (T5). Raw artifacts stay out of
  tracked source.

## Consequences

**Positive**

- The suite stays fast and meaningful; failures point at real contract breaks.
- Security properties are proven at the boundary where they matter.
- The pure core is fully testable without I/O.

**Negative / accepted costs**

- Fewer tests means reviewers must judge which contract a change affects.
- Some duplication in integration setup for transports/providers is accepted (A5).

## Alternatives considered

- **High-coverage-by-volume.** Rejected: locks in implementation details and slows the suite
  without proving real contracts.
- **Only end-to-end tests.** Rejected: slow feedback and hard-to-localize failures; unit tests on
  the pure core localize defects cheaply.
- **Snapshotting internal structures.** Rejected: mirrors private steps and breaks on harmless
  refactors.