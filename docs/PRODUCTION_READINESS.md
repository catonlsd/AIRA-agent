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
