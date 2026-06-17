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

## Scope-aware preferences, quotas & documents

Workspace behaviour is **additive and explicit**, never a rewrite of personal mode:

- **Preference precedence** (low → high): product default < personal/account
  default < workspace default (when acting in workspace scope) < current-turn
  instruction. `preference_memory.effective([personal, workspace])` layers the
  personal default under the workspace one, so a workspace sets shared defaults
  while a user's personal preference still fills any gap. A preference *stated*
  while acting in a workspace becomes a **workspace** default; in personal scope
  it's personal. The current message always wins at answer time. The preferences
  API/UI edits the **active scope** and labels it ("Editing Personal / Team
  defaults").
- **Quotas** are scope-aware through the owner key: personal usage counts under
  `account:<id>`/session and workspace usage under `workspace:<id>`, so they're
  isolated automatically. Workspace owners resolve to independently-tunable
  workspace limits (`WORKSPACE_*_PER_WINDOW`, defaulting to the personal limits).
- **Document collections** scope by owner too: uploads and document-first
  retrieval in workspace scope use `workspace:<id>`, personal use stays
  `account:<id>`/session — no cross-workspace or workspace/personal leakage, with
  the Chroma `where` filter unchanged.

## Roles, permissions & operator boundary

Workspace access is **role-aware**, not flat membership (`app/authz.py`):

- **Roles** (ranked): `viewer` < `editor` < `owner`. **Permissions**: `view`
  (read) < `edit` (mutate content) < `manage` (change settings). viewer→{view},
  editor→{view,edit}, owner→{view,edit,manage}. A member with no/unknown role is
  denied everything (**safe default**); legacy "member" maps to viewer.
- **Enforcement** (`can(scope, PERM_*)`): personal/account/session scope is full
  self-access (single-user stays simple). In **workspace** scope, the member's
  role (carried on `ResourceScope.role`, set by `resolve_scope`) drives real
  decisions: editing workspace preferences → **manage** (owner); uploading
  workspace documents, generating artifacts, and starting/approving guided flows
  → **edit** (editor+); reading/downloading → **view** (any member). The
  workspace creator is `owner`; `WorkspaceService.add_member` defaults new members
  to **viewer**. A stated-in-chat preference only rewrites a workspace default
  with manage rights. Denials are honest and state-preserving (a `403`, or a clean
  `workspace_forbidden` turn result) — never a fake success.
- **Operator boundary** (`/operator/*`, `app/routes/operator.py`): a
  service/operator principal is the configured `API_KEY` holder — **distinct from
  account/workspace users**. `GET /operator/overview` returns durable-resource
  counts (no PII/content) and requires the service key; a normal account token is
  rejected, and with no key configured the path is simply unavailable. This is the
  seam for future support/audit/policy tooling — no admin dashboard.

## Membership & workspace switching (minimal collaboration loop)

A small, real collaboration loop sits on the role model — no admin console:

- **Membership API** (`/workspaces/{id}/members`, `app/routes/workspaces.py`):
  `GET` list members (any member), `POST` add an existing account **by email** with
  a role (manage/owner only), `PATCH` change a role, `DELETE` remove (manage; or a
  member leaving themselves). Honest `404` when no account uses that email. Owner
  protections live in `WorkspaceService` — the **last owner can't be removed or
  demoted** (no self-lockout); new members default to **viewer**. Responses carry
  display fields only — never owner keys.
- **Scope switching** is real, not cosmetic: the frontend Settings page has a
  compact **Workspaces** card (a Personal / workspace scope selector + create +,
  for owners, a minimal members section). Selecting a workspace persists the
  active id (`lib/scope.ts`) and reloads so every scope-aware surface re-resolves;
  the `X-Workspace-Id` header then flows on chat, upload, and preferences. The
  backend honours it **only for members** (`resolve_scope`), so a stale or
  forbidden selection silently falls back to Personal — the switcher and backend
  never drift. Personal scope behaves exactly as before.

## Shared resources (recent artifacts, documents, runs)

A small, read-only discovery surface over resources that already exist and are
already owner-scoped — so workspace members can find shared outputs without deep
links, and a solo user sees their own recent items.

- **API** (`GET /resources/recent`, `app/routes/resources.py` →
  `app/shared_resources.py`): resolves the active scope (account-first; workspace
  header honoured only for members) and returns `{ scope, artifacts, documents,
  runs }`. Reading needs `view` (granted in every real scope), so a viewer can
  discover/download while a non-member silently falls back to Personal — never
  another team's data. Artifacts are read from the owner-token directory on disk;
  documents from the (now scope-tagged) `documents` table; runs from owner-tagged
  traces. Metadata is minimal and clean — title/type/size/time + the same opaque,
  access-controlled download URL — **never owner keys, raw rows, or trace dumps**.
- **Frontend**: a compact "Recent in {scope}" card in Settings (artifacts with a
  Download, documents, and a lightweight activity list) — calm and chat-first, not
  a file manager. It reflects the active scope and shows a clean empty state.
- **Migration**: `documents` gains a nullable `owner` column, applied by
  `ensure_runtime_columns()` (self-healing on existing SQLite DBs).

## Activity history (user-facing) vs operator logs

Two deliberately separate layers:

- **User-facing activity** (`activity_events` table, `app/activity.py`): a small,
  curated set of **meaningful product events** — `artifact_created/failed`,
  `document_uploaded`, `run_completed/failed`, `validation_passed/failed`,
  `startup_verified/failed`, `preference_updated`, `workspace_member_added`.
  Recorded best-effort at the action site (supervisor + upload/preferences/members
  routes), scope-owned, with the acting account as actor. `GET /activity/recent`
  resolves the active scope (account-first; workspace header honoured only for
  members), requires `view`, and returns UI-ready fields only — title, actor,
  type, status, severity, time — **never tool payloads, stack traces, trace dumps,
  or owner keys**. The Settings "Recent in {scope}" card shows a compact, calm
  activity list above the shared resources.
- **Operator diagnostics** stay where they were — `aira_x.supervisor` JSON ops
  logs (`_ops_log`) and the per-turn trace JSONL — never surfaced in the UI. The
  user activity log is the clean summary; operator/audit tooling reads the raw
  layers separately. This separation keeps future operator audit tools cheap
  without muddying the user surface.
- **Migration**: `activity_events` self-heals via `ActivityService._ensure_table`.

Invitation tokens/emails, join-accept flows, shared run continuation, richer
history/search/filtering, activity-driven notifications, and operator audit tools
all layer on this without changing the owner-key call sites.

## Run history & "pick up where we left off"

A thin, read-only composition (`app/run_history.py`, `RunHistoryService`) over
stores that are already owner-scoped — it adds **no new storage** and inherits the
access model for free. It surfaces three honestly-distinct kinds of run:

- **`resume`** — a genuinely pending guided flow (`artifact` / `plan`) awaiting
  approval, read via `guided_flow_store.list_pending` (peek, never consume).
  Resuming sends the exact approve phrase, so the supervisor's existing atomic
  `consume` claims it — real resume, idempotent (a duplicate approve resolves to
  "already handled").
- **`continue`** — a completed artifact on disk. "Continue" seeds a fresh,
  on-topic build from the prior output's context; it **never pretends the internal
  execution state still exists**, so it works regardless of ephemeral session
  memory. The item links to the same access-controlled artifact download.
- **`retry`** — a recent failure surfaced from `activity_events`, so a retry is
  one click away — never a raw error blob.

**APIs** (`app/routes/runs.py`): `GET /runs/recent` (list), `GET /runs/{id}` (one
clean summary), `POST /runs/{id}/continue` (prepare a continuation). All resolve
the active scope like a turn (account-first; workspace header honoured only for
members) and require `view`. Continuation re-checks that the run is accessible in
*this* scope — an inaccessible run is a plain `404`, so its existence never leaks.
Payloads are UI-ready only: `id`, `title`, `status`
(`requires_approval`/`completed`/`failed`), `kind`, `resumable`, `action`,
`summary`, optional `download_url`, `created_at` — **never workflow internals,
tool payloads, trace blobs, raw rows, or owner keys**.

**Chat-native, not a job console**: continuation returns the exact prompt the
client sends as a normal turn. The Settings "Continue your work" list (folded into
the same scope-aware card, replacing the old read-only runs strip — one coherent
surface, no duplicate history panels) calls `POST /runs/{id}/continue`, stashes the
prompt in `sessionStorage`, and lands the user in chat, where the composer is
**prefilled (never auto-sent)** so the user stays in control. No dashboards, no
state inspectors.

Richer history/search, bookmarking/pinning, activity-linked run detail, audit-safe
operator run views, and resumable collaborative workflows all layer on this
composition without touching the owner-key call sites.

## Scoped search & pinned work

Find the right prior work fast, and keep important items one click away — without
a file manager.

- **Search** (`app/search.py`, `GET /search?q=&type=`): a thin read-only
  composition that scans the active scope's **artifacts, documents, runs, and
  activity**, filters by a simple case-insensitive query, and returns one clean,
  newest-first result list. No new storage — it reuses the already owner-scoped
  readers (`recent_artifacts`, `recent_documents`, `run_history_service.recent`,
  `activity_service.recent`). Each result carries UI-ready fields plus a
  download/continue affordance and a **pin reference** where the resource supports
  one (activity is a feed, so it is searchable but not pinnable). `?type=` narrows
  the families (e.g. `type=artifact,run`). Never trace dumps, owner keys, DB rows,
  vector internals, or payload blobs.
- **Pins** (`app/pins.py`, `pinned_items` table; `GET/POST /pins`,
  `DELETE /pins/{id}`): a small durable scope-owned store of **references**
  (`ref_type` + `ref_id` + a clean display title) — never a copy of the underlying
  payload, so the artifact/run/document stays the source of truth. Pinning is
  idempotent per `(owner, ref_type, ref_id)`. On read, a pinned `artifact` is
  enriched with its access-controlled download URL and a pinned `run` with its
  live status + continue/resume affordance (a run no longer in recent history
  reads as `archived` — honest, not a dead link).
- **Permissions**: every route resolves the active scope like a turn (account-first;
  workspace header member-only). Reading (`/search`, `GET /pins`) needs `view`, so
  a non-member silently searches/sees only their own personal scope — never a
  team's work. Mutating pins (`POST`/`DELETE`) needs `edit`, so a workspace viewer
  can search and see shared pins but only editors/owners change them, while a
  personal user (full self-access) always can.
- **Frontend** (`frontend/lib/search.ts`, dependency-free): the Settings "Find &
  pinned work" card — a compact search box, a lightweight results list, and a
  "Pinned" section. Actions stay chat-connected: an artifact downloads, a run
  Continues/Resumes/Retries via the same prepared-prompt handoff as run history,
  a document opens as context. No giant search page, file browser, or dashboard.

Richer filters/ranking, saved collections, activity-linked search, and
cross-resource search all layer on this composition without changing the
owner-key call sites.

## Chat context handoff ("use this in chat")

Bring a prior document, artifact, or run back into the conversation explicitly —
no hidden context injection, no file blobs in the browser.

- **Model** (`app/chat_context.py`): a server-backed reference. `attach` resolves
  a `{ref_type, ref_id}` against the already owner-scoped readers (so it can never
  attach another scope's work), produces ONE clean context object, and parks it on
  the chat session (`session_memory`). The action stays semantically honest:
  document → `use_as_context`, artifact → `revise`, run →
  `resume`/`continue_from`/`retry` (delegated to run history, which already
  distinguishes a pending run from a completed/failed one). A pin resolves to one
  of these three. The object carries only a reference + action + a composer
  prefill — never file contents, owner keys, or internals.
- **Real reuse rides existing rails**: attaching an artifact seeds `last_artifact`
  so the next revise-style turn regenerates a richer version; attaching a run
  carries its continuation prompt; attaching a document grounds document-first.
  The supervisor **consumes** the attachment at turn start (`_consume_attached_
  context` in `_prime_memory`), emits an `attached_context` trace event, and
  clears it — single-use, never lingering. The user's typed message still leads.
- **APIs** (`app/routes/chat_context.py`): `POST /chat/context` (attach),
  `GET /chat/context` (what's attached, or null), `DELETE /chat/context` (detach).
  Reading/attaching needs `view` — it only parks a reference on the caller's own
  session — so a workspace viewer can reuse what they can already see, a
  non-member silently falls back to personal scope, and an inaccessible /
  cross-scope reference is a plain 404 (its existence never leaks).
- **Frontend** (`frontend/lib/chat-context.ts`, dependency-free): the Settings
  search/pins/runs surfaces now offer **Revise** (artifact), **Use in chat**
  (document), and **Resume/Continue/Retry** (run) — all routed through
  `attachContext`, landing the user in chat. The chat composer fetches the parked
  context on mount and shows ONE calm, removable **pill** ("Revising artifact:
  Roadmap Deck") above the input, prefilling an honest starter. The pill clears
  when the message is sent (the server consumes it) or when the user removes it.
  All five surfaces share one coherent action vocabulary.

Multi-item context packs, richer revision flows, and shared run handoff between
teammates all layer on this reference model without changing the call sites.

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
