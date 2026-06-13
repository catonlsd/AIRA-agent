# AIRA-X Operations Guide

The day-to-day reference for running, validating, and observing AIRA-X.
Deployment targets (Render/Railway/VPS/Docker) live in [DEPLOYMENT.md](DEPLOYMENT.md).

## Required configuration

Backend (`backend/.env`, full reference in `backend/.env.example`):

| Variable | Required | Notes |
|---|---|---|
| `LLM_PROVIDER` + matching `*_API_KEY` | **yes** | Startup **fails fast** with a clear error when the key for the selected provider is missing. |
| `EMBEDDING_PROVIDER` | no | `sentence_transformers` (default, ~80 MB model) or `hashing` (no download — used in CI). |
| `CHROMA_DIR`, `DATABASE_URL`, `AIRA_TRACE_LOG` | no | Storage paths are auto-created at startup (`ensure_storage`). |
| `API_KEY`, `CORS_ORIGINS`, `RATE_LIMIT_PER_MINUTE` | recommended for public deploys | Defaults: auth off, localhost CORS + `*.vercel.app` regex, 60 req/min. Set `API_KEY` and explicit `CORS_ORIGINS` for anything public. |

Frontend: `NEXT_PUBLIC_API_URL` (browser-reachable backend URL, **build-time**).

## Local startup

```bash
# Backend
cd backend && python -m venv venv && venv\Scripts\activate   # or source venv/bin/activate
pip install -r requirements.txt && cp .env.example .env       # set the LLM key
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev                     # http://localhost:3000
```

## What "healthy" means

- `GET /health` — **liveness**: the process is up. Used by Docker healthchecks.
- `GET /ready` — **readiness**: core subsystems usable (database query succeeds,
  LLM provider configured). Returns 503 with a per-check breakdown when not.
  Point orchestrator readiness probes here, liveness probes at `/health`.

## CI (GitHub Actions: `.github/workflows/ci.yml`)

Runs on every push and on PRs to `main`:

- **Backend**: Python 3.12 (pip cached) → full pytest suite (320+ tests,
  hermetic — no API keys; `EMBEDDING_PROVIDER=hashing` avoids model downloads).
  This includes the regression wall protecting routed modes, approval/resume,
  evidence-gated completion, and the SSE lifecycle.
- **Frontend**: Node 22 (npm cached) → `tsc --noEmit` → `eslint` → production build.

Any test regression, type error, lint error, or build failure fails the run.

## Logs and traces

- **Request logs** — `aira_x.request`: method, path, status, duration per request.
- **Supervisor lifecycle logs** — `aira_x.supervisor`: one JSON line per
  significant event (`route_chosen`, `clarification_requested`,
  `execution_started`, `runtime_validation_started/finished`,
  `execution_finished`, `turn_completed`), each carrying `session_id`,
  `turn_id`, and `run_id` on completion — grep one id to reconstruct a turn.
  Ops-facing only; never rendered in the chat UI.
- **Turn traces** — append-only JSONL at `storage/traces.jsonl` (override with
  `AIRA_TRACE_LOG`; rotates at 5 MB): route, confidence, candidate routes,
  capabilities, stages, latency, clarification/evidence details.
  Inspect recent turns: `GET /aira-x/traces`.

## What runtime validation covers

For generated projects (after the user approves runtime actions):
dependency install (`pip install -r …` / `npm install`), compile checks
(`compileall`, `npm run build --if-present`), and an import/startup smoke test
for the Python entry module. Failures are classified
(`dependency_install_failed`, `compile_failed`, `import_failed`, …), repaired
once with evidence-targeted regeneration, and reported honestly. It does **not**
yet boot long-running apps or ping HTTP endpoints.

## Guided-flow state (durable)

Pending approval / clarification / plan / runtime-action / artifact state is
**persisted in the database** (`guided_flows` table), not process memory:

- **Restart-safe** — a server restart between "plan ready" and "approve" keeps
  the pending flow; the user can still approve and it resumes.
- **Multi-process-safe** — the request can hit process A and the approval
  process B; the approval loads state from the DB.
- **Idempotent** — resume is a single atomic status flip (`pending` →
  `consumed`), so duplicate clicks / races / retries run the work exactly once;
  a second attempt is told honestly ("already handled").
- **Stale-state honest** — missing / expired (24 h TTL) / already-consumed
  flows resolve to a clear message, never a fabricated re-run.

The `GuidedFlowStore` interface is small and swappable — re-point it at
Redis/Postgres for multi-replica scale-out without touching the supervisor.

## Known limitations (current)

- SQLite + local ChromaDB are single-node; conversation memory is not
  session-scoped server-side; rate limiting is in-memory per replica.
- Artifact generation (PPTX/DOCX) is not yet wired through the evidence-based
  executor.
- No user auth; `API_KEY` is service-to-service.

Architecture is kept compatible with the upgrades above: vector store and
embedding provider are swappable interfaces, traces are structured, and all
pending-state stores sit behind one small store abstraction.
