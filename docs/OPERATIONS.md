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

## Multi-item context & handoff bundles

The single-item handoff above generalises to several attached items plus durable,
reusable bundles — still calm, explicit, and reference-only.

- **Multi-item attached context** (`app/chat_context.py`): the session now parks
  an ordered, **deduplicated list** of context items (cap 8) instead of one. Each
  keeps its honest action AND a short **role** (document → "source doc", artifact
  → "artifact to revise", run → "prior run"). `attach` appends one (deduped),
  `attach_many` adds several (returns `attached`/`skipped` counts), `remove` drops
  one, `clear` empties, `consume` returns the whole list and clears it. The
  supervisor consumes the list at turn start and emits one `attached_context`
  trace with the count + items — single-use, never lingering. `primary_prompt`
  picks the first actionable starter (a run/artifact); documents ground silently.
- **APIs**: `POST /chat/context` (one), `POST /chat/context/items` (many),
  `GET /chat/context` (→ `{items, prompt, context}` — `context` mirrors the first
  item for single-item callers), `DELETE /chat/context/item` (one),
  `DELETE /chat/context` (all). All `view`-gated; inaccessible refs never attach.
- **Bundles** (`app/bundles.py`, `context_bundles` table; `app/routes/bundles.py`):
  a small durable scope-owned store of **references only** (`items_json` =
  `[{ref_type, ref_id, title}]`, never payloads/prompts/urls). `POST /bundles`
  saves the currently attached items as a named pack; `GET /bundles` lists the
  active scope; `POST /bundles/{id}/load` **re-resolves** every reference against
  the *current* scope and attaches the accessible ones (inaccessible items are
  skipped, never smuggled in); `PATCH` renames; `DELETE` removes. Reading/loading
  needs `view` (a workspace viewer can reopen a shared pack; a non-member falls
  back to personal scope and a pack they can't see is a 404); creating / renaming
  / deleting needs `edit` (a personal user always can).
- **Frontend** (`frontend/lib/chat-context.ts`, dependency-free): the composer now
  shows a calm **ContextStack** — a "Using N items" header with per-item pills,
  remove-one, clear-all, and **Save as bundle** — and the Settings "Find & pinned
  work" card gains a **Handoff packs** subsection (Load / Delete). Loading a pack
  lands the user in chat with the items attached and an honest starter prefilled.
  The user's typed message still leads; the attachments only help.

Reusable context packs, teammate-to-teammate handoff, and richer multi-document
reuse all layer on this reference model without changing the owner-key call sites.

## Durable background execution (queue + worker)

Heavy/long-running work can run off the request path so it survives client
disconnect and process pressure — a staged, swappable foundation, not distributed
infra.

- **Queue/state** (`app/execution_queue.py`, `execution_jobs` table): a DB-backed
  `ExecutionJob` with lifecycle `queued → running → (validating/repairing) →
  completed|failed`, plus `awaiting_approval` and `cancel_requested/canceled`
  reserved. Scope-owned (`owner` = account/workspace/session). `enqueue` is
  **idempotent** via `dedup_key` (a duplicate approval can't double-queue);
  `claim()` flips exactly one row `queued→running` with a guarded `UPDATE` (SQLite
  serializes writers, so a job runs **once** even with multiple workers);
  `run_once()` executes a handler with **bounded retry** (`job_max_attempts`) then
  records an **honest `failed`** with a clean message. `payload_json` holds a
  reference spec, `result_json` a clean outcome (title/download/error) — never
  internals. The interface swaps for Redis/RQ/Arq/Celery later without touching
  call sites.
- **Worker** (`app/worker.py`): `python -m app.worker` — a thin loop calling
  `run_once()`; scale by running it more than once (the atomic claim keeps each
  job single-execution). The API never depends on the worker for inline paths.
- **Handlers** (`app/job_handlers.py`): `kind="artifact"` runs the **real**
  `ArtifactService.generate` (generation + validation unchanged, so evidence-based
  completion and artifact validation are preserved) and records the same activity
  the inline path does, so run history / recent artifacts stay coherent and
  scope-attributed.
- **Approval integration**: when `queue_artifacts` is on (default **off** —
  inline stays the tested default), an approved artifact is **enqueued** instead of
  generated inline. The pending guided flow is consumed first, so a duplicate
  approval still resolves to "already handled" — no double-execute. The turn
  returns a calm "working in the background" message with a `job_id`.
- **Status** (`app/routes/jobs.py`): `GET /jobs/{id}` (reconnect-safe), `GET /jobs`
  (recent, `?active=`), `POST /jobs/{id}/cancel`. Read = `view` (an inaccessible
  job is a 404, no leak); cancel = `edit`. Payloads are UI-ready only — never
  worker ids, queue internals, or owner keys.
- **Frontend** (`frontend/lib/jobs.ts`, dependency-free): a calm "Working in the
  background" line in the Settings "Recent" card when jobs are active (`?active`),
  with human status labels — no job dashboard, no worker ids, no polling console.
  Completed work surfaces through the existing activity / recent-artifacts
  surfaces.

Multiple workers, external queues, cancellation/retry UX, operator replay, and
workload prioritization all layer on this model without changing the call sites.

### Cancellation, retry & operator replay

Honest controllability on top of the queue (`app/execution_queue.py`):

- **Cooperative cancellation** — `request_cancel(owner, id)` is honest, not a
  force-kill. A **queued** job cancels outright (→ `canceled`); a **running** one
  is marked `cancel_requested` and stops at the worker's next **safe checkpoint**
  (the artifact handler checks `job.cancelled()` *before* the expensive generation
  and raises `JobCanceled`; `run_once` also re-checks *after* the handler and
  discards the result if a cancel arrived mid-run — so a cancel never reports fake
  completion and never delivers an orphaned artifact). An **already-terminal** job
  is told the truth ("already finished — nothing to cancel"). `transition` refuses
  to leave a terminal state, so a worker race can't resurrect a final status.
- **Honest retry** — `retry(owner, id)` works **only on a failed** job and
  schedules a **real new execution** (new id, `attempts` reset) linked to the
  original via `parent_job_id`/`origin="retry"`, so a retry is distinguishable
  from the original. Idempotent via `dedup_key="retry:{id}"` — a double click
  returns the in-flight retry, never a second run. Distinct from the **internal
  bounded repair retry** inside `run_once` (same job, `attempts++`, capped by
  `job_max_attempts`) and from operator replay.
- **Operator replay** — `replay(id)` re-runs **any** job (even completed) as a
  fresh attempt (`origin="replay"`), preserving the job's scope. Exposed **only**
  behind `POST /operator/jobs/{id}/replay` (service API key), never in the product
  UI — the clean seam for support/audit replay.
- **Activity** — a canceled job records `run_canceled`, a retry records
  `run_retrying` (scope-attributed), so history stays honest and calm.
- **Routes**: `POST /jobs/{id}/cancel` (honest `{ok, status, message}`),
  `POST /jobs/{id}/retry` (new job; `409` if not failed). Both `edit`-gated (a
  workspace viewer can't cancel/retry; a personal user always can); an
  inaccessible job is a `404`.
- **Frontend** (`frontend/lib/jobs.ts`): `canCancel`/`canRetry` gate the controls
  so they appear **only when honest** — a subtle Cancel on in-flight work and
  Retry on failed work in the Settings "Background work" line. No worker ids, no
  retry counters, no queue console.

### Scheduling policy: priority, concurrency classes & fairness

The queue is no longer plain FIFO (`app/job_policy.py`): each job `kind` maps to an
`ExecutionClass` with a **priority** and a **concurrency** bound, and `claim()`
uses them.

- **Classes**: `interactive` (priority 100, unbounded — light, user-visible work),
  `artifact` (50, cap 2 — heavy generation), `validation` (40, cap 1 —
  startup/runtime), `maintenance` (10, cap 1 — operator replay, isolated). Unknown
  kinds default to `interactive`; **operator replay is always `maintenance`** so a
  re-run never jumps ahead of users. Class + priority are stored on the job
  (`exec_class`/`priority`) but **never surfaced in the user payload**.
- **Priority-aware claim**: among eligible queued jobs, claim by `priority DESC`
  then `created_at ASC` (deterministic FIFO tie-break). The claim is still a single
  guarded `UPDATE`, so it stays race-safe (exactly one worker wins).
- **Concurrency shaping**: a class whose running count has reached its cap is
  **skipped** — so heavy artifact generation (cap 2) can't occupy every worker and
  starve lighter work.
- **Fairness**: a per-owner in-flight cap (`queue_per_owner_inflight_cap`, default
  3) skips an owner already running their share, so one user/workspace retrying a
  lot can't monopolise a class. This **complements** quotas (which still gate
  enqueue/approval) rather than replacing them.
- **Config** (operator-tunable, validated): `queue_scheduling_enabled` (off =
  plain FIFO), `queue_per_owner_inflight_cap` (≥ 1), and
  `queue_concurrency_<class>` (≥ 0; 0 = unbounded). Invalid values fail clearly at
  startup (pydantic validators) — no magic constants.
- **Coexistence**: cancel/retry/replay are unchanged under the scheduler; a
  canceled/terminal job frees its class slot; retries keep the original class,
  replay drops to maintenance. Nothing is exposed in the UI — the user just
  experiences the right work starting at the right time.

Multiple worker pools, per-class worker eligibility, external queues, per-class
autoscaling, and operator policy overrides all layer on this model without
changing call sites.

## Unified live status & reconnect-safe resumption

Inline turns stream SSE phases that live only while the request is open; queued
jobs are durable but carried only a freeform progress string. `app/live_status.py`
(`LiveStatusService`) is the seam that makes them feel like one product:

- **One phase vocabulary** — `job_phase(status, origin)` maps a durable job's
  lifecycle into the SAME curated, user-facing phases the streaming presenter uses
  (`Queued`, `Working in the background`, `Running validation`, `Repairing`,
  `Canceling`, `Completed`, `Could not complete`, and `Retrying` for a freshly
  re-queued retry). Labels match `frontend/lib/live-phase-presenter.ts` exactly, so
  inline and queued work read identically. **Never** worker ids, offsets, queue, or
  trace internals.
- **Reconnect-safe via snapshot** — the `ExecutionJob` row IS the durable snapshot,
  so no event backplane is needed: a reloaded client re-reads and resumes the right
  phase, and a finished job resolves to its honest **terminal** phase (never fake
  resumed progress). `RunLiveStatus` (`{id, kind, state, phase, status, result,
  …}`) is the conceptual channel both inline and queued work map into.
- **APIs** (`app/routes/jobs.py`): `GET /jobs/{id}` and `GET /jobs` now carry the
  unified `phase`; `GET /jobs/{id}/live` returns one reconnect snapshot;
  `GET /jobs/live` lists the active (non-terminal) work in scope to restore a live
  view. All `view`-gated and scope-inherited from the queue's own `get`/`recent` —
  an inaccessible job is a `404` (existence never leaks); a workspace member can
  resume shared live work, a non-member can't.
- **Frontend** (`frontend/lib/live-status.ts`, dependency-free): `jobLivePhase`
  bridges a queued job into the shared `LivePhase` shape (prefers the server phase,
  falls back by status); `liveBannerLabel`/`isResolved` drive a calm banner and
  terminal reconciliation. The Settings "Background work" line now renders the
  unified phase label + tone, so queued work reads exactly like inline phases. Fast
  inline chat turns stay ephemeral by design (no heavy durable machinery forced on
  them); the durable, reconnect-relevant work is the queued path.

Resumable event streams, multi-device live continuity, and richer live run detail
all layer on this snapshot model without changing call sites.

## Operator inspection (support-safe observability)

The data to diagnose a run lives in four disconnected places — the
`execution_jobs` table, the per-turn trace JSONL, `activity_events`, and the
retry/replay lineage in job columns. `app/operator_inspect.py`
(`SupportInspectionService`) correlates them into ONE curated, **operator-only**
inspection model so support stops meaning raw DB spelunking. It is gated by the
service api-key (operator principal) exactly like replay, and is **strictly
separate** from the user-facing activity layer (which stays the minimal summary).

- **`OperatorJobView`** (`GET /operator/jobs/{id}`): job id, kind, status, unified
  phase, queue internals (exec_class/priority/dedup_key — fine for operators,
  never for users), scope context (account/workspace/session — derived, not the
  raw owner key), actor display name, timestamps, **lineage**
  (`origin`/`parent_job_id`/`retried_into`/`replayed_into`), a **summarized
  failure class** (e.g. `RuntimeError` — never the full message or a stack trace),
  and a **safe artifact reference**. Approval is reported honestly (a queued
  artifact's approval is consumed before enqueue).
- **`OperatorTimeline`** (`GET /operator/jobs/{id}/timeline`,
  `/operator/runs/{id}/timeline`): a curated, ordered "what happened" —
  queued → claimed → terminal, correlated activity (artifact/validation/startup/
  run events), and lineage markers (`Retried into X` / `Replayed from Y`) — never a
  raw log concatenation.
- **`OperatorRunView`** (`GET /operator/runs/{id}`): the inline/trace world — a
  friendly run label, status, source, and curated **stage names** from the trace
  (no raw event payloads or blobs).
- **Locator** (`GET /operator/jobs?status=&origin=&kind=&failures=`): a minimal
  query to find the right job (recent failures, retry/replay origin) — not an admin
  search console.
- **Curation rules**: payloads exclude `payload_json`, raw `result_json`, full
  error messages, and `trace_events`. **Separation is enforced**: the user-facing
  `GET /jobs/{id}` gains **no** operator fields (scope/owner/actor/lineage/queue
  internals) — verified by test. All endpoints `403`/`401` without the service key
  and `404` on a missing id. No frontend surface — this is a backend/operator API.

Operator replay tools, dead-letter inspection, failure triage, audit-safe support
tooling, and richer correlation search all layer on this curated model without
touching the user surface.

## Observability export & failure triage

`app/observability.py` (`ObservabilityExportService`, `observability_events` table)
is the operator-only ops stream — distinct from user `activity_events` (the calm
product summary) and from raw traces (per-turn debug JSONL).

- **Export feed** (`GET /operator/observability?since=&type=&limit=`): a durable,
  append-only journal of curated job lifecycle signals — `job_queued`,
  `job_claimed`, `job_completed`, `job_failed`, `job_canceled`, `job_retrying`,
  `job_replayed` — emitted **best-effort** from the queue's real lifecycle tap
  points (enqueue / claim / run_once terminal / cancel / retry-replay clone), so
  emission **never breaks execution**. The row id is a **monotonic cursor**: an
  external dashboard/alerting backend polls `?since=<cursor>` for incremental
  export and the response carries the next `cursor`. Each event carries only safe,
  ops-useful fields (type, ts, job/run ids, origin, **scope type + id** derived
  from the owner — never the raw key, status, **summarized failure class**,
  lineage `parent_job_id`) — never prompts, tool payloads, trace blobs, or secrets.
- **Triage** (`GET /operator/triage`): the dead-letter / failure-triage foundation
  — terminal-`failed` jobs classified **honestly** from their lineage:
  `retry_exhausted` (attempts reached `job_max_attempts`), `replay_candidate` (no
  active/resolved follow-up — safe to replay), `in_progress` (a retry/replay is in
  flight), or `resolved` (a retry/replay already succeeded). Includes
  `retried_into`/`replayed_into` ids and the failure class.
- **Gating & separation**: both endpoints are service-key gated (operator
  principal) — `401`/`403` without it. The signals do **not** flow into the user
  activity feed (verified), there is **no** user-facing `/observability` route, and
  the user `GET /jobs/{id}` is unchanged. No frontend surface.

External dashboards, alerting/webhook hooks, dead-letter queues, and richer triage
workflows all layer on this curated, cursor-based stream without changing the user
surface or the queue's execution path.

## Operational policy: SLOs, stuck detection & alerts

`app/ops_policy.py` (`OperationalPolicyService`, `SLOPolicy`) is the *policy* on top
of the observability signals: it turns durable job state + timestamps into a small,
production-sensible set of health classifications — so "needs attention" is
policy-driven, not ad-hoc heuristics scattered across the code.

- **Classifications** (each with severity `info`/`warning`/`critical` and a human
  reason): `healthy`, `stuck`, `retry_exhausted`, `triage_needed`, `resolved`,
  `backlog_pressure`.
- **Stuck-job detection** uses **durable timestamps** (never in-memory timers): a
  `queued` job older than `slo_queued_seconds`, a running job past its
  **class-aware** budget (`slo_running_seconds_<class>` — generation gets a longer
  budget than light work), or a `cancel_requested` job that hasn't reached
  `canceled` within `slo_cancel_seconds`. "Slow but valid" stays healthy until it
  crosses a clear threshold.
- **Lineage/resolution honoured**: a failed job whose retry/replay **completed** is
  `resolved` (not alerted); one with a follow-up **in flight** is `triage_needed`
  (info); only a retry-exhausted failure with no follow-up is `critical`. A stuck
  job that later completes is simply no longer active. A clean `canceled` is
  `healthy`, distinct from a stuck cancellation.
- **Backlog pressure**: a class with more `queued` jobs than `slo_backlog_threshold`
  is flagged (`critical` past 2×).
- **APIs** (operator-only): `GET /operator/health` (bounded snapshot —
  per-job classifications for recent active + terminal-failed work, per-class
  backlog, summary counts) and `GET /operator/alerts` (alert-ready: only
  warning/critical — stuck, retry-exhausted, backlog — critical-first). Both
  service-key gated.
- **Config** (operator-tunable, validated): `slo_enabled`, `slo_queued_seconds`,
  `slo_running_seconds_{default,artifact,validation,maintenance}`,
  `slo_cancel_seconds`, `slo_backlog_threshold`. Invalid values fail clearly at
  startup (pydantic validators). `SLOPolicy` is injectable, so thresholds are
  swappable and testable.
- **Separation**: policy results never reach the user activity feed; there are **no**
  user-facing `/health`/`/alerts` routes; `GET /jobs/{id}` is unchanged (no
  classification/severity fields). No frontend surface.

Real alert routing/webhooks, SLO dashboards, incident workflows, dead-letter
queues, and auto-remediation hooks all layer on this policy model without touching
the user surface or the execution path.

## External delivery: webhooks & alert routing

`app/webhooks.py` (`DeliveryService`, tables `webhook_destinations` +
`webhook_deliveries`) *delivers* the curated observability events and alert-worthy
policy results to external systems instead of forcing them to poll. Operator-only.

- **Destinations** (`POST/GET/PATCH/DELETE /operator/destinations`): an operator
  configures a webhook target — `url`, `subscription` (`events` / `alerts` /
  `both`), `min_severity` (for alerts), an optional `event_filter`, and a signing
  `secret`. The **secret is stored but NEVER returned** (reads expose only
  `has_secret`). Disabled destinations receive nothing.
- **Routing**: `observability.record()` fans each curated event out (best-effort,
  own session, guarded) to enabled `events`/`both` destinations; the alert sweep
  routes `ops_policy.alerts()` to `alerts`/`both` destinations filtered by
  `min_severity`. **Deliveries are NOT execution jobs** — routing them through the
  queue would re-emit observability events and loop — so a failing webhook can
  **never break a job**. Alert routing is **idempotent** via a `dedup_key`, so a
  stuck job doesn't deliver on every sweep.
- **Durable, bounded delivery** (`deliver_pending`, run by the worker when idle, or
  via `POST /operator/deliveries/sweep`): a `WebhookDelivery` runs
  `pending → delivered | failed`; a non-2xx/exception increments `attempts` and
  re-queues until `webhook_max_attempts` (a **delivery** retry counter, distinct
  from job retry/replay), then marks the delivery **terminally failed**
  (dead-letter-ready). Payloads are signed `HMAC-SHA256` in `X-AIRA-Signature`.
- **Inspection** (`GET /operator/deliveries?status=&destination_id=`,
  `GET /operator/deliveries/{id}`): status, attempts, response code, and the **error
  class** (never a body/secret). `?status=failed` is the dead-letter view; the
  delivered payload preserves correlation (`source_type`/`source_id`/`event_type`/
  severity). The payload is the already-curated event/alert — never prompts, tool
  payloads, traces, or secrets.
- **Config** (validated): `webhooks_enabled`, `webhook_max_attempts` (≥ 1),
  `webhook_timeout_seconds`. **Separation**: no user-facing destination/delivery
  routes, `GET /jobs/{id}` unchanged, nothing in the user activity feed. The HTTP
  send is injectable, so it's fully testable without a network. No frontend.

### Redrive, dead-letters & destination adapters

On top of the delivery foundation (`app/webhooks.py`):

- **Adapter abstraction** — a destination has a `kind`, and an **adapter** owns only
  payload *shaping* + which `(url, secret)` to use; the HTTP transport stays the
  single injectable `_send`, so the delivery state machine / retry / redrive are
  adapter-agnostic. `webhook` (generic signed POST) is the full adapter; a minimal
  `slack` adapter reshapes the curated payload into Slack's `{"text": …}` shape
  (proves the seam — PagerDuty/email/queue adapters are a one-class addition).
  `deliver_pending` dispatches via `adapter_for(dest.kind)`; an unknown kind falls
  back to `webhook` safely.
- **Operator redrive** (`POST /operator/deliveries/{id}/redrive`): recover a
  **terminal-failed** delivery without DB surgery. Redrive schedules a **real new
  attempt** — a fresh `pending` row linked via `redrive_of`, preserving source +
  destination correlation. It is **bounded** by `webhook_max_redrives` and
  **idempotent** (a redrive already in flight is returned, never duplicated), and
  is deliberately **distinct** from auto delivery-retry, job retry, and job replay.
  Only a `failed` delivery is redrivable (else `409`).
- **Dead-letters** (`GET /operator/deliveries/dead-letters`): terminal-failed
  *original* deliveries (not themselves redrives), each classified from lineage —
  `redrive_candidate` / `redriven` (in flight) / `resolved` (a redrive succeeded) /
  `exhausted` (redrive cap reached) — with `redrive_count` + child ids. The clean
  dead-letter view; `GET /operator/deliveries` now carries `redrive_of`/`is_redrive`.
- **Config** (validated): `webhook_max_redrives` (≥ 1) — a third bound, separate
  from `webhook_max_attempts` (auto-retry) and `job_max_attempts` (execution).
  Self-healing migration adds `webhook_deliveries.redrive_of`.
- **Separation/contract**: redrive/dead-letter routes are operator-only; secrets
  still never returned; payloads stay the curated F-8 contract; no user-facing
  routes, `GET /jobs/{id}` unchanged. No frontend.

### Routing policy & noise-safe suppression

On top of delivery (`app/webhooks.py`), routing stops being a blunt fan-out:

- **Per-destination filters** (enforced, not just stored): `event_filter` (allowed
  observability event types) and `origin_filter` (allowed event origins —
  `normal`/`retry`/`replay`) for events; **`alert_filter`** (allowed alert
  classifications — `stuck`/`retry_exhausted`/`backlog_pressure`/…) plus the
  existing `min_severity` for alerts. A destination receives only the classes it
  asked for.
- **Bounded suppression** (the noise fix): the alert dedup is now a **time window**.
  A persistent stuck job no longer re-delivers the same critical alert every sweep
  — within `suppress_seconds` (per-destination, or the global
  `webhook_suppress_seconds`, default 300; 0 = off), an identical
  `(classification, subject, severity)` signal is **suppressed**. A **severity
  change** (escalation/recovery) is never suppressed, and after the window a
  recurring alert routes again. Suppression creates **no delivery record** — it
  never masquerades as delivered.
- **Explainable** — `alert_routing_decision(...)` is a pure helper returning
  `route` / `skip:<reason>` / `suppress:within_window`. `route_alerts_detailed`
  returns `{routed, suppressed, skipped}` (surfaced by the sweep), and
  `GET /operator/destinations/{id}/routing` dry-runs the current alert set against
  one destination — per alert, *would it route/suppress/skip and why* — so an
  operator can answer "why didn't this destination get that alert" without DB
  spelunking.
- **Adapter policy used intentionally** — each adapter declares a `payload_shape`
  (`structured_json` for webhook, `slack_text` for slack), surfaced on the
  destination so routing/inspection knows the form a destination expects. The
  curated payload contract is unchanged; the adapter adapts *presentation*.
- **Compatible with F-8/F-9** — suppression/filters never create fake deliveries,
  routed alerts still make real durable attempts, redrive preserves
  destination/routing identity, and dead-letter lineage is intact. Config
  `webhook_suppress_seconds` (≥ 0) validated. Operator-only; secrets still never
  returned; no user routes; `GET /jobs/{id}` unchanged. No frontend.

### Multi-destination escalation & delivery analytics

On top of routing (`app/webhooks.py`):

- **Escalation by persistence** — a destination with `escalate_after = N` is an
  **escalation target** that fires only once a matching condition has been detected
  **N times** (a primary has `escalate_after = None` and fires on the first
  occurrence). Occurrences are tracked durably per signal (`alert_occurrences`
  table), **episodically**: a gap longer than `webhook_escalation_resolve_seconds`
  (default 1800) is a resolved episode and the count resets — so escalation
  reflects a *currently-persisting* problem, not stale history. So "a critical
  `retry_exhausted` that persists 3 sweeps also pages PagerDuty" is real, bounded
  by an occurrence count (never an uncontrolled fan-out), and **suppression-safe**
  (the escalation target's own suppression window still applies). The decision is
  the same pure `alert_routing_decision` (+ `skip:below_escalation_threshold`), and
  `routing_preview` shows the live occurrence count + decision per alert.
- **Delivery analytics** (`GET /operator/delivery/analytics?since_minutes=`):
  attempted / delivered / failed / pending / redriven totals, durable **routing
  counters** (routed / suppressed / skipped + escalation-destination count —
  suppressed alerts create no delivery, so these come from per-destination
  `stat_*` counters), and breakdowns **by adapter kind** and **by destination**.
- **Destination health** (`GET /operator/delivery/health`): per destination —
  delivered / failed_terminal / pending / redrive_resolved, the routing counters,
  the last error **class**, and a calm health label (`healthy` / `degraded` /
  `failing` / `disabled`). No secrets, no payloads.
- **Compatible with F-8/F-9/F-10** — escalated deliveries are **real separate
  attempts** with intact source correlation and redrive/dead-letter lineage;
  escalation never blurs with auto-retry or redrive; analytics are derived from
  durable state and never distort delivery truth. New `WebhookDestination` columns
  `escalate_after` + `stat_routed`/`stat_suppressed`/`stat_skipped` (self-healing
  migration); `webhook_escalation_resolve_seconds` (≥ 0) validated. Operator-only;
  secrets still never returned; no user routes; `GET /jobs/{id}` unchanged. No frontend.

Multi-stage escalation chains, adapter-specific escalation policies, delivery
dashboards, SLO-driven routing, and alert acknowledgement/silencing all layer on
this without touching the user surface or the execution path.

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
