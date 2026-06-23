# Release process

How AIRA-X is versioned, released, and rolled back. Releases are cut from `main` by a
maintainer; contributors only keep the changelog's `[Unreleased]` section accurate.

---

## Versioning strategy

AIRA-X follows [Semantic Versioning 2.0.0](https://semver.org): `MAJOR.MINOR.PATCH`.

- **MAJOR** — incompatible API/contract changes (none pre-1.0; while `0.x`, minor bumps
  may carry larger changes).
- **MINOR** — additive, backward-compatible functionality (the normal release).
- **PATCH** — backward-compatible bug fixes and docs/tooling-only changes.

Tags are `vMAJOR.MINOR.PATCH` (e.g. `v0.1.0`). `main` is always releasable.

**Pre-1.0 note:** AIRA-X is `0.x`. The public contract may still evolve; we use MINOR for
meaningful additions and PATCH for fixes. We reach `1.0.0` when the API/operator surface
is committed to as stable.

---

## Changelog process

We follow [Keep a Changelog](https://keepachangelog.com).

- Every user/operator-facing PR adds a bullet under `## [Unreleased]` in
  [../CHANGELOG.md](../CHANGELOG.md), grouped by `Added` / `Changed` / `Fixed` /
  `Security` / `Deprecated` / `Removed`.
- At release time, `[Unreleased]` is renamed to the new version with the date, and a fresh
  empty `[Unreleased]` is added on top.
- Docs/CI-only changes may be summarized rather than itemized.

---

## Release checklist

Cut a release from a clean `main`:

1. [ ] `main` is green on **fast-check**, **e2e**, and **docs** workflows.
2. [ ] Run the gates locally one final time:
       `cd backend && python -m pytest -q -p no:randomly` (isolated) and the frontend wall
       (`tsc --noEmit` · `node --test "lib/**/*.test.mts"` · `npm run lint` · `npm run build`).
3. [ ] `npm run e2e` passes (hermetic).
4. [ ] Update [CHANGELOG.md](../CHANGELOG.md): move `[Unreleased]` → `vX.Y.Z (YYYY-MM-DD)`.
5. [ ] Update any version references (`docs/PLATFORM_SUMMARY.md` headline counts, README
       badges) if they changed.
6. [ ] Commit: `chore(release): vX.Y.Z`.
7. [ ] Tag: `git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z`.
8. [ ] Create a GitHub Release from the tag; paste the changelog section as notes.
9. [ ] (If images are published) build & push backend/frontend images tagged `vX.Y.Z`.

## Rollback checklist

If a release is bad in production:

1. [ ] **Re-deploy the previous good tag** (`vX.Y.(Z-1)`) — deployments are stateless
       web + thin worker, so this is a config/image swap, not a data operation.
2. [ ] **Database:** the schema self-heals additively (idempotent `create_all` + additive
       column migrations) and there are no destructive migrations, so a rollback of code
       does **not** require a DB rollback. Confirm no release introduced a column the old
       code writes to as `NOT NULL`.
3. [ ] **Verify** `/health` (liveness) and `/ready` (DB + LLM config) on the restored
       version.
4. [ ] **Operator sweep:** confirm the scheduled `POST /operator/deliveries/sweep` still
       runs so pending syncs flush and stale targets revalidate.
5. [ ] **Communicate:** open a tracking issue, add a `Fixed`/`Security` changelog entry,
       and cut a patch release with the real fix (don't leave the rollback as the fix).

> Because incident-sync recovery is **explicit and audited** and the DB holds references
> (not destructive in-place rewrites), a code rollback is low-risk: no auto-remediation
> could have silently mutated state during the bad release.

---

## Cadence

There is no fixed calendar cadence. Release when a meaningful, tested set of changes has
accumulated on `main`, or immediately for a security fix.
