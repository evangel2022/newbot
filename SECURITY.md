# Security Policy

## Supported versions

newbot is pre-1.0. Only the latest commit on the default branch receives security fixes.

## Reporting a vulnerability

**Do not report security vulnerabilities through public GitHub issues.**

Instead, use GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-public-repository-security-vulnerability)
("Report a vulnerability" on the repository's **Security** tab). Include:

- a description of the issue and its impact;
- steps to reproduce, with a minimal example;
- affected versions/commit;
- any suggested fix, if you have one.

You should receive an initial response within 72 hours. Please avoid disclosing the issue
publicly until a fix is available.

## Security model

newbot has filesystem, shell, and network capabilities. They are guarded at a single boundary
per concern, and every affected path must use it:

| Boundary | Guard | Rule |
| --- | --- | --- |
| Filesystem paths | Workspace guard | Resolved path must be contained in the workspace; extra roots are capability-specific. |
| Outbound HTTP | Network guard | Loopback, private, link-local, CGNAT, and metadata endpoints are blocked unless explicitly whitelisted. |
| Shell execution | Shell guard + optional OS sandbox | A configured sandbox that cannot start fails closed. |
| Transports | Access policy | Unconfirmed or unauthenticated peers cannot authorize mutations. |
| Secrets / context | Redactor | Secrets stay in environment references; persisted context is bounded and sanitized. |

See [docs/ADR/ADR-007-security.md](./docs/ADR/ADR-007-security.md) and
[.agent/security.md](./.agent/security.md) for the full boundary definitions.

> Note for users: newbot never writes resolved credentials to disk. If a credential is
> exposed (for example pasted into a chat log), rotate it at the provider immediately.
