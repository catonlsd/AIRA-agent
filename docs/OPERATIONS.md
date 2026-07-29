# AIRA-X Operations Guide

The day-to-day reference for running, validating, and observing AIRA-X.
Deployment targets (Render/Railway/VPS/Docker) live in [DEPLOYMENT.md](DEPLOYMENT.md).

> **New here?** Start with the **[root README](../README.md)** for the platform overview,
> then **[ARCHITECTURE.md](ARCHITECTURE.md)** for the flows and **[DEMO_WALKTHROUGH.md](DEMO_WALKTHROUGH.md)**
> for a 7-minute hands-on evaluation. The reasoning behind the design is in
> **[ENGINEERING_DECISIONS.md](ENGINEERING_DECISIONS.md)**; resume-ready metrics in
> **[PLATFORM_SUMMARY.md](PLATFORM_SUMMARY.md)**. This guide is the deep operational
> reference once you're running it.
>
> **Portfolio visuals (Milestone C):** the README's screenshot slots are stable paths
> backed by a foolproof, deterministic shooting script in
> **[screenshots/CAPTURE_PLAN.md](screenshots/CAPTURE_PLAN.md)** (8 shots on the demo
> seed, ~10 min, with a pre-commit safety checklist and the exact README embed block).
> The honest presentation gaps are tracked in **[PORTFOLIO_AUDIT.md](PORTFOLIO_AUDIT.md)**.

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

## CI (GitHub Actions — three focused, parallel workflows)

Replaces the former monolithic `ci.yml` with three deterministic workflows so feedback is
fast and each status check is meaningful:

- **`fast-check.yml`** (every push + PRs to `main`) — two parallel jobs:
  - **Backend**: Python 3.12 (pip cached) → full pytest suite, deterministic
    (`-p no:randomly`), hermetic (no API keys; `EMBEDDING_PROVIDER=hashing`). Single
    process — the test DB is shared SQLite, so suites never run concurrently. This is the
    regression wall (routed modes, approval/resume, incident-sync lifecycle, observability
    math, operator gating).
  - **Frontend**: Node 22 (npm cached) → `tsc --noEmit` → `node --test "lib/**/*.test.mts"`
    → `eslint` → production build.
- **`e2e.yml`** (PRs to `main` + manual dispatch) — installs Chromium and runs the hermetic
  Playwright suite (`CI=1`: retries + HTML report; report uploaded on failure). Kept off
  every push to save browser minutes.
- **`docs.yml`** (every push + PRs) — a fast, distinct gate running the packaging +
  professionalization tests (`tests/test_docs_packaging.py`,
  `tests/test_repo_professionalization.py`): the docs, OSS governance, CI, and release
  files must exist, cover required sections, and (for docs) keep counts in sync with the
  live registry.

Any test regression, type error, lint error, build failure, or doc/packaging drift fails
the relevant run.

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

### Adapter-specific retry, destination health/SLOs & cooldown

The delivery layer (`app/webhooks.py`) stops being one-size-fits-all:

- **Adapter-specific retry budget** — `effective_max_attempts(kind, dest_max)`:
  a destination's own `max_attempts` override, else the **adapter** default, else
  the global `webhook_max_attempts`. So `slack` retries tighter (2) than `webhook`,
  and `deliver_pending` honours the per-destination budget instead of one global
  cap. Each adapter also declares a `backoff` class. (This is the DELIVERY retry
  budget — still distinct from job retry, replay, and operator redrive.)
- **Health classification** — `destination_health_one`/`destination_health` label a
  destination `healthy` / `degraded` / `failing` / `cooling_down` / `disabled` with
  a concise **reason**, recent delivered/failed/pending counts, the durable routing
  counters, and **escalation eligibility** (an escalation target that's
  cooling/failing/disabled is `escalation_eligible: false`).
- **Bounded cooldown** — a terminal delivery failure bumps `consecutive_failures`;
  crossing `webhook_cooldown_threshold` (default 5) puts the destination in
  `cooldown_until = now + webhook_cooldown_seconds` (default 600). While cooling,
  **routing skips it honestly** (counted as `skipped`, **never** a fake delivered),
  so an unhealthy endpoint stops thrashing — and a failing escalation target stops
  receiving. It is **bounded + recoverable**: the cooldown auto-expires, a single
  successful delivery (e.g. a redrive) clears the streak + cooldown, and
  `POST /operator/destinations/{id}/cooldown/clear` is an explicit recovery. A
  cooling destination's **existing pending deliveries still attempt** (cooldown
  gates new routing only), so redrive recovers honestly.
- **APIs** (operator-only): `GET /operator/destinations/{id}/health` (health/SLO
  view), `GET /operator/destinations/{id}/policy` (effective retry budget +
  provenance + backoff + cooldown config/state), `POST
  /operator/destinations/{id}/cooldown/clear`, and `max_attempts` on
  create/`PATCH`. `GET /operator/delivery/health` now carries the cooldown +
  escalation-eligibility fields.
- **Config** (validated): `webhook_cooldown_threshold` (≥ 1), `webhook_cooldown_seconds`
  (≥ 0). New `WebhookDestination` columns `max_attempts`/`consecutive_failures`/
  `cooldown_until` (self-healing migration). Compatible with F-8→F-11: cooldown
  skips never masquerade as delivered, redrive/dead-letter lineage is intact,
  analytics stay honest. Operator-only; secrets still never returned; no user
  routes; `GET /jobs/{id}` unchanged. No frontend.

Adapter-specific backoff timing, delivery SLO dashboards, escalation fallback
chains, and destination silencing/acknowledgement all layer on this without
touching the user surface or the execution path.

### Operator delivery console (G-1)

A minimal **operator-only** delivery console at `/operator`
(`frontend/app/operator/page.tsx`, client `frontend/lib/operator.ts`) — the first
admin surface, so operators stop chaining raw `curl` against `/operator/*`.

- **Strictly separate**: `AppShell` renders `/operator` **without** the product nav
  (it is never linked from the user UI). The operator enters the **service key**,
  kept in `sessionStorage` (a secret — never `localStorage`, never mixed with a
  user's account token), sent as `X-API-Key` on every call. With no `api_key`
  configured (the normal product deployment) the whole surface is simply 403 for
  everyone; with it, only the key holder gets in — verified against
  `GET /operator/overview` on connect.
- **Backed only by real, already-gated APIs** (no new backend): a **delivery
  summary** (`/operator/delivery/analytics`), **destination health**
  (`/operator/delivery/health` — label + reason, cooldown state, escalation
  eligibility, routed/suppressed/skipped counts) with **routing explainability**
  (`/operator/destinations/{id}/routing` — per-alert route/suppress/skip + reason)
  and **cooldown recovery** (`/operator/destinations/{id}/cooldown/clear`), and a
  **dead-letter recovery** list (`/operator/deliveries/dead-letters`) with one-click
  **redrive** (`/operator/deliveries/{id}/redrive`) gated to `redrive_candidate`
  (others show why not). A **Sweep** button runs `/operator/deliveries/sweep`.
- **Operator-safe**: secrets are never shown (only `has_secret`); payloads are the
  curated operator contract (error *class*, not bodies/traces). Pinned by
  `tests/test_operator_console.py` — every console endpoint is operator-only,
  account tokens are denied, payloads carry no `secret`, and **no** operator field
  (`health`/`reason`/`escalation_eligible`/`dead_letter_state`/…) leaks into user
  routes like `GET /jobs/{id}`. Pure UI logic (`healthTone`/`deadLetter*`/
  `canRedrive`) is unit-tested in `frontend/lib/operator.test.mts`.

Richer operator dashboards, destination-tuning UIs, redrive history, and SLO
dashboards all layer on this console + client without touching the user product.

### Operator console — history, tuning & lineage (G-2)

The console grows from a single panel into **three focused tabs** (still one page,
no admin maze) — **Overview**, **History**, **Recovery**:

- **Delivery history** (`GET /operator/deliveries?status=&destination_id=&redrives=`):
  recent attempts with quick filters (all / failed / pending / delivered, by
  destination) — `recent_deliveries` now carries the **destination name** and a
  `redrives` filter (original-vs-redrive). Each row drills into its **redrive
  lineage**.
- **Redrive lineage** (new `delivery_lineage(id)` + `GET /operator/deliveries/{id}/
  lineage`): the **original attempt plus every redrive, in order**, each curated
  (status / attempts / error class / time). Resolving lineage from a child id
  returns the same root chain — operators see *what happened over time*, not just
  the current dead-letter state. Surfaced in both History and Recovery.
- **In-console destination tuning** (`PATCH /operator/destinations/{id}`): an
  inline form edits `enabled` / `min_severity` / `alert_filter` / `suppress_seconds`
  / `escalate_after` / `max_attempts` (only changed fields are sent; backend
  validation preserved). **Secrets are never editable or shown** (only `has_secret`).
- Still operator-gated and separate: pinned by `tests/test_operator_console.py`
  (history filterable + named + no payload/secret; lineage chains original+redrive
  and 404s/gates correctly; tuning via PATCH validates + never returns the secret +
  account tokens denied; no operator field leaks into `GET /jobs/{id}`). Pure UI
  logic (`deliveryStatusTone`, …) in `frontend/lib/operator.test.mts`. No backend
  delivery logic changed beyond the additive lineage/name/`redrives` helpers.

Redrive-history timelines, destination-tuning presets, and incident workflows all
layer on this without touching the user product.

### Incident workflow — acknowledge, silence & honest recovery (G-3)

Repeated operational conditions (a stuck-job alert, a retry-exhausted delivery
class, a degrading destination) now get a **durable operator-incident identity**
instead of re-firing as anonymous noise. The console gains a fourth tab —
**Incidents** — and a small, focused workflow on top of the existing alert
pipeline. This is a support workflow, **not** a ticketing/pager product.

- **Durable identity = the alert signal.** An `OperatorIncident`
  (`backend/app/db/models.py`, table `operator_incidents`) is keyed by the alert
  **signal** (`f"{classification}:{job_id or exec_class}"`), the same identity the
  routing/suppression layer already uses. `IncidentWorkflowService`
  (`backend/app/incidents.py`) `observe()`s the live alert set on every console
  read and sweep: a new condition **opens**, a recurring one **bumps occurrences**
  (no duplicates), and a recovered/silence-expired one **reopens as a fresh
  episode** (clearing ack/note/silence).
- **States are distinct and honest:** `open` → `acknowledged` (being worked, still
  active) → `silenced` (muted for a **bounded** window) → `recovered` (condition
  cleared). `recover_stale(active_signals)` flips any incident whose signal is no
  longer active to **recovered** with a timestamp — a cleared, redriven, or
  re-healthy condition surfaces as recovered rather than vanishing.
- **Silence is bounded and never a black hole.** `silence(id, seconds)` clamps to
  `incident_max_silence_seconds` (default cap 24h; default window 1h) and is the
  **only** new coupling into routing: `route_alerts_detailed` skips signals in
  `incident_service.silenced_signals()` and counts them as `silenced` (a *distinct*
  skip reason). A silenced incident **still exists** in operator state and history;
  on expiry it stops muting and reopens on the next recurrence. Silence (per-signal,
  operator-driven) stays cleanly separate from **delivery suppression**
  (per-destination/signal/window), **destination cooldown** (per-destination
  health), and **dead-letter** (terminal delivery failure).
- **Operator-only APIs** (`backend/app/routes/operator.py`, all service-key gated):
  `GET /operator/incidents`, `GET /operator/incidents/{id}`,
  `POST .../{id}/ack`, `POST .../{id}/silence` (bounded), `POST .../{id}/unsilence`,
  `PATCH /operator/incidents/{id}` (≤280-char note). Payloads are curated — no raw
  payloads/traces/secrets.
- **Console tab** groups incidents into **Unresolved / Acknowledged / Silenced
  (with time-left) / Recovered**, each with one-click **Acknowledge / Silence /
  Unsilence**, the source/severity/occurrence summary, the operator note, and an
  open-count badge. The normal product UI is untouched: no incident fields leak
  into `GET /jobs/{id}` and there is no user-facing `/incidents` route.
- Pinned by `backend/tests/test_operator_incidents.py` (open→ack, occurrence
  bumping, bounded silence muting routing while still existing, honest
  silence-expiry reopen, unsilence preserving ack, recovery + fresh-episode
  recurrence, silence ≠ suppression, HTTP gating/actions, config bounds, no
  user-route leak) and `frontend/lib/operator.test.mts` (`incidentTone`).

### Incident collaboration — assignment, notes & action trail (G-4)

Incidents become **handoff-safe** so a relieving operator can pick up a shift
without out-of-band Slack archaeology. Still a support workflow, **not** a
ticketing product — one owner, one short note, one curated trail.

- **Operator identity, honestly.** Service-key auth has no verified named
  operators, so an operator optionally **self-declares a handle** at connect time
  (stored in `sessionStorage`, sent as the `X-Operator-Name` header). It is
  recorded as the `actor` on actions — never presented as a verified account.
- **Single ownership.** `OperatorIncident` gains `assignee` / `assigned_at`
  (additive `ensure_runtime_columns` ALTER). `assign(id, handle)` takes/transfers
  ownership (re-assigning to a *different* handle records a `reassigned` event),
  `unassign(id)` releases it. Ownership **survives reopen** — when a recovered
  condition recurs, the owner still owns the fresh episode.
- **Durable notes.** The existing `PATCH /operator/incidents/{id}` note (≤280)
  now records a `note_updated` trail entry; the console edits it inline.
- **Curated action trail.** New `OperatorIncidentEvent`
  (`backend/app/db/models.py`, table `operator_incident_events`, monotonic int PK
  for stable chronological order) appends **one row per meaningful transition**:
  opened / acknowledged / silenced / unsilenced / recovered / reopened / assigned
  / unassigned / reassigned / note_updated. `observe()` logs `opened`/`reopened`,
  `recover_stale()` logs `recovered` (occurrence bumps do **not** flood the trail).
  Each entry carries only `{action, actor, detail, state, at}` — never payloads,
  traces, secrets, or raw owners.
- **Operator-only APIs** (`backend/app/routes/operator.py`): `POST
  .../{id}/assign` (`assignee` validated non-empty ≤80 → 422 otherwise), `POST
  .../{id}/unassign`, `GET .../{id}/history`. Assignee/note actions thread the
  declared operator name as actor.
- **Console** (`app/operator/page.tsx`): each incident row shows the **owner**, a
  **Claim** (assign-to-me, gated on a declared handle) / **Release** control, an
  inline **note** editor, and an expandable **action trail** (lazy-loaded), with
  ack/silence/unsilence unchanged. The connect screen adds an optional operator
  name; the header shows "acting as …". Still strictly operator-gated — no
  assignee/note/history field leaks into `GET /jobs/{id}` and there is no
  user-facing route.
- Pinned by `backend/tests/test_operator_incidents.py` (assign/reassign/unassign
  durable + trail order, ownership survives reopen, curated ordered history with
  actor/detail, HTTP collab actions with `X-Operator-Name`, empty-assignee 422,
  collab gating + 404, no `assignee` leak into `/jobs/{id}`) and
  `frontend/lib/operator.test.mts` (`incidentEventLabel`).

### External incident sync — outbound export to incident tools (G-5)

Incidents can now **mirror outward** to an external incident/ticket tool instead of
being copy-pasted by hand. Deliberately **one-way (outbound from AIRA-X)** and
honest about it — no inbound/bidirectional pretence — and kept **distinct from
webhook event/alert routing** (`app/webhooks.py` fans job-lifecycle events; this
mirrors *incident workflow transitions*). A small, durable foundation, not a
ticketing product.

- **Targets** (`app/incident_sync.py`, table `external_incident_targets`): operator
  config for an outbound destination — `name`, `url`, `kind` (generic / pagerduty /
  jira / opsgenie, adapter-ready), optional `sync_actions` CSV allow-list (which
  transitions to mirror; empty = all), and a `secret` **stored for HMAC signing but
  never returned** (reads show only `has_secret`).
- **Records** (table `incident_sync_records`): one durable row per (transition,
  target), **correlated to the source incident** (`incident_id` / `signal`) and
  **snapshotting curated fields** at sync time — state, severity, classification,
  subject, assignee, short note — never raw payloads/traces/secrets/owners. Status
  runs `pending → synced | failed`.
- **The hook.** `IncidentWorkflowService` mirrors every committed transition via a
  guarded `_emit_sync` → `incident_sync_service.export(snapshot, action, actor)`:
  `observe()` emits opened/reopened, `recover_stale()` emits recovered, and each
  operator action (ack/silence/unsilence/assign/unassign/reassign/note_updated)
  emits after commit. Best-effort and a **no-op when no targets exist** — external
  sync can never break the incident workflow.
- **Bounded & recoverable.** Each record attempts once on creation; a failed send is
  **terminal `failed` once `attempts` reaches `incident_sync_max_attempts`**
  (default 4), else stays `pending` for the sweep's `flush_pending()` retry. A
  terminal-failed record is **operator-redrivable** (`redrive()` → fresh linked
  record, bounded by `incident_sync_max_redrives`, idempotent), mirroring the
  delivery dead-letter pattern. The HTTP send is the single injectable `_send`
  (HMAC `X-AIRA-Signature`), so the state machine is network-free in tests.
- **Operator-only APIs** (`app/routes/operator.py`): `GET/POST
  /operator/incident-targets`, `PATCH/DELETE /operator/incident-targets/{id}`,
  `GET /operator/incident-sync?status=&incident_id=`, `GET
  /operator/incident-sync/{id}`, `POST /operator/incident-sync/{id}/redrive`.
- **Console** (`app/operator/page.tsx`): a calm **External sync** card at the top of
  the Incidents tab shows configured targets (name/kind/enabled, failure counter)
  and recent sync attempts (status badge, action, target, error, time) with a
  **Redrive** button on failed ones — surfacing "was it synced? to where? did it
  fail? is it behind?" without a payload dump. Still operator-only: no
  target/record fields leak into `GET /jobs/{id}` and there is no user-facing
  `/incident-sync` or `/incident-targets` route.
- Pinned by `backend/tests/test_incident_sync.py` (target CRUD + secret hidden,
  invalid target/config rejected, opened/ack/assign/note transitions exported with
  curated correlated payloads, `sync_actions` allow-list filtering, disabled target
  skipped, bounded-retry terminal failure + redrive recovery, HTTP gating + 404, no
  sync field leak into `/jobs/{id}`) and `frontend/lib/operator.test.mts`
  (`syncStatusTone`).

### Incident adapters, external linking & sync-health (G-6)

Outbound sync grows from "one generic target shape" into a small **adapter +
external-link** layer — still strictly **outbound-only** (AIRA-X never reads
external state back; no bidirectional pretence).

- **Adapter registry** (`app/incident_sync.py`): an adapter per target `kind`
  keeps one curated contract — `shape(payload)` (the outbound body a target
  expects) and `parse(status, headers, body) → (external_ref, external_url)` — so
  retry/redrive/linkage/tests stay adapter-agnostic. `GenericIncidentAdapter`
  (default: sends the curated envelope as-is, reads ref/url from common
  headers/JSON) and a real `PagerDutyIncidentAdapter` (reshapes into a PagerDuty
  Events-v2-style envelope — `event_action` mapped from the transition, `dedup_key`
  = the incident signal — and parses the returned `dedup_key`). `kind=jira/opsgenie`
  are reserved labels that fall back to generic shaping today (honest — no fake
  vendor support claimed). New vendors are a one-class addition; the transport
  (`_send`) stays a single injectable primitive.
- **Stable external linking** (table `incident_external_links`): on every
  **successful** sync, the incident→external correlation is **upserted** — one row
  per (incident, target) holding the latest `external_ref` + (when the target
  returned one) `external_url`, plus `last_action`/`last_synced_at`. A link is
  **never invented** (only persisted when the adapter actually parsed a ref/url) and
  a failed sync **never overwrites a good link** (the link reflects the last
  success; staleness is derived, not destructive). `IncidentSyncRecord` also gains
  `external_url` (additive `ensure_runtime_columns` ALTER).
- **Per-incident sync health** (`incident_sync_status(incident_id)` →
  `GET /operator/incidents/{id}/sync`): curated **links + recent attempts + an
  honest summary** — `linked`, `synced`, `behind` (the most recent transition
  hasn't landed externally), `last_synced_at` / `last_failed_at` / `last_error`,
  and `recovered_after_redrive` (latest synced record is itself a redrive). This
  answers "was it synced? to where? is there a stable ref/url? is the link stale or
  current? did redrive recover it?" without a payload dump.
- **Target health** (`target_health(id)` → `GET /operator/incident-targets/{id}/
  health`): recent attempt mix (synced/failed/pending) + last success/failure +
  `healthy|degraded` from `consecutive_failures`. Secret still never returned.
- **Console** (`app/operator/page.tsx`): expanding an incident now also loads its
  **External sync** linkage line — an honest status badge (`incidentSyncSummary`:
  Not synced / Externally linked / Sync behind / Last sync failed / Recovered after
  redrive), the target name/kind, the external `ref`, and an **Open ↗** link when a
  real `external_url` exists. The global sync card's record rows gain the same
  **Open ↗** when linked. Still operator-only: no link/ref/url field leaks into
  `GET /jobs/{id}`.
- Pinned by `backend/tests/test_incident_sync.py` (success persists ref/url + upserts
  link; link **not invented** when the target returns none; behind→recovered after
  redrive; PagerDuty adapter shapes the envelope specifically + parses `dedup_key`;
  per-incident sync status + target health over HTTP with gating/404; no
  `external_url` leak into `/jobs/{id}`) and `frontend/lib/operator.test.mts`
  (`incidentSyncSummary`).

### Bounded inbound reconciliation, drift & staleness (G-7)

Outbound sync gains a **bounded inbound recheck** so AIRA-X can tell whether the
external system still matches the local incident — explicitly **not** full
bidirectional sync: local state stays primary, and a refresh **never mutates the
local incident**, it only records what was observed externally.

- **Adapter refresh capability.** Each adapter declares `supports_refresh` and a
  `parse_status(code, headers, body) → (external_exists, normalized_status,
  external_url)`. `GenericIncidentAdapter` + `PagerDutyIncidentAdapter` support a
  bounded inbound GET; `jira`/`opsgenie` now map to an `OutboundOnlyAdapter`
  (`supports_refresh = False`) — honestly outbound-only until a real adapter lands.
  External statuses normalize to `open` / `acknowledged` / `resolved` / `missing` /
  `unknown`. The inbound transport is a single injectable `_fetch` (GET `?ref=`,
  network-free in tests).
- **Link reconciliation state.** `incident_external_links` gains `last_checked_at`,
  `external_status`, `external_exists` (additive `ensure_runtime_columns` ALTER).
  `refresh(incident_id)` rechecks each linked target whose adapter supports it and
  records the observation on the link — outbound-only adapters are skipped, never
  faked.
- **Pure drift classifier.** `classify_link_status(local_state, last_synced_at,
  last_checked_at, external_exists, external_status, now, stale_seconds)` →
  `(status, reason)` over six honest states: `never_linked`, `linked`, `refreshed`,
  `stale` (no successful sync within `incident_link_stale_seconds`, default 24h),
  `drifted` (external resolved while local open, or local recovered while external
  open), `missing_external` (external not found). The incident-level rollup takes the
  **worst (most actionable) link**.
- **Operator-only APIs:** `GET /operator/incidents/{id}/sync` now carries
  `link_status` / `reason` / `refresh_supported` / `last_checked_at` + per-link
  external state; `POST /operator/incidents/{id}/sync/refresh` (409 if no links);
  `GET /operator/incident-sync/drift` (triage list of drifted/missing/stale links —
  declared *before* `/incident-sync/{record_id}` so "drift" isn't parsed as an id).
- **Console:** the incident's External-sync line shows an honest reconciliation badge
  (`incidentSyncSummary` now puts drift/missing/stale ahead of plain outbound
  health), the reason, the observed external status, synced/checked times, a
  **Refresh** button when the adapter supports it, and "refresh unsupported" when it
  doesn't. Still operator-only — no link/drift field leaks into `GET /jobs/{id}`.
- Pinned by `backend/tests/test_incident_sync.py` (pure classifier across all six
  verdicts; refresh detects external-resolved drift / missing / aligned without
  mutating the local incident; outbound-only adapter is honestly skipped; age-based
  stale; refresh-without-links 409; refresh+drift over HTTP with gating; stale config
  rejected) and `frontend/lib/operator.test.mts` (`incidentSyncSummary` drift-first,
  `linkStatusTone`).

### Drift resolution, link repair & scheduled reconciliation (G-8)

Detected drift becomes **actionable**: an operator can repair a bad/missing link
from the incident view without DB edits, and a bounded sweep keeps stale links
fresh — still **outbound-primary** (these actions never mutate local incident state).

- **Repair actions** (`app/incident_sync.py`, all operator-only, none touch local
  state): `detach(incident, target)` marks a bad link **intentionally detached**
  (preserved for lineage via `detached_at`, excluded from drift/reconcile — a new
  `detached` link verdict); `relink(incident, target, external_ref)` repairs/
  establishes a link but **only after the adapter verifies the ref exists** (a
  bounded inbound `_fetch`) — refused honestly for outbound-only adapters or
  unverifiable refs, **never trusting an arbitrary link blindly**;
  `redrive_incident_latest(incident)` redrives the most recent failed sync straight
  from the incident context.
- **Action availability is honest.** The per-incident summary now carries an
  `actions` block — `can_refresh` / `can_redrive` / `can_detach` / `can_relink` —
  computed from real link/record state, so the console only offers what will work.
- **Audit trail.** New `incident_reconciliation_events` table appends one curated row
  per repair action (refresh / redrive / detach / relink / reconcile) with its
  outcome (`ok` / `failed` / `unsupported` / `missing` / `skipped`) — answering "was
  a repair attempted, and did it work?" durably, no payloads/secrets. Surfaced as
  `reconciliation` in the sync status.
- **Scheduled reconciliation.** `reconcile(max_incidents=)` rechecks the active,
  refresh-capable links that most need it (never-checked first, then stale), **capped
  by `incident_reconcile_max_per_sweep`** (default 25) so external systems are never
  spammed. Wired into the operator sweep (alongside `flush_pending`) and exposed as
  `POST /operator/incident-sync/reconcile` (the path a scheduled worker can call).
- **Operator-only APIs:** `POST /operator/incidents/{id}/sync/redrive`,
  `POST .../sync/detach` (`{target_id}`), `POST .../sync/relink`
  (`{target_id, external_ref, external_url?}` → 409 when refused),
  `POST /operator/incident-sync/reconcile`. Refresh/detach/relink/redrive all thread
  the declared operator as the action's `actor`.
- **Console:** the incident's External-sync line now offers **Refresh / Redrive /
  Detach / Relink** (gated by the `actions` flags), an inline relink input
  ("External reference · verified via adapter"), and a "last action (outcome)"
  footnote. Detached links read "Link detached" (muted). Still operator-only — no
  `detached` / `link_status` / `reconciliation` field leaks into `GET /jobs/{id}`.
- Pinned by `backend/tests/test_incident_sync.py` (detach excludes from drift without
  touching local state + records the event; relink requires adapter verification —
  refused when unverifiable or outbound-only, reattaches on success; redrive from
  incident context; bounded reconcile sweep rechecks stale links without mutating
  local state; HTTP gating across every resolution endpoint; reconcile config
  rejected; no reconciliation field leaks into `/jobs/{id}`) and
  `frontend/lib/operator.test.mts` (`detached` in `incidentSyncSummary` /
  `linkStatusTone`).

### Explicit local-vs-external resolution (apply / push / capabilities) (G-9)

Detected disagreement becomes **explicitly resolvable from either side** — local or
external — without AIRA-X ever becoming a silent bidirectional system. The
guardrail is absolute: **only an explicit operator action may change local incident
state from an external observation**; refresh/reconcile still never do.

- **Explicit adapter capabilities** (`adapter_capabilities(kind)` in
  `app/incident_sync.py`): `{refresh, push_outward, relink_validation}`. Generic and
  PagerDuty are fully capable; the outbound-only kinds (`jira`/`opsgenie`) report
  `push_outward: true` (they *can* send) but `refresh`/`relink_validation: false`
  (they can't read back) — honest, no faked vendor support. Surfaced per-link.
- **Apply-from-external** (`apply_from_external(incident, action)` →
  `POST /operator/incidents/{id}/sync/apply`): the **only** path that turns an
  observed external state into a local change, and only when the disagreement
  actually supports it. `accept_resolved` (external reports resolved while local is
  open) calls the new explicit `incident_service.mark_recovered()` — a deliberate
  single-incident recovery recorded on the incident trail with reason "applied
  external resolution" (`changed_local: true`). `accept_missing` (external gone)
  detaches the dead link (`changed_local: false` — linkage only). Refused with 409
  when the offered `apply_action` doesn't match what's observed.
- **Push-outward** (`push_outward(incident, target_id?)` →
  `POST /operator/incidents/{id}/sync/push`): explicitly re-sends the **current**
  local state to push-capable targets — e.g. push a local `recovered` so the
  external incident resolves (PagerDuty maps `recovered → event_action: resolve`).
  Targets whose adapter can't push are skipped honestly; local state is never
  changed.
- **Honest action availability.** The per-incident `actions` block gains
  `can_apply` + `apply_action` (the bounded suggestion derived from the observed
  drift) and `can_push`. Every apply/push is recorded in
  `incident_reconciliation_events` (action `apply:accept_resolved` / `push` / …),
  so "was a resolution attempted, did it work, and did it change local state or only
  linkage?" is answerable.
- **Console:** the External-sync line adds an accent **Apply resolution / Accept
  missing** button (only when `can_apply`, with a one-line explanation of its local
  effect) and a **Push outward** button (when `can_push`); apply that recovers
  locally also refreshes the incident list. Still operator-only — no
  `capabilities` / `apply_action` field leaks into `GET /jobs/{id}`.
- Pinned by `backend/tests/test_incident_sync.py` (capabilities are explicit +
  honest; external-resolved is actionable without silently mutating local; apply
  recovers local **only when invoked** + records the trail/reconciliation; apply
  refused when not applicable; accept_missing detaches linkage only; push uses the
  adapter + records, and outbound-only kinds still push; apply/push over HTTP with
  re-apply 409 + gating) and `frontend/lib/operator.test.mts` (`applyActionLabel`).

### Richer vendor adapters, bounded inbound status sync & suggestions (G-10)

A supported adapter can now surface a **richer-than-generic** bounded snapshot of
external state, turned into **operator suggestions** — without ever becoming
source-of-truth (local state stays primary; inbound never mutates it).

- **Adapter capability tiers.** Adapters gain `supports_status_sync` and a single
  `support_level` (`rich` / `refresh` / `outbound_only`). Generic = `refresh`
  (existence/status/url only); **PagerDuty = `rich`** (parses a few bounded
  normalized fields from an incident-shaped response — assignee *display name*,
  urgency→severity, `last_status_change_at`, an alert/note **count**); jira/opsgenie
  = `outbound_only`. `adapter_capabilities(kind)` exposes the full set + level;
  `GET /operator/incident-targets/{id}/capabilities` surfaces it for the console.
- **Bounded inbound snapshot.** Every inbound parse goes through `_external_state(…)`
  — a hard allow-list of `{exists, status, url, assignee, severity, updated_at,
  comment_count}`, each size-clamped, with **no raw-payload escape hatch** (vendor
  bodies, emails, comment text never pass through). `IncidentExternalLink` stores
  `external_assignee` / `external_severity` / `external_updated_at` /
  `external_comment_count` (additive ALTER), populated **only** by status-sync
  adapters during `refresh`. `_fetch` now returns `(ok, snapshot, err)`.
- **Operator suggestions.** Pure `external_state_suggestions(local_incident, link)`
  → a bounded list (≤4) of `{code, tone, text}`: external resolved while local open
  (→ consider applying), acknowledged externally by X, external owner ≠ local owner,
  high external severity, external missing (→ detach), or "aligned — no action".
  Advisory only; surfaced as `summary.suggestions` + `summary.support_level`.
- **Explicit workflow preserved.** Refresh updates the bounded snapshot; **apply /
  push stay explicit and capability-driven** (G-9). Inbound status sync **never**
  silently mutates local incident state — proven by tests asserting local state +
  owner are untouched after a rich refresh.
- **Console:** the External-sync block gains a **support-level chip**, a concise
  external-state line (owner / severity / note-count / updated) when a rich adapter
  populated it, and a short **suggestions** list with tone dots. Still operator-only
  — no `external_assignee` / `support_level` / `suggestions` / `capabilities` leaks
  into `GET /jobs/{id}`.
- Pinned by `backend/tests/test_incident_sync.py` (PagerDuty parses a bounded rich
  snapshot + drops raw body/email; generic stays thin; status-sync stores only
  normalized fields and keeps local primary; suggestions are bounded/honest +
  surface after refresh; capabilities endpoint with gating/404; no rich-inbound leak
  into `/jobs/{id}`) and `frontend/lib/operator.test.mts` (`supportLevelLabel`).

### Bounded apply policy, vendor-typed actions & audit-safe refusals (G-11)

The resolution workflow gets a **policy layer separate from capability** and a
**per-action availability matrix** with explicit blast-radius. Refusals are now
auditable, and richer adapters expose vendor-typed outbound actions instead of just
"push". Local state primacy remains absolute — the only path that may change a
local incident from external observation is still an explicit operator
`apply_resolved`, which now goes through both capability *and* policy gates.

- **Per-action capabilities.** Every adapter declares
  `supports_apply_resolved` / `supports_apply_missing` (bounded INBOUND→LOCAL
  applications), and `supports_external_resolve` / `supports_external_reopen`
  (vendor-TYPED OUTBOUND actions — PagerDuty maps `recovered → event_action: resolve`
  and `reopened → trigger`). Generic targets get apply support (they can observe)
  but no typed outbound mapping; outbound-only kinds (jira/opsgenie) get neither.
- **`apply_policy(kind, action) → (allowed, code, reason)`** is a pure, stable
  allow-list separate from capability. Today it just defers to the adapter's
  capability flags, but the seam is in place for per-target overrides later. Codes
  (`allowed` / `denied:capability` / `denied:unknown_action` / `denied:state` /
  `failed`) are stable so the audit trail and console group refusals reliably.
- **Audited refusals.** `apply_from_external` now logs **every** outcome
  (`refused:capability` / `refused:state` / `refused:unknown_action`) to
  `incident_reconciliation_events`, alongside the existing `ok` / `failed`. The
  audit table answers "was this attempt refused and why?" durably — no payloads,
  just `{action, outcome, actor, detail, at}`.
- **Per-action availability matrix** (`summary.available_actions[]`): one entry
  per action — `refresh` / `redrive` / `detach` / `relink` / `apply_resolved` /
  `apply_missing` / `push` — with `{action, label, available, reason, effect}`.
  **`effect`** is the explicit blast radius: `none` (observe only),
  `linkage` (link state only), `local` (changes the local incident — only ever
  `apply_resolved`), or `external` (pushes to the external system). Action gating
  now lives in one place, so the console can't accidentally offer something the
  policy or capability refuses.
- **Operator-only API:** `GET /operator/incidents/{id}/sync/actions` exposes just
  the curated action matrix — a small, focused preview useful for review tooling
  without pulling the full status payload.
- **Console:** the existing Apply button now carries an explicit effect hint
  (e.g. "Apply external resolution (recover locally) · *changes local state*" vs
  "Detach (external missing) · *linkage only*"), surfaced via the pure
  `actionEffectLabel` helper.
- Pinned by `backend/tests/test_incident_sync.py` (apply_policy pure across
  allowed/capability/unknown; refused apply is audited with stable codes
  including unknown-action and state-not-applicable; per-action effect matrix is
  honest about local/linkage/external/none; outbound-only target excludes apply;
  capability-denied apply records `refused:capability` and leaves local untouched;
  `/sync/actions` endpoint with gating + 404; HTTP-level 422 on unknown apply
  action) and `frontend/lib/operator.test.mts` (`actionEffectLabel`).

### Per-target action policy & real vendor-typed external actions (G-12)

Action availability now varies **per target**, not just per adapter kind, and
richer adapters expose **real vendor-typed outbound actions** (resolve / reopen /
acknowledge) — all without DB edits, all bounded, audited, and operator-only. Local
state primacy is intact: the only action that changes a local incident is still the
explicit `apply_resolved`, now gated by capability AND per-target policy.

- **Three-layer precedence.** `target_action_policy(kind, overrides, action) →
  (allowed, code, reason)` resolves: (1) adapter **capability** (class flags), then
  (2) per-target **override** (tri-state: NULL = adapter default, True = permitted,
  False = denied — an override can only *narrow* capability, never enable beyond it),
  then the caller applies (3) incident-**state** applicability. Stable codes add
  `denied:target_policy` alongside the existing `denied:capability` /
  `denied:unknown_action`.
- **Durable per-target overrides.** `external_incident_targets` gains six nullable
  override columns (`allow_apply_resolved` / `allow_apply_missing` /
  `allow_external_resolve` / `allow_external_reopen` / `allow_external_acknowledge`
  / `allow_push_outward`; additive `ensure_runtime_columns` ALTER). Tunable via the
  existing `PATCH /operator/incident-targets/{id}` (operator-only, validated,
  secret never exposed).
- **Real vendor-typed external actions.** Adapters declare
  `supports_external_resolve` / `_reopen` / `_acknowledge`; PagerDuty maps each to a
  typed `event_action` (`resolve` / `trigger` / `acknowledge`), generic/outbound-only
  honestly don't. `external_action(incident, action)` →
  `POST /operator/incidents/{id}/sync/external-action` sends the mapped vendor event
  to **each linked target individually**, policy-checked per target, refusals audited
  per target. Effect is strictly **external** — it never changes local state.
- **Policy inspection.** `GET /operator/incident-targets/{id}/policy` returns, for
  every bounded action, `{capable, override, effective, code, reason}` — the single
  place an operator sees capability-vs-override-vs-effect. Targets' read payloads now
  carry `capabilities` + `policy_overrides`; links carry `policy_overrides`; the
  `available_actions[]` matrix gains the three vendor actions (all `effect: external`)
  and is now evaluated against per-target policy.
- **Console:** the incident sync line renders the available vendor-typed external
  actions (from `available_actions`, already capability+policy gated) with their
  effect hint; pure helpers `policyOverrideLabel` (Default/Allowed/Denied) and the
  existing `actionEffectLabel` keep the UI honest. No `policy_overrides` /
  `capabilities` / `available_actions` field leaks into `GET /jobs/{id}`.
- Pinned by `backend/tests/test_incident_sync.py` (precedence capability→override
  is honest; per-target override denies an otherwise-capable action; policy view
  shows capable/override/effective; override-denied `apply_resolved` refused with
  `denied:target_policy` + audited + local untouched; vendor `external_action`
  executes only when capability+policy align and sends the typed `event_action`
  without touching local; capability- and target-denied external actions audited;
  full HTTP path for policy view + PATCH override + external-action with 409 on
  denial, gating, 404, and 422 on unknown action; no policy field leaks into
  `/jobs/{id}`) and `frontend/lib/operator.test.mts` (`policyOverrideLabel`).

### Per-target inbound-state policy & richer adapter advertisement (G-13)

The same per-target tri-state model now governs **inbound** data, not just outbound
actions: an operator can hide a richer external field (assignee / severity /
updated_at / comment_count) or silence suggestions **for one target** without DB
edits. Local-state primacy is untouched — inbound policy only changes what is
*observed, stored, and suggested*, never what becomes local truth.

- **Adapters advertise their bounded inbound fields.** Each adapter declares
  `inbound_fields` (PagerDuty: assignee/severity/updated_at/comment_count; generic
  and outbound-only: none). `adapter_capabilities` surfaces this as an
  `inbound_fields` map — the console shows exactly what's *possible* per kind.
- **Three-layer inbound resolution.** `inbound_field_policy(kind, overrides, field) →
  (allowed, code, reason)`: adapter **capability** → per-target **override**
  (tri-state NULL/True/False, can only narrow) → read-time **mask**. Same stable
  codes (`denied:capability` / `denied:target_policy`). Suggestions are a derived
  view gated by a master `allow_external_suggestions`.
- **Durable per-target inbound overrides.** `external_incident_targets` gains five
  nullable columns (`allow_external_assignee` / `_severity` / `_updated_at` /
  `_comment_count` / `_suggestions`; additive ALTER), tunable via the same
  `PATCH /operator/incident-targets/{id}`.
- **Data minimization + read-time masking.** `refresh` imports **only** the richer
  fields this target permits (a disabled field is never stored). `_clean_link` also
  **masks at read** — toggling a target's policy hides even previously-imported
  values immediately, and exposes `inbound_visibility` + `suggestions_allowed` so the
  console can explain *why* a field is absent.
- **Policy-aware suggestions.** Suggestions derive only from the masked link, so a
  target that hides external assignee produces no owner-mismatch suggestion, one that
  hides severity produces no severity suggestion, and `allow_external_suggestions:
  false` suppresses them wholesale.
- **Policy inspection** extends `GET /operator/incident-targets/{id}/policy` with an
  `inbound` section (`{capable, override, effective, code, reason}` per field +
  suggestions). Targets' read payloads carry the full `policy_overrides`; links carry
  `inbound_visibility` / `suggestions_allowed`.
- **Console:** the incident sync line renders only permitted richer fields and adds a
  calm "Hidden by target policy: …" note (pure `hiddenInboundFields` helper) plus a
  "Suggestions disabled for this target" line — honest about what's hidden vs
  unavailable. No inbound-policy field leaks into `GET /jobs/{id}`.
- Pinned by `backend/tests/test_incident_sync.py` (inbound precedence capability→
  override; override hides a capable field; policy view `inbound` section; refresh
  stores only permitted fields + never mutates local; read-time mask hides a field
  disabled after import; hidden field suppresses its suggestion; suggestions master
  switch; full HTTP path with gating; no inbound-policy leak into `/jobs/{id}`) and
  `frontend/lib/operator.test.mts` (`hiddenInboundFields`).

### Adapter profiles/presets, broader vendor rollout & onboarding (G-14)

The incident-sync model grows a **profile layer** so operators onboard a target from
a vendor preset instead of hand-setting every override, and a **second first-class
rich adapter** (Opsgenie) proves the model isn't PagerDuty-only. Local-state primacy
is untouched: profiles only set *defaults* for what's observed/suggested/allowed,
never what becomes local truth.

- **Opsgenie rich adapter.** `OpsgenieIncidentAdapter` is now a real status-sync
  adapter (was outbound-only): Alert-API-style `shape` (action create/close/
  acknowledge, `alias` = signal), `parse_status` (open/acked/closed), and
  `parse_snapshot` (bounded owner/priority→severity/updatedAt; **no** note count, and
  raw bodies never imported). Honestly has **no clean reopen** so
  `external_reopen` stays False. Registry order is now generic / pagerduty / opsgenie
  (rich) / jira (outbound-only).
- **Profile registry** (`_PROFILES`, pure declarations over existing adapters — no new
  vendor logic hides here): `generic`, `pagerduty`, **`pagerduty-readonly`** (same
  rich inbound, but every external-mutation action disabled by default — "watch,
  don't push"), `opsgenie`, `jira-outbound`. Each profile carries a label, summary,
  support level, and `default_actions`/`default_inbound` maps. `list_profiles()`.
- **Four-layer precedence.** `target_action_policy` / `inbound_field_policy` now
  resolve **capability → profile default → per-target override → state**. An explicit
  override is *more specific* than the profile, so it can re-enable what a profile
  disabled (still bounded by capability — a profile can never exceed it). New stable
  code `denied:profile`.
- **Durable profile on the target.** `external_incident_targets` gains a `profile`
  column (additive ALTER; NULL → the kind's default profile). `create_target(profile=)`
  onboards from a preset (the profile picks the adapter kind); `update_target(profile=)`
  re-points the kind. `_clean_target` exposes `profile` + `profile_label`.
- **Onboarding inspection.** `GET /operator/incident-target-profiles` lists presets;
  `GET /operator/incident-targets/{id}/profile` shows the target's profile + defaults
  + effective policy; the `/policy` view now adds `profile_default` and a **`source`**
  per decision (`capability` / `profile` / `override` / `default`) — so an operator
  can see *why* something is on/off before relying on the target.
- **Console:** the incident sync line shows a profile badge when a target uses a
  non-default preset; pure `policySourceLabel` names the decision source. No
  profile/preset field leaks into `GET /jobs/{id}`.
- Pinned by `backend/tests/test_incident_sync.py` (Opsgenie is a real rich adapter +
  bounded shape/snapshot that drops raw bodies; profiles list honest + gated; profile
  default narrows within capability and an override re-enables it; profile can't
  exceed capability; create/patch from profile sets kind + defaults; profile view
  shows defaults + sources; readonly profile blocks an external action until
  overridden without touching local; full HTTP path with gating + 404; no profile
  leak into `/jobs/{id}`) and `frontend/lib/operator.test.mts` (`policySourceLabel`).

### Target preflight validation, safe test-send & durable readiness (G-15)

Onboarding a sync target stops being "save config and hope": an operator can
**validate** a target and send a **safe synthetic test** before trusting it with real
incidents, and the result is a durable, explainable **readiness** state. Nothing here
touches a real incident or local state.

- **Readiness is computed, not stored stale.** Six durable evidence columns on
  `external_incident_targets` (`last_validated_at` / `last_test_at` / `last_success_at`
  / `last_failure_at` / `last_check_error` / `last_check_kind`; additive ALTER). Pure
  `compute_readiness(...)` derives the state from config + evidence → `unverified` /
  `ready` / `degraded` / `invalid_config` / `auth_failed` / `test_failed` / `disabled`,
  with a `source` (none/config/connectivity/test) and reason.
- **Preflight validation** (`validate(target)` → `POST .../validate`): bounded checks —
  config present, profile/kind compatible, policy overrides effective (warns on
  enabling an action the adapter can't do), secret/signing sanity, and a **real
  connectivity/auth probe** via the injectable `_fetch` for refresh-capable adapters
  (outbound-only adapters honestly report `skip`). Records durable evidence; an
  HTTP 401/403 → `auth_failed`.
- **Safe test-send** (`test_send(target)` → `POST .../test`): ONE clearly-synthetic
  event through the **real adapter transport** — action `recovered` resolving the
  synthetic `aira-x:preflight-test` ref (a no-op vendor resolve/close of something
  never triggered), carrying a `test: true` marker. It **never** creates/mutates a
  real incident, **never** writes an `IncidentSyncRecord`, and never pollutes incident
  history. Refused (409) for disabled/invalid targets. Records durable test evidence.
- **Inspection.** `_clean_target` (and thus the existing `GET .../health` + the targets
  list) now carries `readiness` + `readiness_facts`; the validate/test responses return
  the per-check list and the recomputed readiness so the console renders from one place.
- **Console:** the External-sync panel's target rows now show a **readiness badge**
  (pure `readinessTone`/`readinessLabel`), the last-checked time + reason, and
  **Validate** / **Test** buttons (Test disabled for a disabled target). No readiness
  field leaks into `GET /jobs/{id}`.
- Pinned by `backend/tests/test_incident_sync.py` (`compute_readiness` pure across all
  states; fresh target is unverified; validate passes a reachable refresh-capable
  target and detects auth failure; outbound-only skips connectivity honestly; invalid
  config + ineffective-override warning; test-send uses the real transport with the
  `test` marker + resolve no-op, writes NO sync record and creates NO incident;
  test-send failure → `test_failed`; refused for disabled; full HTTP path with gating
  + 404; no readiness leak into `/jobs/{id}`) and `frontend/lib/operator.test.mts`
  (`readinessTone`/`readinessLabel`).

### Target lifecycle & secret hygiene (Phase 2)

Onboarding stays trustworthy *after* credentials change: rotation, change-driven
revalidation, stale-readiness aging, scheduled revalidation, a durable readiness
history, and a "needs attention" triage list. Readiness evidence stays separate from
incident business state, and validation/test never touch a real incident.

- **Stale readiness.** `compute_readiness` gains a `stale` verdict — a
  previously-passing target whose last success is older than
  `incident_target_revalidate_seconds` (default 7d) reads `stale` ("revalidate")
  rather than falsely `ready`. `READY_ATTENTION_STATES` groups the non-ready,
  non-disabled states.
- **Secret rotation** (`rotate_secret` → `POST .../rotate-secret`) and any
  secret/URL change via PATCH **invalidate prior readiness evidence**
  (`_invalidate_readiness` → `unverified`) so a target must be revalidated before it's
  trusted again. Secrets are never returned (only `has_secret`).
- **Durable check history.** New `incident_target_check_events` table (monotonic PK)
  records one curated, secret-free row per lifecycle event — validate / test /
  revalidate / secret_rotated / config_changed / disabled / enabled — with the
  resulting readiness/outcome and reason. Surfaced as `check_history` on
  `GET .../health`.
- **Scheduled revalidation.** `revalidate_stale(max_targets=)` re-runs preflight on
  enabled targets that need attention, capped by `incident_revalidate_max_per_sweep`
  (default 10), wired into the operator sweep alongside `flush_pending` + `reconcile`.
- **Needs-attention triage.** `targets_needing_attention()` →
  `GET /operator/incident-targets/attention` lists enabled-but-not-ready targets with
  readiness + facts. The console's External-sync header shows an "N need attention"
  badge derived from the loaded targets' readiness; the `stale` state has its own tone.
- Deployment posture is documented in `docs/PRODUCTION_READINESS.md` (web/worker
  split, SQLite→Postgres seam, health/ready probes, secret hygiene, backups).
- Pinned by `backend/tests/test_incident_sync.py` (stale aging pure; secret change +
  rotate invalidate readiness + audit; disable/re-enable audited; needs-attention
  excludes ready targets; scheduled revalidate rechecks + flips to ready; full HTTP
  rotate/attention/history with gating + 404; revalidate config rejected; no lifecycle
  field leaks into `/jobs/{id}`) and `frontend/lib/operator.test.mts` (`stale` in
  `readinessTone`/`readinessLabel`).

### Operator runbooks & incident operations (Phase 4)

Operating incident sync used to need tribal knowledge — an operator staring at a
`degraded` target or a `drifted` incident had to *know* the recovery move. Phase 4
turns that knowledge into **deterministic, table-driven metadata** (never AI advice)
plus written runbooks, so the next step is on screen and recovery under pressure is a
checklist, not a guess.

**Derived metadata (deterministic — a fixed table over existing state).**
- `readiness_guidance(state)` → `{recommended_action, next_step}` rides along on every
  readiness object (so the console, attention list, and health view all carry it). The
  action codes are stable: `validate` (unverified/stale/degraded), `rotate_secret`
  (auth_failed), `fix_config` (invalid_config), `test` (test_failed), `enable`
  (disabled). `ready` → no action.
- `link_guidance(link_status, apply_action)` → `{recommended_action, next_step}` on an
  incident's sync summary: `detach` (missing_external), `refresh` (stale/drifted),
  `relink` (detached). When the observed disagreement supports an apply, that wins —
  external-resolved/local-open → `apply_resolved`.
- All guidance is **pure and unknown-safe**: an unrecognized state yields a null action,
  never a crash or a fabricated suggestion.

**Triage rollups (bounded, deterministic).**
`attention_summary()` → `GET /operator/incident-targets/attention/summary` is a
one-pass rollup over **all** targets — never a history dump:
- `rollup` — `{ready, attention, disabled, total}` (the buckets always cover every
  target).
- `by_state` / `by_action` — grouped counts (how many auth failures? how many need a
  secret rotation?).
- `oldest` — the single longest-waiting attention item (by last-failure → last-validated
  → created), so the most-stale problem is never buried.

The console's External-sync panel renders a grouped rollup (hard failures first, each
labeled with the action that clears it) and a `→ Rotate secret`-style next-step chip per
unready target — all from already-loaded data, no extra round-trip.

**Audit discoverability (surface, don't duplicate).**
`target_health` gains a `check_summary` derived from the durable check trail:
`latest` (most recent meaningful event), `last_validation_ok`, and
`last_validation_failed` — so "when did this last pass, and when did it last fail?" is a
glance, not a scroll through `check_history`. An incident's sync summary gains
`last_reconciliation` (the single most recent reconciliation action) alongside the full
`reconciliation` trail.

**The runbooks.** Step-by-step recovery procedures for every operational task —
target onboarding, validation / auth / readiness failures, secret rotation, drifted
incidents, missing external references, relink, detach, external apply, external
resolve/reopen/acknowledge, and recovery after accidental disablement — live in
`docs/PRODUCTION_READINESS.md` (§8 Operator runbooks, §9 Troubleshooting matrix, §10
Rollout guidance). Each maps the on-screen `recommended_action` to the exact operator
move and its blast radius.

- Guardrails preserved: **no automatic state mutation** (every recovery move stays a
  deliberate, audited operator action), no weakening of operator-only separation (all
  surfaces require the service key), no API breaks (every field is additive), and **no
  change to the chat product**.
- Pinned by `backend/tests/test_incident_sync.py` (guidance tables pure + unknown-safe;
  readiness carries the action everywhere; auth-failure → rotate; attention items carry
  flattened triage fields; `attention_summary` rollup/grouping/oldest incl. empty + the
  oldest-is-earliest edge; `check_summary` separates last pass/fail; link guidance incl.
  apply refinement; incident summary carries action + `last_reconciliation`; HTTP
  summary endpoint with gating) and `frontend/lib/operator.test.mts`
  (`recommendedActionLabel`, `readinessGuidanceAction`, `attentionRollupRows` ordering +
  empty, `oldestAttentionLabel`).

### Observability & operational intelligence (Phase 5)

The runbooks (Phase 4) tell an operator what to do about *one* target or incident. Phase
5 answers the fleet-level questions that previously required manual investigation —
*"are validations passing? is drift growing? which targets keep failing auth?"* — with
**bounded, deterministic metrics computed on read from existing audit/history**. No
duplicate storage, no background aggregation, no AI, and nothing here ever mutates,
enforces, or notifies. It is pure observability.

**One endpoint:** `GET /operator/incident-sync/metrics` →
`incident_sync_service.incident_metrics()`. Everything below is one read.

- **Metrics foundation.** The pure module `app/incident_metrics.py` turns extracted
  samples (timestamp + outcome class) into rollups — it holds no state and touches no
  DB, so the math is unit-tested in isolation. `incident_metrics()` does the bounded
  reads (capped at `METRICS_EVENT_CAP = 5000` most-recent rows per stream) and feeds
  them in.
- **Readiness distribution** (point-in-time): every readiness state counted, plus
  `ready` / `attention` / `disabled` / `stale` / `auth_failed` rollups and `enabled` /
  `total`. Derived from the same computed `_readiness` the console already trusts.
- **Trend windows** (`24h` / `7d` / `30d`, fixed — no custom ranges, no warehouse): for
  each of **validation**, **reconciliation**, **refresh**, **apply**,
  **external_action**, and **sync**, a `{pass, fail, neutral, total, pass_pct}` rollup.
  `pass_pct` is over *decided* (pass+fail) samples and is **`null` when nothing has
  happened yet** — an honest "no data", never a misleading 0%/100%. Validation pass =
  a `validate`/`revalidate` check event whose outcome is `ready`; reconciliation/refresh
  /apply/external from the reconciliation-event trail (`ok` pass, `failed`/`missing`
  fail, `skipped`/`unsupported` neutral); sync from `synced`/`failed` sync records.
- **Drift snapshot:** active-link backlog count, grouping by link status
  (drifted/missing/stale), and the single oldest unresolved item with its age in seconds.
- **SLO signals** (observe-only percentages, `null` on no data): `target_readiness_pct`
  (ready/enabled), `validation_pass_pct_24h`, `reconciliation_success_pct_24h`,
  `sync_success_pct_24h`. Signals, never gates — AIRA-X never blocks on an SLO.
- **Candidate alerts** (deterministic threshold observations — **no notification, no
  paging, no email/Slack**): `repeated_auth_failures` / `repeated_validation_failures`
  (per target, ≥3 in 24h), `drift_backlog` (≥5 unresolved), `stale_readiness` (≥3 stale),
  `reconciliation_failures` (≥5 failed in 24h). Severity is deterministic — `critical`
  at ≥2× the threshold, else `warning` — and the list is sorted critical-first. Each
  alert is an *observation* the operator chooses to act on; nothing fires automatically.
- **Console:** the Incidents tab renders a read-only "Sync observability" panel — SLO
  tiles, targets-by-state chips, the 24h per-category pass rates, the drift backlog line,
  and the candidate-alert list. No actions live in the panel (it's purely a dashboard);
  remediation stays in the existing target/incident affordances.
- Guardrails: every number is **explainable and reproducible** from existing rows (same
  rows + same `now` → same output); operator-only (service-key gated); additive
  (no API break); chat product untouched.
- Pinned by `backend/tests/test_incident_sync.py` (pure `pct`/`within`/`window_rollup`/
  categorize/classify + threshold/severity/sort for alerts; integration: readiness
  distribution + SLO, validation rollup, reconciliation/refresh/drift snapshot, alerts
  from repeated auth failures, empty-is-well-formed, HTTP endpoint with gating) and
  `frontend/lib/operator.test.mts` (`formatMetricPct`, `sloTone` bands, `alertSeverityTone`,
  `trendWindowLabel`, `formatAgeSeconds`, `readinessDashboardRows`, `sloRows`).
- Metrics glossary, SLI definitions, the operational review checklist, and the
  degradation interpretation guide live in `docs/PRODUCTION_READINESS.md` (§11–§14).

### Demo seed & guided walkthrough (Phase 6 — demonstrability)

A fresh clone has an empty database, so the operator console, the observability
dashboard, and the drift/recovery flows have nothing to show — the platform's strongest
capabilities are invisible to a recruiter, evaluator, or customer on first run. Phase 6
makes AIRA-X **instantly demonstrable**: one operator-gated call populates a realistic,
deterministic incident-sync scenario that lights up every Phase 1–5 capability at once,
plus a guided walkthrough that tells the viewer exactly what to look at.

**Instant demo (operator):**
```bash
# with the operator service key configured (API_KEY)
curl -s -X POST localhost:8000/operator/demo/seed   -H "X-API-Key: $API_KEY"
curl -s     localhost:8000/operator/demo/status -H "X-API-Key: $API_KEY"   # tour + counts
curl -s -X POST localhost:8000/operator/demo/reset  -H "X-API-Key: $API_KEY"
```
…or, in the operator console → **Incidents** tab → **Demo data** card → **Seed demo
data** (one click), which then renders the walkthrough inline.

**What it seeds (deterministic):**
- **6 targets across every readiness state** — `ready` ×2, `stale`, `unverified`,
  `auth_failed`, `disabled` — and adapter variety (PagerDuty/Opsgenie rich, Generic,
  Jira outbound-only). States are set from **honest evidence** (the existing
  `compute_readiness` derives them) — the demo never fakes a state.
- **5 incidents spanning the link verdicts** — healthy linked, **drifted** (external
  resolved / local open → offers Refresh + Apply), **missing_external**, **stale**, and a
  recovered/aligned one. Drift backlog = 3.
- **Audit history across the trend windows** — check events, reconciliation events, and
  sync records dated across 24h/7d/30d so the **observability dashboard** shows real
  SLOs (readiness 40%, validation 33%, reconciliation/sync 67%), trend pass rates, and a
  live **`repeated_auth_failures` candidate alert**.

**Safety (every existing guarantee preserved):**
- **Namespaced & non-destructive.** All demo data lives in the `demo.aira-x.local` target
  namespace and the `demo:` incident-signal namespace. Seed/reset touch **only** those
  rows — real operator data and the chat product are never affected (a real target +
  incident provably survive a `reset`).
- **Deterministic & idempotent.** Re-seeding yields the same shape without duplicating;
  same seed → same readiness distribution, drift backlog, and alerts.
- **No network, no side effects.** Rows are inserted directly; nothing calls a real
  adapter transport or the live sweep.
- **Operator-only + opt-out.** Routes are service-key gated and additionally guarded by
  `demo_seed_enabled` (default true; set false in production — `/demo/status` still works
  read-only and reports `enabled: false`).
- Routes: `POST /operator/demo/seed`, `POST /operator/demo/reset`,
  `GET /operator/demo/status` (the seed/status responses carry the guided `tour`).
- Pinned by `backend/tests/test_demo_seed.py` (deterministic scenario shape + readiness
  distribution + drift backlog + alert; attention/drift-recovery; secrets never returned;
  idempotency; **reset removes only the demo namespace, real data survives**; status
  presence; HTTP gating; feature-flag disable) and `frontend/lib/operator.test.mts`
  (`demoSeedSummary`).

### Portfolio & commercial packaging (Phase 7)

Documentation-only — **no business capability changed**. Turns AIRA-X from "an impressive
codebase you have to read" into a repo a recruiter, staff engineer, CTO, or customer can
understand in minutes without a guided explanation:

- **Root `README.md`** rewritten to present both surfaces (user product + operator-grade
  incident-sync/observability platform): overview, why-it-exists, architecture summary
  (Mermaid), feature matrix, screenshots placeholders, operator/incident-sync/
  observability/demo overviews, quickstart, local dev, production deployment, testing,
  architecture principles, roadmap, and a documentation map. Headline metrics up top.
- **`docs/ARCHITECTURE.md`** — system boundaries, component map, and Mermaid diagrams for
  the request / sync / operator / observability flows, deployment topology, plus the
  trust / security / audit models.
- **`docs/ENGINEERING_DECISIONS.md`** — rationale (decision → why → consequence) for the
  load-bearing choices: local-state-is-truth, explicit recovery, capability/policy/profile
  separation, the profile system, the computed readiness model, deterministic metrics, the
  demo namespace, and why inbound sync never mutates local state.
- **`docs/DEMO_WALKTHROUGH.md`** — a deterministic 5–10 min evaluation path (seed →
  readiness → observability → drift recovery → audit → operator separation), matching the
  seeded scenario exactly.
- **`docs/PLATFORM_SUMMARY.md`** — resume-ready metrics + highlights (test counts,
  adapters, operator/observability features, architecture highlights).
- **`docs/screenshots/`** — capture guide + placeholders referenced from the README.
- Pinned by `backend/tests/test_docs_packaging.py` (required docs exist + key sections
  present; README covers every platform surface; ARCHITECTURE has Mermaid + the named
  flows; **every adapter kind in the live registry is documented**; PLATFORM_SUMMARY's
  adapter/profile/operator-route counts match the running system; ENGINEERING_DECISIONS
  covers every required topic; DEMO_WALKTHROUGH covers every evaluation step) and
  `frontend/lib/operator.test.mts` (unchanged). No feature work; all prior guarantees
  preserved.

### Production delivery & OSS professionalization (Phase 8)

Process / infrastructure only — **no product, API, DB, UI, or incident-sync behavior
changed.** Makes the repository look and behave like a platform maintained by a mature
engineering org:

- **OSS governance:** `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `CONTRIBUTING.md`
  (scope, invariants, setup, the test gates, branch strategy, release pointer),
  `SECURITY.md` (responsible disclosure via GitHub Security Advisories + supported
  versions), `LICENSE` (MIT). GitHub issue templates (bug / feature, + a `config.yml`
  routing security to private advisories) and a PR template that checks the platform
  invariants.
- **CI/CD:** the monolithic `ci.yml` is replaced by three focused, parallel workflows —
  `fast-check` (backend + frontend), `e2e` (Playwright), `docs` (packaging +
  professionalization gates). See the **CI** section above.
- **Release management:** `docs/RELEASE_PROCESS.md` (SemVer, release + rollback checklists,
  Keep-a-Changelog process) and `CHANGELOG.md` seeded with `v0.1.0` (the Phase 1–7
  milestone) and an `[Unreleased]` section for this phase.
- **Deployment blueprint:** `docs/DEPLOYMENT_BLUEPRINT.md` — single-VM → docker-compose →
  future-Kubernetes tiers, each covering backend / frontend / worker / database / secrets.
- **Portfolio assets:** `docs/PORTFOLIO_GUIDE.md` (role-based reading orders, a 5-min demo
  script, architecture talking points, interview discussion points) and
  `docs/RESUME_BULLETS.md` (resume / LinkedIn / GitHub-summary bullets).
- Pinned by `backend/tests/test_repo_professionalization.py` (12 tests: OSS files +
  templates exist; CONTRIBUTING covers workflow/release; SECURITY covers disclosure; the
  three workflows exist and run the real gates; `ci.yml` is gone; release/changelog,
  deployment-blueprint tiers+components, and portfolio assets all present) — the same
  "process can't silently disappear" philosophy as Phase 7.

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
