# AIRA-X — Production Readiness & Persistence Audit

Companion to `DEPLOYMENT.md` (which covers *where* to host). This document is the
honest *assumptions audit*: what is production-safe today, what is acceptable-for-now,
and what must be upgraded before a commercial multi-instance deployment. Infrastructure
is swappable **behind existing seams** — none of the ownership, queue, incident, or
operator abstractions change when storage or process topology is hardened.

---

## 1. Process topology (web vs worker)

Two **separate process roles**, already cleanly split:

| Role | Command | Responsibility |
|---|---|---|
| **Web / API** | `uvicorn app.main:app` | HTTP, inline turns, operator APIs. Never depends on the worker for inline paths. |
| **Worker** | `python -m app.worker` | Durable executor: claims and runs one queued job at a time (`ExecutionQueueService.run_once`). |

- The worker is a **thin driver** — all state, idempotency, and bounded retry live in
  the queue service. Scaling out is "run more workers": the atomic single-`UPDATE`
  claim guarantees each job runs exactly once even with N workers.
- **Deploy them as separate units** so web latency and worker throughput scale
  independently and a worker crash never takes down the API.

**Acceptable-for-now:** both in one host for local/dev. **Must-upgrade for commercial:**
separate web and worker deployments behind the same DB.

---

## 2. Persistence posture (per durable store)

`settings.database_url` defaults to **SQLite** (`storage/research_assistant.db`).
The engine branches on the URL scheme, but PostgreSQL is not yet deployable by
configuration alone: a driver and versioned migration path are missing. All
models are currently plain SQLAlchemy `Base` tables created via `create_all` plus
self-healing `ensure_runtime_columns` ALTERs.

| Durable store | Backed by | Status | Notes |
|---|---|---|---|
| Accounts / workspaces / memberships | DB | **must-upgrade** | Postgres for multi-instance + row-locking. |
| Guided flows, preferences, pins, bundles, activity | DB | **must-upgrade** | Same DB; same upgrade. |
| Execution queue (`execution_jobs`) | DB | **must-upgrade** | The atomic claim relies on a transactional `UPDATE`; SQLite is single-writer (fine locally, won't scale write-concurrency). Postgres (or Redis/RQ later) is the production path — the queue is already a swappable service. |
| Observability / webhook delivery / incidents | DB | **must-upgrade** | Same DB. |
| **Incident sync** (targets, links, records, reconciliation, **target check history**) | DB | **must-upgrade** | Same DB. Secrets stored for HMAC signing — see §4. |
| Artifacts (generated files) | **local filesystem** (`storage/`, `backend/storage/artifacts/`) | **must-upgrade** | Ephemeral on most PaaS. Move to object storage (S3/GCS) behind the artifact delivery seam; DB holds references, not blobs. |
| Vector store (Chroma) | local dir (`AIRA_CHROMA_DIR`) | **acceptable-for-now** | Persisted dir; for multi-instance use a hosted vector DB or shared volume. |
| Turn traces | JSONL file (`AIRA_TRACE_LOG`) | **acceptable-for-now** | Debug stream; ship to a log aggregator in production. |

### SQLite to PostgreSQL is a planned migration, not an environment-only switch

Although SQLAlchemy accepts a PostgreSQL URL, the repository does not currently
ship a PostgreSQL driver or versioned schema migrations. Local file APIs and both
vector indexes also remain single-host. See `PERSISTENCE_AND_RECOVERY.md` for the
supported internal-preview topology and the work required before scaling out.

---

## 3. Health & readiness

- **`GET /health`** — liveness (process up) → container liveness probe.
- **`GET /ready`** — readiness: checks the **database** (`SELECT 1`) and LLM config;
  non-200 when a critical dependency is unusable → load-balancer readiness gate.

**Per-integration readiness** (incident-sync targets) is a separate, operator-driven
layer — preflight `validate`, safe synthetic `test`, computed readiness that ages out
to `stale`, and bounded scheduled revalidation. See `OPERATIONS.md`. A target is never
trusted on "save config and hope."

---

## 4. Secret hygiene

- Incident-sync target **secrets are stored** (for HMAC `X-AIRA-Signature` signing)
  but **never returned** by any read API — reads expose `has_secret` only.
- **Rotation is first-class:** `POST /operator/incident-targets/{id}/rotate-secret`
  (or a secret/URL change via PATCH) **invalidates prior readiness evidence** (the
  target reads `unverified` until revalidated) and records the change in durable target
  check history.
- **Production hardening:** encrypt the secret column at rest (DB TDE or app-level
  envelope encryption); inject `API_KEY` and `DATABASE_URL` via the platform
  secret manager. Operator routes are globally gated by `APIKeyMiddleware` when
  `api_key` is set.

---

## 5. Backups & recovery

| Asset | Backup | Recovery |
|---|---|---|
| DB (initial preview: SQLite) | Coordinated encrypted volume backup | Restore the matching storage generation; run integrity and smoke checks. |
| Artifacts (initial preview: persistent volume) | Back up with DB/uploads/indexes | Restore the matching storage generation. |
| Incident target config | In DB | Restored with the DB; re-inject/rotate secrets if excluded from backup scope. |
| Vector store | Periodic volume snapshot | Re-index from source documents (documents are the source of truth). |

**Principle:** the DB holds **references**, not large blobs — backups stay small and a
blob-store restore is independent.

---

## 6. Pre-deploy environment checklist

- [ ] `DATABASE_URL` points to SQLite on the persistent preview volume.
- [ ] `API_KEY` and a distinct `AUTH_SECRET` are set.
- [ ] Uploads, artifacts, traces, and both indexes use the same persistent volume.
- [ ] Initial preview uses one web process and `QUEUE_ARTIFACTS=false`.
- [ ] Liveness → `/health`, readiness → `/ready` wired to the platform.
- [ ] LLM provider key + model configured; `/ready` passes.
- [ ] Secrets injected via the platform secret manager, not committed.
- [ ] Operator sweep (`POST /operator/deliveries/sweep`) scheduled so pending syncs
      flush, links reconcile, and stale targets revalidate.

---

## 7. What stays the same after hardening

Hardening is **infrastructure-only**: scope/ownership boundaries, the durable queue +
thin worker, the incident workflow, the capability/policy/profile model, and operator
readiness all sit behind stable seams. SQLite→Postgres and local-disk→object-storage
change configuration, not contracts — which is exactly why the architecture stays
explainable in 2–3 minutes.

---

## 8. Operator runbooks (incident operations)

Every procedure is **deliberate and audited** — AIRA-X never auto-mutates incident or
external state. The console surfaces a deterministic `recommended_action` per target /
incident (a fixed table, never AI advice); these runbooks are what that action means.
All actions require the operator service key.

**Where to look first:** `GET /operator/incident-targets/attention/summary` (rollup +
oldest item) for targets, and an incident's sync summary (`recommended_action`,
`last_reconciliation`) for one incident.

### 8.1 Target onboarding
1. Create the target (name, URL, kind, optional secret, profile/preset). It starts
   `unverified` → `recommended_action: validate`.
2. **Validate** (`POST .../validate`) — confirms config + (for refresh-capable kinds)
   connectivity. Expect `ready`.
3. **Test** (`POST .../test`) — sends a synthetic, no-op resolve through the real
   adapter transport (`TEST_SIGNAL`), touching **no** real incident. Expect "Test event
   sent."
4. Enable it. A target is never trusted on "save and hope" — `ready` requires evidence.

### 8.2 Validation failure (`degraded`, action `validate`)
Last check failed (non-auth, non-test). Re-run **Validate**. If it persists: confirm the
endpoint URL/host is reachable and the vendor isn't degraded; check `last_check_error` on
the target's health view. Stays out of `ready` until a check actually passes.

### 8.3 Auth failure (`auth_failed`, action `rotate_secret`)
The endpoint rejected the signature/credentials (HTTP 401/403). → **§8.5 Secret
rotation**, then **Validate**. Do not just re-validate with the same secret.

### 8.4 Readiness degradation / staleness (`stale`, action `validate`)
A previously-`ready` target whose last success aged past
`incident_target_revalidate_seconds` (default 7d) reads `stale` — *not* falsely `ready`.
Re-run **Validate** (the scheduled sweep also revalidates a bounded batch). `check_summary.last_validation_ok`
shows when it last genuinely passed.

### 8.5 Secret rotation (action `rotate_secret`)
1. `POST .../rotate-secret` with the new secret (or change secret/URL via PATCH). This
   **invalidates prior readiness evidence** → the target reads `unverified` and the
   rotation is recorded in `check_history` (secret value never logged/returned).
2. **Validate**, then **Test**. The target is untrusted until it re-passes.

### 8.6 Drifted incident (`drifted`, action `refresh` → maybe `apply_resolved`)
Local and last-observed external state disagree (e.g. external resolved, local open).
1. **Refresh** (`POST /operator/incidents/{id}/sync/refresh`) to re-observe external
   state — refresh **never** mutates the local incident.
2. If the summary then offers `apply_resolved`, **Apply** to recover the local incident
   deliberately (audited, logged as a reconciliation event). Never auto-applied.

### 8.7 Missing external reference (`missing_external`, action `detach`)
The external incident no longer exists. Either **Detach** the dead link (§8.9) or
**Relink** to a valid reference (§8.8). The local incident is untouched.

### 8.8 Relink workflow (action `relink`)
For a detached or missing link on a refresh-capable target: `POST
.../sync/relink` with a valid external ref. The adapter validates the reference before
the link is re-established; sync resumes only on success.

### 8.9 Detach workflow (action `detach`)
`POST .../sync/detach` removes the linkage **only** — local and external state are both
left as-is (`detached_at` recorded). Use when an external incident was deleted/migrated
or the link was wrong. Reversible via relink.

### 8.10 External apply workflow (action `apply_resolved`)
Only offered when external state was actually observed to disagree (e.g. external
resolved while local open). **Apply** brings the *local* incident into line with the
observed external state — a one-way, audited recovery. It is never automatic and never
pushes outward.

### 8.11 External resolve / reopen / acknowledge
Operator-initiated **outbound** state changes (`POST .../sync/external-action`) on
vendor-typed adapters that advertise the capability. The console only shows actions the
adapter actually supports — no fake vendor claims. Each carries an explicit blast-radius
label ("changes external state") and is audited.

### 8.12 Recovery after accidental disablement
A disabled target reads `disabled` (`recommended_action: enable`) and its disable/enable
transitions are in `check_history`. Re-enable via PATCH `enabled: true`; readiness
recomputes from existing evidence (re-**Validate** if it had aged to `stale`). Disabling
never deletes config, history, or links — re-enabling is non-destructive.

---

## 9. Troubleshooting matrix

| Symptom (state / status) | `recommended_action` | First move | If it persists |
|---|---|---|---|
| Target `unverified` | `validate` | Validate, then Test | Check URL/kind/profile config |
| Target `degraded` | `validate` | Re-validate | Endpoint reachable? vendor degraded? check `last_check_error` |
| Target `auth_failed` | `rotate_secret` | Rotate secret → Validate | Confirm the receiver's expected secret |
| Target `invalid_config` | `fix_config` | Correct URL/profile → Validate | Check policy warnings (ineffective overrides) |
| Target `test_failed` | `test` | Re-Test once endpoint recovers | Inspect receiver logs for the `TEST_SIGNAL` event |
| Target `stale` | `validate` | Re-validate | Confirm scheduled sweep is running |
| Target `disabled` | `enable` | Re-enable if it should be active | — |
| Incident `drifted` | `refresh` | Refresh; Apply if offered | Confirm external actually changed |
| Incident `missing_external` | `detach` | Detach, or Relink to a valid ref | Verify the external incident still exists |
| Incident `stale` link | `refresh` | Refresh | Check the target is enabled + refresh-capable |
| Link `detached` | `relink` | Relink to a valid ref | Confirm the target supports relink validation |

**Triage entry points:** `GET /operator/incident-targets/attention/summary` →
`rollup` / `by_state` / `by_action` / `oldest`. Per-target audit: `GET
.../health` → `check_summary` (last pass vs last fail) + `check_history`.

---

## 10. Rollout guidance

1. **Onboard one target end-to-end** before fanning out — validate → test → enable
   (§8.1). Prove the receiver accepts the synthetic test event.
2. **Schedule the operator sweep** (`POST /operator/deliveries/sweep`) so pending syncs
   flush, links reconcile, and stale targets revalidate within the bounded per-sweep cap.
3. **Watch the attention rollup**, not individual targets — `oldest` surfaces the
   longest-waiting problem; `by_action` tells you the dominant failure class (e.g. a wave
   of `rotate_secret` after a credential epoch change).
4. **Treat `stale` as a prompt, not an outage** — it means *re-verify*, and the sweep
   handles a bounded batch automatically.
5. **Keep recovery deliberate.** Apply/relink/detach are operator decisions with an
   audited trail and an explicit blast radius — there is intentionally no "auto-heal."

---

## 11. Metrics glossary (incident-sync observability)

All metrics are served by `GET /operator/incident-sync/metrics`, **computed on read**
from existing audit/history — no duplicate storage, no background jobs. Same rows + same
clock → same numbers.

| Metric | Where it comes from | Meaning |
|---|---|---|
| `readiness.distribution` | computed readiness of every target | count per readiness state (point-in-time) |
| `readiness.ready / attention / disabled` | same | fleet rollup: trusted vs needs-work vs intentionally off |
| `readiness.stale / auth_failed` | same | targets aged out of trust / rejecting credentials right now |
| `windows.validation.<w>` | `validate`/`revalidate` check events | pass/fail/neutral + pass rate per window (`ready` = pass) |
| `windows.reconciliation.<w>` | reconciliation events (all actions) | repair-action outcomes per window |
| `windows.refresh / apply / external_action.<w>` | reconciliation events by category | outcomes for that action class |
| `windows.sync.<w>` | sync records | outbound export success/failure per window |
| `drift.backlog` | active (non-detached) links | count of drifted/missing/stale links now |
| `drift.oldest.age_seconds` | oldest actionable link | how long the longest-standing drift has gone unresolved |
| `alerts[]` | thresholds over the above | deterministic candidate observations (see §13) |

**Windows** are fixed: `24h` = 86 400s, `7d` = 604 800s, `30d` = 2 592 000s. Reads are
bounded to the `5000` most-recent rows per stream.

**`pass_pct` semantics:** numerator = `pass`, denominator = `pass + fail` (neutral
excluded). **`null` means zero decided samples** — render it as "—", never as 0% or 100%.

---

## 12. SLI / SLO definitions

These are **service-level *indicators*** — observed, never enforced. AIRA-X has no code
path that blocks, throttles, or pages on them.

| Indicator | Definition | Healthy band (console tone) |
|---|---|---|
| **Target readiness %** | `ready / enabled` targets | ≥99 good · ≥90 warn · <90 bad |
| **Validation pass % (24h)** | `ready` validations / decided validations, 24h | same bands |
| **Reconciliation success % (24h)** | `ok` / (ok+fail) reconciliation actions, 24h | same bands |
| **Sync success % (24h)** | `synced` / (synced+failed) records, 24h | same bands |

Tone bands are deterministic constants in `frontend/lib/operator.ts` (`sloTone`). A
`null` indicator (no data yet) renders muted, not alarming. Pick your own internal
targets per environment; the platform only *shows* the number.

---

## 13. Operational review checklist

A bounded, repeatable pass (e.g. start of shift / weekly review). Everything here is one
`GET /operator/incident-sync/metrics` plus the Incidents-tab "Sync observability" panel.

- [ ] **Readiness rollup** — is `attention` trending up vs the team's baseline?
- [ ] **SLOs** — any of the four indicators in the `warn`/`bad` band? Note which.
- [ ] **Candidate alerts** — triage `critical` first. Each maps to a runbook (§8):
      `repeated_auth_failures` → §8.5, `repeated_validation_failures` → §8.2,
      `drift_backlog` → §8.6/§8.7, `stale_readiness` → §8.4.
- [ ] **Drift backlog** — is the count and the `oldest` age growing across reviews?
- [ ] **Trend windows** — compare `24h` vs `7d` vs `30d` pass rates: is a metric
      *degrading* (24h worse than 30d) or *recovering* (24h better)?
- [ ] **Sweep health** — is the scheduled sweep running (pending syncs flushing, stale
      targets revalidating)? A rising `stale_readiness` alert often means it isn't.

---

## 14. Degradation interpretation guide

How to read what the metrics are telling you — deterministic patterns, not guesses.

| Pattern you observe | Most likely meaning | Where to act |
|---|---|---|
| `validation_pass_pct_24h` ≫ below `7d`/`30d` | a target (or its endpoint) just started failing | §8.2 / §8.3; check `windows.validation` per-target via attention rollup |
| `repeated_auth_failures` on one target | secret/credential expired or rotated upstream | §8.5 rotate → revalidate |
| `drift_backlog` rising across reviews, `oldest` age growing | external systems changing state faster than refresh/apply clears them | §8.6 refresh then apply; confirm the sweep cadence |
| `stale_readiness` climbing | the scheduled sweep isn't revalidating (or the window is too short) | check sweep schedule; §8.4 |
| `reconciliation_failures` ≥ threshold | refresh/relink hitting an unreachable or changed external API | inspect the targets in the failed events; §8.2 |
| `sync_success_pct_24h` dropping, `validation` healthy | outbound delivery problem (network/endpoint), not config | check sync records' `last_error`; redrive (§8.x) |
| All SLOs `null` | no activity in window — not a failure, just quiet | none; confirm targets are enabled if you expected traffic |

**Trend, don't snapshot.** A single bad number is noise; the same metric worse in `24h`
than in `30d` is a real regression. The three windows exist precisely so degradation is
*observable over time* without an analytics warehouse.

**Point-in-time vs trend.** `drift_backlog` and `stale_readiness` are current counts —
true historical trending of a point-in-time count would need periodic snapshots, which
we deliberately do **not** store (no duplicate storage). Instead, candidate alerts fire
on the *current* backlog, and the event-rate windows (validation/reconciliation/sync)
give you the time-series signal. Compare backlog counts across your own review cadence to
see growth.
