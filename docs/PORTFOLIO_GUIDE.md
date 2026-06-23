# Portfolio guide

How to evaluate AIRA-X efficiently, tailored to who's reading. Each path is short and
ends with a concrete "what you'll conclude." Pair any of them with the hands-on
[DEMO_WALKTHROUGH.md](DEMO_WALKTHROUGH.md).

---

## Reading orders by role

### Recruiter (3 minutes)
1. [README.md](../README.md) — the headline metrics table + feature matrix.
2. [PLATFORM_SUMMARY.md](PLATFORM_SUMMARY.md) — the one-page numbers.
3. Skim a Mermaid diagram in [ARCHITECTURE.md](ARCHITECTURE.md).

**You'll conclude:** real scope (two production surfaces, 939 + 104 + 6 tests), and that
it's documented and maintained like a real platform — not a tutorial project.

### Staff / senior engineer (15 minutes)
1. [ARCHITECTURE.md](ARCHITECTURE.md) — boundaries, the four flows, trust/security/audit.
2. [ENGINEERING_DECISIONS.md](ENGINEERING_DECISIONS.md) — the *why* behind the invariants.
3. Code spot-checks: `backend/app/incident_sync.py` (readiness + drift),
   `backend/app/incident_metrics.py` (pure, deterministic metrics),
   `backend/tests/test_incident_sync.py` (how guarantees are pinned).
4. CI: `.github/workflows/` (fast-check / e2e / docs).

**You'll conclude:** the author reasons about trust boundaries, determinism, and failure
recovery; the tests are the proof, not decoration.

### Startup CTO (10 minutes)
1. [README.md](../README.md) — "Why AIRA-X exists" + the operator/observability sections.
2. [DEMO_WALKTHROUGH.md](DEMO_WALKTHROUGH.md) — seed it, watch the SLO dashboard + a live
   candidate alert appear.
3. [DEPLOYMENT_BLUEPRINT.md](DEPLOYMENT_BLUEPRINT.md) + [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md)
   — how it ships and what it costs to operate.

**You'll conclude:** this could be operated by a real team — explainable state, deliberate
recovery, a deployment story, and no magic.

### Open-source maintainer (5 minutes)
1. [CONTRIBUTING.md](../CONTRIBUTING.md) + [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md) +
   [SECURITY.md](../SECURITY.md).
2. `.github/` templates and workflows.
3. [RELEASE_PROCESS.md](RELEASE_PROCESS.md) + [CHANGELOG.md](../CHANGELOG.md).

**You'll conclude:** contribution, disclosure, CI, and release processes are all in place
and self-enforcing (docs are pinned by tests).

---

## Demo script (≈5 minutes, live)

> Full version with commands: [DEMO_WALKTHROUGH.md](DEMO_WALKTHROUGH.md).

1. **Frame it (20s):** "AIRA-X is two surfaces — a conversational assistant, and an
   operator-grade incident-sync platform. The interesting engineering is the second one."
2. **Seed (15s):** Operator console → Incidents → **Seed demo data**. "One click, fully
   deterministic, namespaced — it never touches real data."
3. **Readiness (45s):** "Six targets across every readiness state. This isn't a stored
   label — it's computed from evidence. The stale one passed validation 9 days ago."
4. **Observability (60s):** "This whole SLO dashboard is computed on read from audit
   history — no metrics tables, no background jobs. Here's a live candidate alert: 4 auth
   failures in 24h. It's an *observation*, not a page — nothing auto-fires."
5. **Drift recovery (60s):** Expand the drifted incident. "External says resolved, local
   says open. Refresh only *observes*. **Apply** is the only thing that changes local
   state — and it's explicit and audited. There is no auto-heal, by design."
6. **Separation (20s):** Open `/chat`. "None of that operator surface is reachable here —
   it's service-key gated, and tests enforce it."
7. **Close (20s):** "Computed state, deterministic metrics, deliberate recovery, hard
   boundaries — that's the difference between an AI demo and a platform."

---

## Architecture talking points

- **Local state is the source of truth.** Inbound sync observes; it never mutates. This is
  the single invariant everything else hangs on.
- **Capability ≠ policy ≠ profile.** Honesty about what an adapter *can* do, separated from
  what a target is *configured* to do — every decision reports its `source`.
- **Computed, not stored.** Readiness and all metrics are derived from durable evidence;
  same inputs → same output. Nothing rots into a stale status string.
- **Deliberate recovery.** No auto-remediation; every state change is an audited operator
  action with a stated blast radius.
- **Observability without a warehouse.** Metrics are one bounded read, computed on demand;
  `null` (not a fake 0%) when there's no data.
- **Boundaries enforced by tests.** Operator/user separation and "no operator field leaks
  into user responses" are pinned, not promised.

---

## Interview discussion points

Questions you can go deep on (and the honest answers):

- *"How do you stop an external system from corrupting your state?"* → the inbound-never-
  mutates invariant; drift is surfaced, not applied; only explicit `apply` changes local.
- *"How is readiness not just a cached boolean?"* → it's computed from timestamped check
  evidence every read; it ages to `stale`; rotation invalidates it.
- *"Why no auto-remediation?"* → the 3 a.m. failure mode; trust + auditability over
  convenience; see [ENGINEERING_DECISIONS.md](ENGINEERING_DECISIONS.md) §2/§8.
- *"How do you keep metrics trustworthy?"* → pure functions over existing audit rows,
  computed on read, bounded; no second source of truth. `null` is honest "no data".
- *"How would you scale / deploy this?"* → stateless web + thin worker, one DB, SQLite→
  Postgres via one env var; see [DEPLOYMENT_BLUEPRINT.md](DEPLOYMENT_BLUEPRINT.md).
- *"How do you keep docs from lying?"* → packaging tests assert docs exist, cover required
  sections, and that counts match the live registry (Phase 7/8 quality gates).
- *"What would you do next?"* → Postgres multi-replica, encrypted secret column at rest,
  and a notification channel layered *on top of* candidate alerts (never inside them).
