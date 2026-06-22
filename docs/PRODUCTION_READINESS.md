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

`settings.database_url` defaults to **SQLite** (`storage/research_assistant.db`). The
engine already branches on the URL scheme (`check_same_thread` only for SQLite), so
**pointing at Postgres is a single env var** — no code change. All models are plain
SQLAlchemy `Base` tables created via `create_all` + self-healing
`ensure_runtime_columns` ALTERs.

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

### The one real migration (SQLite → Postgres)
```bash
export AIRA_DATABASE_URL="postgresql+psycopg://user:pass@host:5432/aira"
# First boot creates tables (create_all) and applies additive ensure_runtime_columns().
```
Web/worker split, operator tooling, and incident workflows are unchanged.

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
  envelope encryption); inject `AIRA_API_KEY` and `AIRA_DATABASE_URL` via the platform
  secret manager. Operator routes are globally gated by `APIKeyMiddleware` when
  `api_key` is set.

---

## 5. Backups & recovery

| Asset | Backup | Recovery |
|---|---|---|
| DB (Postgres) | Managed snapshots + PITR | Restore; `create_all` + `ensure_runtime_columns` are idempotent on boot. |
| Artifacts (object storage) | Bucket versioning + lifecycle | Re-point store; references are DB rows, not inline blobs. |
| Incident target config | In DB | Restored with the DB; re-inject/rotate secrets if excluded from backup scope. |
| Vector store | Periodic volume snapshot | Re-index from source documents (documents are the source of truth). |

**Principle:** the DB holds **references**, not large blobs — backups stay small and a
blob-store restore is independent.

---

## 6. Pre-deploy environment checklist

- [ ] `AIRA_DATABASE_URL` → managed Postgres (not the SQLite default).
- [ ] `AIRA_API_KEY` set → operator routes gated (unset only for trusted local dev).
- [ ] Artifact storage → durable object storage (not ephemeral local disk).
- [ ] Web and worker deployed as **separate** units against the same DB.
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
