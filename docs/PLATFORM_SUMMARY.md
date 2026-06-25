# AIRA-X — Platform summary (resume-ready)

A one-page, copy-pasteable snapshot of what AIRA-X is and what it proves. Numbers are
pinned by a test that ties this document to the live system (`backend/tests/test_docs_packaging.py`).

---

## At a glance

| Metric | Value |
|---|---|
| **Backend tests** | **931** passing, across **70** test files, deterministic (`pytest -p no:randomly`) |
| **Frontend lib tests** | **104** pure-logic tests (`node --test`, zero deps) |
| **End-to-end tests** | **6** hermetic Playwright tests (Chromium, fully API-mocked) |
| **Incident adapters** | **4** — generic, PagerDuty, Opsgenie (rich), Jira (outbound-only) |
| **Onboarding profiles** | **5** — generic, PagerDuty, PagerDuty-observe-only, Opsgenie, Jira-outbound |
| **Readiness states** | **8** computed states (never stored stale) |
| **Operator endpoints** | **68** service-key-gated routes |
| **Trend windows** | 24h / 7d / 30d, computed on read |

---

## Operator features

- Incident workflow: acknowledge / silence / assign / recover, with a durable action trail.
- Incident export to external tools (outbound-primary; local state stays authoritative).
- Capability + policy + profile model with per-decision `source` attribution.
- Preflight `validate` + safe synthetic `test` (no-op resolve through the real transport).
- Secret rotation that invalidates trust; secrets never returned (`has_secret` only).
- Bounded inbound `refresh` (observe-only) with drift classification.
- Deliberate, audited recovery: refresh / apply / relink / detach / redrive.
- 12 operator runbooks + a troubleshooting matrix + per-state `recommended_action`.
- One-click deterministic demo seed (namespaced, non-destructive) + guided tour.

## Observability features

- Readiness distribution + fleet rollup.
- 24h / 7d / 30d pass-rate trends for validation, reconciliation, refresh, apply,
  external-action, and sync.
- SLO signals (target readiness %, validation %, reconciliation %, sync %) — observed,
  never enforced; `null` on no-data (honest "—").
- Drift snapshot: backlog, by-status, oldest unresolved item + age.
- Deterministic candidate alerts (repeated auth/validation failures, drift backlog,
  stale-readiness) — observations only, no paging.
- Audit summaries: latest meaningful event, last validation pass vs fail, last
  reconciliation — surfaced without dumping history.

---

## Architecture highlights

- **Local state is the source of truth** — external systems never silently become
  authoritative; inbound sync observes, it does not mutate.
- **Explicit, audited recovery** — no auto-heal; every state change is an operator action
  with a stated blast radius.
- **Computed-not-stored readiness & metrics** — derived from durable evidence; same inputs
  → same output; no black boxes.
- **Hard operator/user separation** — service-key boundary, enforced by tests; zero
  operator-capability leakage into the user product.
- **Self-healing schema** — SQLite → Postgres is one env var; idempotent `create_all` +
  additive column migrations on boot.
- **Bounded everything** — sweeps, metrics reads, and trend windows are all capped.

---

## What this demonstrates (for a hiring review)

- Production thinking beyond the happy path: trust boundaries, failure surfacing, recovery,
  and proof.
- Integration design done honestly: capability modeling, policy separation, and audit.
- Deterministic systems discipline: computed state, reproducible metrics, hermetic tests.
- End-to-end ownership: backend, frontend, operator UX, deployment posture, and docs.

Full narrative: **[../README.md](../README.md)** · architecture:
**[ARCHITECTURE.md](ARCHITECTURE.md)** · rationale:
**[ENGINEERING_DECISIONS.md](ENGINEERING_DECISIONS.md)** · evaluation path:
**[DEMO_WALKTHROUGH.md](DEMO_WALKTHROUGH.md)**.

---

*This summary is intentionally static for readability; its key counts (adapters, profiles,
operator endpoints) are verified against the live registry by
`backend/tests/test_docs_packaging.py`, so they cannot silently drift out of date.*
