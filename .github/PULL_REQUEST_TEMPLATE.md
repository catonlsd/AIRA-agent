<!-- Thanks for contributing to AIRA-X. Keep PRs small and focused. -->

## What & why
<!-- One paragraph: what does this change and why? Link the issue: Closes #NNN -->

## Type of change
- [ ] Bug fix (non-breaking)
- [ ] Feature (additive, non-breaking)
- [ ] Docs / tooling / CI
- [ ] Refactor (no behavior change)

## Invariants preserved
<!-- AIRA-X's guarantees are non-negotiable. Confirm each that applies: -->
- [ ] Local state remains the source of truth; inbound sync still never mutates local state
- [ ] Recovery stays explicit + audited (no new auto-remediation)
- [ ] Operator/user separation intact (no operator state leaks into user responses)
- [ ] No breaking API / DB / UX changes (additive only)
- [ ] Deterministic & explainable (no opaque/AI operational advice)

## Tests
- [ ] `cd backend && python -m pytest -q -p no:randomly` passes (run in isolation)
- [ ] `cd frontend && ./node_modules/.bin/tsc --noEmit && node --test "lib/**/*.test.mts" && npm run lint && npm run build` passes
- [ ] E2E unaffected, or `npm run e2e` passes
- [ ] New behavior is covered by a test (and I did not remove existing tests)

## Docs
- [ ] Updated relevant docs (README / OPERATIONS / ARCHITECTURE / CHANGELOG) if behavior or interfaces changed
- [ ] Added a `CHANGELOG.md` entry under `[Unreleased]` if user/operator-facing

## Screenshots / evidence
<!-- For UI or operator-console changes, attach before/after. For backend, paste the
     passing test output. Redact any secrets. -->
