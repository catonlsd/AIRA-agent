from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    # Durable scope owner (account:<id> / workspace:<id> / session) so a document
    # collection can be listed per scope (retrieval is already owner-scoped in the
    # vector store). Nullable for legacy rows / self-healing migration.
    owner: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    vector_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)

    document: Mapped[Document] = relationship(back_populates="chunks")


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, index=True)


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class Account(Base):
    """A durable human account — the authenticated identity that owns resources.

    The product is moving from session-scoped ownership ("this browser owns the
    data") toward account-scoped ownership ("this account owns the data, across
    devices"). `workspace_id` is reserved now so team/workspace ownership can be
    added later without a migration or a rewrite of the owner-scoped call sites.
    """

    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Reserved for future team/workspace ownership (NULL = personal scope today).
    workspace_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class ActivityEvent(Base):
    """A meaningful, user-facing product event (NOT a raw trace).

    One row per noteworthy thing that happened in a scope — an artifact created,
    a document uploaded, a run completed/failed, a workspace member added. Stored
    durably and scope-owned (`owner` = account:<id> / workspace:<id> / session) so
    a calm "recent activity" surface can answer "what happened lately, and who did
    it?" without exposing tool payloads, stack traces, or trace dumps. Operator
    diagnostics stay in the separate ops logs.
    """

    __tablename__ = "activity_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    actor_account_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    type: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, index=True)


class PinnedItem(Base):
    """A small, durable, scope-owned pin that keeps important work easy to find.

    One row per (owner, ref_type, ref_id) — a reference plus a clean display
    title, NEVER a copy of the underlying resource payload. Scope-owned (`owner` =
    account:<id> / workspace:<id> / session) so pins list by the active scope and
    respect the same boundaries as artifacts/documents/runs. The referenced
    resource stays the single source of truth; a pin is just a durable shortcut.
    """

    __tablename__ = "pinned_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    ref_type: Mapped[str] = mapped_column(String(24), index=True, nullable=False)  # artifact|run|document
    ref_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, index=True)


class ExecutionJob(Base):
    """A durable unit of background work — the queue/worker backbone.

    Long-running or expensive work (artifact generation today; execution / repair
    loops later) is recorded here so it survives client disconnect and process
    pressure, can be claimed by a worker out-of-request, and exposes reconnect-safe
    status. Scope-owned (`owner` = account:<id> / workspace:<id> / session) so jobs
    inherit the same access boundaries as runs and artifacts. `payload_json` holds
    a clean work spec (references, not user blobs); `result_json` holds a clean,
    UI-ready outcome (title / download / error) — never raw internals.

    `status` drives the lifecycle: queued -> running -> (validating / repairing) ->
    completed | failed, with awaiting_approval and cancel_requested / canceled
    reserved so cancellation, retry, and replay layer on without a schema change.
    `dedup_key` makes enqueue idempotent (a duplicate approval can't double-queue);
    a worker claims a job with a single guarded UPDATE, so it can only run once.
    """

    __tablename__ = "execution_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    actor_account_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    # Scheduling policy (internal — never surfaced in the user UI): the execution
    # class shapes concurrency, `priority` drives priority-aware claiming (higher
    # first; created_at FIFO breaks ties).
    exec_class: Mapped[str | None] = mapped_column(String(24), index=True, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    progress: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedup_key: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Lineage for honest retry / operator replay: the job this one re-runs, and
    # whether it's a user "retry" of a failed job or an operator "replay". None =
    # an original job. Lets the system answer "was this a retry?" without guessing.
    parent_job_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    origin: Mapped[str | None] = mapped_column(String(16), nullable=True)  # retry | replay
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ObservabilityEvent(Base):
    """A curated, durable operational signal for external monitoring / export.

    Distinct from user-facing `activity_events` (the calm product summary) and from
    raw traces (per-turn debug JSONL): this is the operator-only ops stream — a
    bounded, append-only record of meaningful job lifecycle transitions
    (queued/claimed/completed/failed/canceled/retrying/replayed) plus a summarized
    failure class and lineage ids. The integer primary key is a monotonic cursor,
    so an external dashboard/alerting system polls `?since=<id>` for incremental
    export without scraping the DB. Never carries prompts, tool payloads, trace
    blobs, secrets, or raw owner keys — only safe, ops-useful identifiers.
    """

    __tablename__ = "observability_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, index=True)
    event_type: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    job_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    origin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    scope_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    scope_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    failure_class: Mapped[str | None] = mapped_column(String(60), nullable=True)
    parent_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ContextBundle(Base):
    """A durable, scope-owned "handoff pack" — a saved combination of context
    references (documents, artifacts, runs) that can be reloaded into chat later.

    Stores only REFERENCES (`items_json` = a list of {ref_type, ref_id, title}),
    never the underlying payloads, so the resources stay the single source of
    truth and access is re-checked at load time. Scope-owned (`owner` =
    account:<id> / workspace:<id> / session) so a personal pack stays personal and
    a workspace pack is shared with authorized members.
    """

    __tablename__ = "context_bundles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    items_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, index=True)


class Workspace(Base):
    """A durable shared scope that can own resources alongside personal accounts.

    Foundation only: a workspace has an owner account and a name. Resources tagged
    with owner `workspace:<id>` are shared within the workspace; personal data
    stays `account:<id>`. Membership lives in `WorkspaceMember`, so adding real
    members/roles later is a row insert, not a schema or call-site rewrite.
    """

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_account_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class WorkspaceMember(Base):
    """An account's membership in a workspace (the access-check home).

    The owner is auto-added as a member with role "owner". Roles are a plain
    string today (owner/member) so role-based access can be layered on later
    without changing the membership shape.
    """

    __tablename__ = "workspace_members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    account_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="member", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class MemoryEntry(Base):
    """Owner-scoped, durable memory (preference memory).

    Distinct from the legacy global `UserPreference`: every entry is tagged with
    the owning principal, so preference memory respects the same ownership
    boundaries as guided flows, artifacts, and document retrieval. One row per
    (owner, category, key); `category` keeps memory classes separable
    (`preference` today; room for more later without a schema change).
    """

    __tablename__ = "memory_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class GuidedFlow(Base):
    """Durable, multi-process-safe pending state for guided flows.

    One row per (session_key, kind) pending step — plan / runtime-action /
    artifact approval, or clarification follow-up. The `status` column is the
    idempotency marker: a single atomic UPDATE from "pending" to "consumed"
    claims the flow, so a resume can only ever run once across processes.
    """

    __tablename__ = "guided_flows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_key: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)


class UsageRecord(Base):
    """Durable, principal-scoped usage events for windowed quotas.

    One row per quota-counted action (execution start, artifact generation,
    startup validation). Counting rows newer than (now - window) gives a
    multi-process-safe rate window without external infra.
    """

    __tablename__ = "usage_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, index=True)
