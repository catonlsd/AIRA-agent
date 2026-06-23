# Resume & profile bullets

Copy-paste-ready, honest, and quantified. Numbers match
[PLATFORM_SUMMARY.md](PLATFORM_SUMMARY.md) and are pinned to the live system by tests.
Pick the variants that fit the role; don't use all of them at once.

---

## Resume bullets (engineering roles)

**Lead / headline**
- Designed and built **AIRA-X**, a production-grade platform combining a streaming
  conversational AI assistant with an **operator-grade incident-sync & observability
  system**, backed by **939 deterministic backend tests, 104 frontend unit tests, and 6
  hermetic end-to-end tests**.

**Systems / backend emphasis**
- Architected an outbound-primary incident-sync subsystem (4 capability-honest adapters,
  5 onboarding profiles) on the invariant that **local state is the source of truth** —
  inbound sync only *observes*, never mutates — eliminating an entire class of
  "external system silently corrupts our data" failures.
- Built a **computed-not-stored readiness model** (8 states derived from durable check
  evidence, ageing to `stale`, invalidated by secret rotation) so integration trust is
  always honest rather than a cached boolean.
- Implemented a **deterministic observability layer** (readiness distribution, 24h/7d/30d
  SLO trends, drift snapshot, threshold-based candidate alerts) computed on read from
  existing audit history — **no duplicate storage, no background aggregation** — with
  `null` (not a misleading 0%) when there's no data.
- Enforced a hard **operator/user trust boundary** (service-key gated, 68 operator
  endpoints) with tests proving zero operator-state leakage into user responses.

**Quality / delivery emphasis**
- Established the platform's regression wall and CI: three parallel GitHub Actions
  workflows (fast-check, e2e, docs) plus **documentation-as-tests** that fail the build
  if docs drift from the live registry (adapter/profile/route counts).
- Authored full production packaging — architecture docs with Mermaid flows, an
  engineering-decision record, runbooks, a deployment blueprint (single-VM → compose →
  Kubernetes path), and SemVer release/rollback processes.

**Product / breadth emphasis**
- Shipped end-to-end across backend (FastAPI, SQLAlchemy, LangGraph), frontend (Next.js
  16 / React 19 / TypeScript), CI/CD, and operations — including a **one-click,
  deterministic, namespaced demo seed** that makes the platform instantly evaluable
  without touching real data.

---

## LinkedIn project bullets (tighter, first person optional)

- **AIRA-X — production-grade AI + operations platform.** A streaming conversational
  assistant plus an operator-grade incident-sync & observability system, behind one
  codebase.
- Built on firm invariants: local state is authoritative, recovery is explicit and
  audited (no auto-remediation), and operator tooling is walled off from the user product
  — all enforced by tests.
- Deterministic by design: computed (not stored) readiness, observability computed on read
  from audit history, and ~1,000 automated tests across backend, frontend, and E2E.
- Packaged like a real platform: architecture docs, runbooks, CI/CD, SemVer releases, and
  a one-click deterministic demo for evaluators.

---

## GitHub project summary (repo description / pinned-repo blurb)

> **AIRA-X** — a production-grade platform pairing a streaming conversational AI assistant
> with an operator-grade incident-sync & observability system. Local state is the source
> of truth, recovery is explicit and audited, and metrics are deterministic and computed
> on read. 939 backend + 104 frontend + 6 E2E tests; full architecture, runbook,
> deployment, and release docs. One-click deterministic demo.

**Short (≤350 chars, for the GitHub "About" field):**
> Production-grade AI assistant + operator-grade incident-sync & observability platform.
> Local state is authoritative, recovery is explicit & audited, metrics are deterministic.
> FastAPI + Next.js. 939/104/6 tests, full docs, one-click demo.

**Suggested topics:** `fastapi` · `nextjs` · `typescript` · `python` · `observability` ·
`incident-management` · `sre` · `llm` · `langgraph` · `production-ready`

---

*Honesty note: every number here is verifiable in-repo (`docs/PLATFORM_SUMMARY.md`, pinned
by `backend/tests/test_docs_packaging.py`). Update these bullets when those counts change.*
