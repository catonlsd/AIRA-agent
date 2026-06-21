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


class WebhookDestination(Base):
    """An operator-configured external delivery target (start: webhook).

    Operator-only: where curated observability events / alert-worthy policy results
    are POSTed. `secret` signs the payload (HMAC) and is NEVER returned by read
    APIs. `subscription` selects events / alerts / both; `min_severity` and
    `event_filter` give bounded routing. Disabled destinations receive nothing.
    """

    __tablename__ = "webhook_destinations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), default="webhook")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    subscription: Mapped[str] = mapped_column(String(16), default="alerts")  # events|alerts|both
    min_severity: Mapped[str] = mapped_column(String(16), default="warning")  # warning|critical
    event_filter: Mapped[str | None] = mapped_column(String(255), nullable=True)  # comma list, optional
    # Routing policy (F-10): a comma list of allowed alert CLASSIFICATIONS
    # (retry_exhausted/stuck/backlog_pressure/…); a comma list of allowed event
    # ORIGINS (normal/retry/replay); and a per-destination suppression window for
    # repeated identical alerts (NULL = use the global default). All operator-only.
    alert_filter: Mapped[str | None] = mapped_column(String(255), nullable=True)
    origin_filter: Mapped[str | None] = mapped_column(String(64), nullable=True)
    suppress_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Escalation policy (F-11): an escalation target fires only once a matching
    # condition has persisted >= `escalate_after` detections (None/0 = a primary
    # that fires on the first occurrence). Bounded by an occurrence count, never an
    # uncontrolled fan-out. `stat_*` are durable routing counters for analytics
    # (suppressed alerts create no delivery, so these are the only durable record).
    escalate_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stat_routed: Mapped[int] = mapped_column(Integer, default=0)
    stat_suppressed: Mapped[int] = mapped_column(Integer, default=0)
    stat_skipped: Mapped[int] = mapped_column(Integer, default=0)
    # Delivery-control policy (F-12): a per-destination DELIVERY retry budget
    # override (None = the adapter default, else the global default — never job
    # retry/replay); and bounded health/cooldown state. `consecutive_failures`
    # counts terminal delivery failures since the last success; once it crosses the
    # threshold the destination is put in `cooldown_until` (time-bounded), during
    # which routing skips it honestly (never a fake "delivered"). A success resets.
    max_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    secret: Mapped[str | None] = mapped_column(String(255), nullable=True)  # signs payloads; never returned
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class WebhookDelivery(Base):
    """A durable delivery record for one (destination, source signal) pair.

    Separate from job retry / replay: `attempts` is the DELIVERY retry counter,
    bounded by `webhook_max_attempts`. `status` runs pending -> delivered | failed
    (terminal). `dedup_key` makes alert routing idempotent (a stuck job doesn't
    deliver every sweep). `payload_json` is the curated, correlation-friendly body
    that was/will be POSTed — never prompts, tool payloads, traces, or secrets.
    """

    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    destination_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)  # observability|alert
    source_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending|delivered|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(120), nullable=True)  # error CLASS, not body
    dedup_key: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    # Operator redrive lineage: the terminal-failed delivery this attempt re-drives
    # (None = an original delivery). A redrive is a NEW row, so source/destination
    # correlation is preserved and "already redriven" is just a child lookup.
    redrive_of: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class AlertOccurrence(Base):
    """Durable per-signal occurrence counter for repeated-condition escalation.

    Keyed by the alert signal (`classification:subject`). Each routing sweep that
    still sees a condition bumps `count`; a gap longer than the resolve window
    starts a fresh episode (count resets), so escalation reflects a *persisting*
    problem, not a one-off. Lets an escalation destination fire only after the
    condition has been detected N times — bounded and honest about resolution.
    """

    __tablename__ = "alert_occurrences"

    signal: Mapped[str] = mapped_column(String(160), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=1)
    last_severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class OperatorIncident(Base):
    """A durable operator workflow record for a recurring operational condition.

    Operator-only — distinct from delivery suppression, destination cooldown, and
    dead-letter state. Keyed by the alert SIGNAL (`classification:subject`), so one
    incident tracks one recurring condition across sweeps. State runs
    open → acknowledged / silenced → recovered (and reopens honestly if a recovered
    or silence-expired condition recurs). `silenced_until` is always BOUNDED — a
    silenced incident still exists in operator state (never a black hole) and gates
    only *alert routing* for its signal, never delivery/execution truth.
    """

    __tablename__ = "operator_incidents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    signal: Mapped[str] = mapped_column(String(160), unique=True, index=True, nullable=False)
    classification: Mapped[str | None] = mapped_column(String(48), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="alert")
    state: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open|acknowledged|silenced|recovered
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[str | None] = mapped_column(String(280), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    silenced_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recovered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Collaboration (G-4): a single current owner + when they took it. The assignee
    # is an operator-declared handle (service-key auth has no real named identity),
    # bounded and operator-only — never a verified account.
    assignee: Mapped[str | None] = mapped_column(String(80), nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, index=True)


class OperatorIncidentEvent(Base):
    """A curated, append-only action-trail entry for an operator incident (G-4).

    One row per meaningful workflow transition — opened / acknowledged / silenced /
    unsilenced / recovered / reopened / assigned / unassigned / reassigned /
    note_updated — so a relieving operator can read what already happened on a
    shift handoff instead of relying on out-of-band memory. The integer primary key
    is monotonic, giving a stable chronological order even within one timestamp.
    Operator-only and deliberately small: a brief `detail` (note text / new
    assignee / silence-until), the resulting `state`, and the operator-declared
    `actor` if one was supplied — never payloads, traces, secrets, or raw owners.
    """

    __tablename__ = "operator_incident_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(80), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(280), nullable=True)
    state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, index=True)


class ExternalIncidentTarget(Base):
    """An operator-configured OUTBOUND destination for incident export/sync (G-5).

    Deliberately separate from `webhook_destinations` (event/alert routing): an
    incident target mirrors operator *incident* transitions (opened / acknowledged /
    assigned / recovered / …) to an external incident or ticket tool, one-way. The
    `secret` is stored for HMAC signing but NEVER returned by read APIs (only
    `has_secret`). `sync_actions` is an optional CSV allow-list of which transitions
    to mirror (empty = all). Operator-only; no user-facing surface.
    """

    __tablename__ = "external_incident_targets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), default="generic")  # generic|pagerduty|… (adapter-ready)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sync_actions: Mapped[str | None] = mapped_column(String(255), nullable=True)  # CSV allow-list; null = all
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    # Per-target action policy overrides (G-12). Tri-state: NULL = defer to the
    # adapter capability default; True = explicitly permitted (still bounded by
    # capability); False = explicitly denied for THIS target even if the adapter can.
    # An override can never enable beyond capability — only narrow it.
    allow_apply_resolved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    allow_apply_missing: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    allow_external_resolve: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    allow_external_reopen: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    allow_external_acknowledge: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    allow_push_outward: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Per-target INBOUND-state overrides (G-13). Same tri-state: NULL = adapter
    # default (visible if the adapter can normalize it), True = permitted, False =
    # hidden for THIS target. Refresh stores only permitted fields; reads mask the
    # rest. Never reveals beyond adapter capability.
    allow_external_assignee: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    allow_external_severity: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    allow_external_updated_at: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    allow_external_comment_count: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    allow_external_suggestions: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, onupdate=_utc_now)


class IncidentSyncRecord(Base):
    """A durable, curated record of one incident transition exported to one target.

    Correlates back to the source incident (`incident_id` / `signal`) and snapshots
    the curated incident fields at sync time — state, severity, classification,
    subject, assignee, and a short note summary — so the external payload is stable
    and never carries raw payloads/traces/secrets/owners. Status runs
    pending → synced | failed; `attempts` is bounded by `incident_sync_max_attempts`,
    and a terminal-failed record can be operator-redriven (a fresh record linked via
    `redrive_of`, bounded by `incident_sync_max_redrives`). Operator-only.
    """

    __tablename__ = "incident_sync_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    target_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    incident_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    signal: Mapped[str | None] = mapped_column(String(160), nullable=True)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(80), nullable=True)
    state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    classification: Mapped[str | None] = mapped_column(String(48), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(120), nullable=True)
    assignee: Mapped[str | None] = mapped_column(String(80), nullable=True)
    note: Mapped[str | None] = mapped_column(String(280), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending|synced|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    redrive_of: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, onupdate=_utc_now)


class IncidentExternalLink(Base):
    """The durable correlation AIRA-X incident → external incident, per target (G-6).

    Upserted on every *successful* outbound sync: it holds the latest stable
    external reference (`external_ref`) and, when the adapter could safely obtain
    one, an `external_url` to open the linked incident. One row per
    (incident_id, target_id) — so "is this incident linked, and where?" is a single
    cheap read, independent of how many sync records exist. A failed sync never
    overwrites a good link (the link reflects the last success; staleness is derived
    by comparing it to the most recent sync record). Operator-only; outbound-only —
    AIRA-X never claims to read external state back.
    """

    __tablename__ = "incident_external_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_action: Mapped[str | None] = mapped_column(String(24), nullable=True)
    last_record_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Bounded inbound reconciliation (G-7): what the last refresh/check observed
    # externally. Outbound stays primary — these only *describe* external state.
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    external_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    external_exists: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Richer BOUNDED inbound snapshot (G-10) — only for adapters that support status
    # sync. Strictly normalized + size-bounded; NEVER raw vendor payloads/comments.
    external_assignee: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_severity: Mapped[str | None] = mapped_column(String(24), nullable=True)
    external_updated_at: Mapped[str | None] = mapped_column(String(40), nullable=True)  # vendor ISO string, bounded
    external_comment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Drift resolution (G-8): an operator may intentionally detach a bad/missing link.
    # A detached link is preserved (lineage) but excluded from drift/reconciliation.
    detached_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, onupdate=_utc_now)


class IncidentReconciliationEvent(Base):
    """A curated, append-only record of an operator drift-resolution action (G-8).

    One row per repair/maintenance action on an incident↔external link — refresh /
    redrive / detach / relink / reconcile — capturing the outcome
    (ok / failed / unsupported / missing / skipped) and a brief detail. The monotonic
    integer PK gives stable chronological order. This is what answers "was a repair
    attempted, and did it work?" durably, without dumping payloads/secrets. Local
    incident state is never mutated by these actions — they only act on linkage.
    """

    __tablename__ = "incident_reconciliation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(80), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, index=True)


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
