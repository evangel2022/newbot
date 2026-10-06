<!--
Thanks for opening a pull request! Please make sure you have read CONTRIBUTING.md.
Fill in the sections below; delete anything that does not apply.
-->

## Summary

<!-- What does this PR change and why? -->

## Type of change

- [ ] feat — new capability
- [ ] fix — bug fix
- [ ] refactor — no behavior change
- [ ] docs — documentation only
- [ ] test — tests only
- [ ] chore — tooling / maintenance

## Verification

<!-- Commands run and the surface verified; see docs/ADR/ADR-009-testing.md -->

- [ ] `python -m pytest`
- [ ] `python -m ruff check src tests`
- [ ] `python -m mypy src/newbot`

## Checklist

- [ ] The change is placed at the correct boundary; the agent core was not modified unless unavoidable
- [ ] New tests protect a reachable contract (no defensive tests for hypothetical states)
- [ ] No blanket code formatter was run
- [ ] No secrets are committed; credentials remain `${ENV}` references
- [ ] Security boundaries still hold for changes touching filesystem, shell, network, or transport access
- [ ] Docs / ADR updated when a boundary or public contract changes
