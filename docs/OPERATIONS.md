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
| `QUOTAS_ENABLED`, `QUOTA_WINDOW_SECONDS`, `MAX_PENDING_FLOWS_PER_OWNER`, `EXECUTION_STARTS_PER_WINDOW`, `ARTIFACT_GENERATIONS_PER_WINDOW`, `STARTUP_VALIDATIONS_PER_WINDOW` | no | Per-principal usage quotas (defaults: on, 3600 s window, 5 / 30 / 20 / 20). Must be positive integers — startup fails clearly otherwise. |
| `ENABLE_BOOT_VALIDATION`, `BOOT_READY_TIMEOUT_SECONDS`, `ENABLE_DOCKER_VALIDATION` | no | Startup/boot verification (defaults: boot on, 8 s readiness timeout, **Docker off**). Docker/compose targets are detected and reported as an honest skip unless this is enabled and Docker is present. |

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
once with evidence-targeted regeneration, and reported honestly.

**Bounded startup/boot verification** goes further when a runnable target is
detected and a safe start command + readiness probe can be derived:

- **Python** — FastAPI (uvicorn) / Flask: launched on an ephemeral port, probed
  at a detected health route (or `/`).
- **Node / JS / TS** — Express/Fastify/Nest/etc. with a `start` script or a
  recognized server dependency + entry file: `npm run start` (or `node <entry>`)
  on an ephemeral port, probed at a detected health route.
- **Next.js** — when a production `start` script exists: built, then `next start`
  on an ephemeral port, probed at `/`.
- **Docker / compose** — detected from `Dockerfile`/`compose.yml`, but **skipped
  honestly** by default (live container boot is gated behind
  `ENABLE_DOCKER_VALIDATION` and requires Docker present).

Every launch is bounded by `BOOT_READY_TIMEOUT_SECONDS`, the process is killed in
a `finally` block (never orphaned), and the launcher/prober are injectable so CI
never spawns real servers. Failures are classified (`node_startup_failed`,
`node_startup_timeout`, `next_startup_failed`, `missing_runtime_dependency`,
`docker_unavailable`, …), repaired once against the evidence-targeted file
(`package.json` for a missing npm module, the server entry for a crash,
`compose.yml`/`Dockerfile` for Docker), and reported without ever claiming an app
"works" that wasn't actually booted. When a target isn't runnable or can't be
safely validated, AIRA-X says what it verified and what it skipped, and why.

## Artifact themes & polish

Artifact generation (PPTX/DOCX/XLSX) runs through one pipeline (plan → content →
generate → validate → deliver) with a small, curated theme catalogue
(`app/artifacts/styles.py`): `professional_clean`, `presentation_dark`,
`modern_report`, `executive_brief`, `spreadsheet_clean`. Themes are kind-scoped
(a deck theme can't be applied to a sheet) and only change appearance —
typography, palette, spacing, header/zebra treatment — never structure, so
validation is unaffected.

Theme resolution is preference-aware with current-turn override: an explicit cue
in the request ("make it **dark / modern / executive**") wins, else the saved
`artifact_style` preference applies, else the kind default.

**Content depth**: artifact content is generated as substantive bullets (full,
specific points — not 1-2 word fragments) plus paragraph-length speaker notes,
and is **grounded in a bounded web-research pass** (`ARTIFACT_RESEARCH_GROUNDING`,
default on) when there are no uploaded documents — so decks/reports carry real
facts and figures. A follow-up that revises the last artifact ("add more detail
to each slide", "include images for each item") regenerates a richer version
through the same pipeline rather than no-opping. When an execution turn can't
find a concrete action it says so honestly (a clarification) — never a fake
"Execution complete".

**Images** are optional and safe (`ENABLE_ARTIFACT_IMAGES`, default on;
`MAX_ARTIFACT_IMAGES`, `ARTIFACT_IMAGE_TIMEOUT_SECONDS`). The provider
(`app/artifacts/image_providers.py`, Openverse — CC-licensed, commercial filter)
is registered at startup, bounded (short timeout, capped size, PNG/JPG/GIF only),
per-query cached, and fully guarded: any failure falls back to text-only and
generation never breaks. A deck only reports images when one was **actually
inserted** (`image_count`), never a fake "rich visuals" claim. The artifact card
surfaces the theme name, structural counts, image count (when > 0), size, and
validation status — clean metadata, no internals.

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

## Access boundaries (ownership)

Every owned resource is scoped to a **principal** (`app/auth.py`): an
authenticated API-key caller when `API_KEY` is set, otherwise the client
session. The `owner_key` tags the resource; an opaque HMAC `owner_token` scopes
download URLs and directories.

- **Guided flows** (plan/runtime/artifact approval, clarification) are
  owner-keyed in the durable store — one principal can't approve, resume, or
  inspect another's pending flow.
- **Artifacts** are written under an owner-scoped directory and served via
  `GET /artifacts/{owner_token}/{filename}` — route-level isolation + path-
  traversal guard; cross-owner filename guessing fails. When `API_KEY` is set,
  an authenticated caller must additionally match the owner.
- **Documents** are ingested with an `owner` and retrieval filters by it, so
  one user's uploads never surface in another's document-first answers.

## Document-grounded answer quality

Uploaded-document answers run a small, swappable retrieval pipeline above the
vector store (Chroma stays behind its adapter):

- **Chunking** is section/page-aware (`app/rag/chunker.py`): never crosses page
  boundaries, splits on heading/paragraph boundaries, carries the heading into
  each chunk for context, and overlaps within a section. Metadata keeps file,
  document id, owner, page, and section.
- **Reranking** (`app/rag/reranker.py`, `RERANK_CANDIDATE_K`, default 12): a wide
  candidate pool is reranked by blended vector + query-term relevance and
  de-duplicated, then trimmed to `RETRIEVAL_K`. A chunk's score stays the raw
  vector similarity, so the sufficiency threshold keeps its meaning.
- **Evidence strength** (`app/rag/evidence.py`): grounded answers are tagged
  `strong` / `partial` / `weak` / `conflicting` (and `none` → honest
  insufficiency + web fallback). Strength drives a subtle, honest qualifier in
  the answer and the provenance line ("Answered from your uploaded files",
  "… — partial coverage", "appear inconsistent on this point"). Raw scores,
  chunk ids, and collection internals never reach the UI; they live in meta.

## Accounts & identity (account-first ownership)

AIRA-X has a real account model on top of the principal abstraction:

- **Accounts** (`accounts` table, `app/accounts.py`): email + bcrypt password +
  display name, with a reserved `workspace_id` for future team scope. Endpoints:
  `POST /auth/register`, `POST /auth/login`, `GET /auth/me`, `POST /auth/logout`.
- **Stateless tokens** (`app/auth.py`): login returns an HMAC-signed, expiring
  token (`AUTH_SECRET`, `AUTH_TOKEN_TTL_SECONDS`). A request carrying
  `Authorization: Bearer <token>` resolves to an **account principal**, owner
  scope `account:<id>` — durable and cross-device.
- **Account-first, session-secondary**: `resolve_owner(request, session_id)`
  returns the account owner when authenticated, otherwise the session id
  (unchanged anonymous/local behaviour). Turns, preferences, uploaded documents,
  guided flows, and artifacts all use this owner, so signed-in data follows the
  user across devices while anonymous use stays session-scoped — an explicit,
  honest distinction. The artifact download route additionally enforces the
  account's `owner_token`.

The frontend Settings page has a minimal **Account** card (sign in / create
account / sign out); when signed in, chat, uploads, and preferences send the
bearer token automatically.

## Resource scope & workspaces (foundation)

Ownership is now an explicit **scope** (`ResourceScope` in `app/auth.py`):
session, account, or workspace. `resolve_scope(request, session_id)` returns the
active scope and `resolve_owner` delegates to it, so the durable owner key stays
backward-compatible — a session owns its raw id, an account owns `account:<id>`,
and a **workspace** owns `workspace:<id>`. Nothing downstream changed shape;
scope just became explicit and extensible.

- **Workspaces** (`workspaces` / `workspace_members` tables, `app/workspaces.py`):
  a durable shared scope with an owner account and real membership rows.
  Endpoints: `GET /workspaces` (mine), `POST /workspaces` (create; creator is
  owner). No invitations/roles UI yet — foundations only.
- **Membership-gated**: a request may act in a workspace by sending
  `X-Workspace-Id`, but the header is honoured **only when the account is a
  member** — otherwise it silently falls back to personal scope, never leaking
  another team's data. Artifact downloads authorize against the set of owner
  tokens an account can reach (personal + member workspaces).
- **Default is Personal**: with no workspace header the experience is identical
  to single-user account scope. The frontend plumbs an `X-Workspace-Id` header
  (`lib/scope.ts`) and shows a calm "Scope: Personal" line — no switcher yet.

Workspace-level preferences/quotas, shared documents/artifacts/runs, and roles
all layer on this without changing the owner-key call sites.

## Memory model (session + preference)

Memory is intentional, scoped, and bounded — not indiscriminate recall:

- **Preference memory** (`app/memory/preference_memory.py`, table `memory_entries`):
  durable and **owner-scoped** (same principal model as guided flows/artifacts —
  no cross-owner leakage). Only a fixed catalogue of product-shaping keys can ever
  be written (answer length/format/style, artifact style, fallback default) — it
  is structurally impossible to store names, identity, or arbitrary facts.
- **Session memory** (`app/memory/session_memory.py`): ephemeral, process-local,
  scoped to (owner, session) — the active working context. Never auto-promoted to
  durable storage.
- **Write policy** (`app/memory/preference_policy.py`): a preference is stored only
  from a deliberate statement ("keep answers concise", "I prefer code-first") —
  one-off questions never write. **Read/apply policy**: saved preferences shape the
  answer-style system prompt and artifact generation **as defaults**, and the
  directive states the current message overrides them — the current turn always
  wins. Self-memory answers ("what do you remember about me?") report saved
  preferences honestly and never invent personal details.

Nothing about memory surfaces in the chat UI as a panel; preferences quietly
improve output and self-memory answers are honest. The store interface is small
and swappable for later settings/edit UI and team/workspace preferences.

- **User control surface**: `GET/PUT/DELETE /preferences` (`app/routes/preferences.py`)
  is owner-scoped and exposes only the product-approved catalogue — list, set,
  clear-one, clear-all. Invalid keys/values are rejected (400); one owner can
  never see or change another's. The frontend Settings page renders an
  "Assistant Preferences" card (`frontend/lib/preferences.ts`) with human labels,
  segmented controls, per-preference remove, and a confirmed clear-all — no raw
  keys or storage internals. Session/task context is deliberately kept out of
  this surface. The browser session id is now persisted (`frontend/lib/session.ts`)
  so preferences edited in Settings apply to the same session's chat answers.

## Known limitations (current)

- SQLite + local ChromaDB are single-node; conversation memory is not
  session-scoped server-side; rate limiting is in-memory per replica.
- Artifact generation (PPTX/DOCX) is not yet wired through the evidence-based
  executor.
- No user auth; `API_KEY` is service-to-service.

Architecture is kept compatible with the upgrades above: vector store and
embedding provider are swappable interfaces, traces are structured, and all
pending-state stores sit behind one small store abstraction.
