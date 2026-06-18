# File: backend/app/observability.py
"""
Observability export + failure triage — the operator-only ops stream.

Two operator-facing capabilities, both curated (never a raw dump) and strictly
separate from the user-facing activity layer:

  * **Export feed** — a durable, append-only journal of meaningful job lifecycle
    signals (queued / claimed / completed / failed / canceled / retrying /
    replayed) with a summarized failure class and lineage ids. The row id is a
    monotonic cursor, so an external dashboard/alerting backend polls `?since=<id>`
    for incremental export without scraping the DB. `record()` is best-effort and
    NEVER breaks the action it describes.

  * **Triage** — a curated view over terminal-failed jobs that need attention,
    each classified honestly: `retry_exhausted` (bounded internal retries ran out),
    `replay_candidate` (no active retry/replay in flight — an operator could replay
    it), or `resolved` (already retried/replayed into a child). The clean seam for
    a future dead-letter queue, without inventing one now.

Every payload carries only safe, ops-useful identifiers (event type, ts, job/run
ids, origin, scope type + id, status, failure class, lineage) — never prompts,
tool payloads, trace blobs, secrets, or raw owner keys.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from app.core.config import settings
from app.db.database import Base, SessionLocal, engine
from app.db.models import ExecutionJob, ObservabilityEvent

# Curated operational signal types (not raw trace events).
EVT_QUEUED = "job_queued"
EVT_CLAIMED = "job_claimed"
EVT_COMPLETED = "job_completed"
EVT_FAILED = "job_failed"
EVT_CANCELED = "job_canceled"
EVT_RETRYING = "job_retrying"
EVT_REPLAYED = "job_replayed"

_ACTIVE = {"queued", "running", "awaiting_approval", "validating", "repairing", "cancel_requested"}


def scope_of(owner: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """(scope_type, scope_id) from an owner key — never the raw key verbatim."""
    if not owner:
        return ("unknown", None)
    if owner.startswith("account:"):
        return ("account", owner.split(":", 1)[1])
    if owner.startswith("workspace:"):
        return ("workspace", owner.split(":", 1)[1])
    return ("session", None)


def failure_class_of(result: Any) -> Optional[str]:
    """The failure CLASS (e.g. 'RuntimeError') — never the full message/stack."""
    if not isinstance(result, dict):
        return None
    error = result.get("error")
    if not isinstance(error, str) or not error:
        return None
    return error.split(":", 1)[0].strip()[:60]


class ObservabilityExportService:
    def __init__(self, session_factory: Callable[[], Any] = SessionLocal) -> None:
        self._session_factory = session_factory
        self._ensure_table()

    def _ensure_table(self) -> None:
        try:
            ObservabilityEvent.__table__.create(bind=engine, checkfirst=True)
        except Exception:
            Base.metadata.create_all(bind=engine)

    # ── record (best-effort; never raises) ────────────────────────────────────

    def record(
        self,
        event_type: str,
        *,
        owner: Optional[str] = None,
        job_id: Optional[str] = None,
        run_id: Optional[str] = None,
        kind: Optional[str] = None,
        origin: Optional[str] = None,
        status: Optional[str] = None,
        failure_class: Optional[str] = None,
        parent_job_id: Optional[str] = None,
        title: Optional[str] = None,
    ) -> None:
        try:
            scope_type, scope_id = scope_of(owner)
            with self._session_factory() as session:
                row = ObservabilityEvent(
                    event_type=event_type, job_id=job_id, run_id=run_id, kind=kind,
                    origin=origin, scope_type=scope_type, scope_id=scope_id,
                    status=status, failure_class=failure_class,
                    parent_job_id=parent_job_id, title=(title[:255] if title else None),
                )
                session.add(row)
                session.commit()
                clean = self._clean(row)
        except Exception:
            return  # observability must never break execution
        # Best-effort fan-out to external destinations subscribed to events. A
        # delivery failure can never affect the source path (own session, guarded).
        try:
            from app.webhooks import delivery_service

            delivery_service.route_observability(clean)
        except Exception:
            pass

    # ── export feed (cursor-based, bounded, curated) ──────────────────────────

    def recent(
        self, *, since: Optional[int] = None, limit: int = 100, types: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """A bounded slice of the ops stream for export. `since` is the last id an
        external consumer saw; the response carries the new `cursor` to poll next."""
        limit = max(1, min(int(limit), 500))
        try:
            with self._session_factory() as session:
                query = session.query(ObservabilityEvent)
                if since is not None:
                    query = query.filter(ObservabilityEvent.id > int(since))
                if types:
                    query = query.filter(ObservabilityEvent.event_type.in_(types))
                rows = query.order_by(ObservabilityEvent.id.asc()).limit(limit).all()
        except Exception:
            return {"events": [], "cursor": since or 0}
        events = [self._clean(r) for r in rows]
        cursor = events[-1]["id"] if events else (since or 0)
        return {"events": events, "cursor": cursor}

    # ── triage (terminal failed jobs needing attention) ───────────────────────

    def triage(self, *, limit: int = 25) -> list[dict[str, Any]]:
        """Curated terminal-failed jobs, classified honestly. The dead-letter seam."""
        limit = max(1, min(int(limit), 100))
        try:
            with self._session_factory() as session:
                failed = (
                    session.query(ExecutionJob)
                    .filter(ExecutionJob.status == "failed")
                    .order_by(ExecutionJob.created_at.desc())
                    .limit(limit)
                    .all()
                )
                out: list[dict[str, Any]] = []
                for row in failed:
                    children = (
                        session.query(ExecutionJob)
                        .filter(ExecutionJob.parent_job_id == row.id)
                        .all()
                    )
                    has_active_followup = any(c.status in _ACTIVE for c in children)
                    has_resolved_followup = any(c.status == "completed" for c in children)
                    classification = self._classify(row, has_active_followup, has_resolved_followup)
                    scope_type, scope_id = scope_of(row.owner)
                    out.append({
                        "job_id": row.id,
                        "kind": row.kind,
                        "origin": row.origin,
                        "classification": classification,
                        "attempts": row.attempts,
                        "failure_class": failure_class_of(self._result(row)),
                        "scope": {"type": scope_type, "id": scope_id},
                        "title": row.title,
                        "retried_into": [c.id for c in children if c.origin == "retry"],
                        "replayed_into": [c.id for c in children if c.origin == "replay"],
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                    })
                return out
        except Exception:
            return []

    @staticmethod
    def _classify(row: ExecutionJob, has_active_followup: bool, has_resolved_followup: bool) -> str:
        if has_resolved_followup:
            return "resolved"            # a retry/replay already succeeded
        if has_active_followup:
            return "in_progress"         # a retry/replay is in flight
        if row.attempts >= max(1, settings.job_max_attempts):
            return "retry_exhausted"     # bounded internal retries are spent
        return "replay_candidate"        # safe to retry/replay — needs attention

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _result(row: ExecutionJob) -> Any:
        import json
        if not row.result_json:
            return None
        try:
            return json.loads(row.result_json)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clean(row: ObservabilityEvent) -> dict[str, Any]:
        return {
            "id": row.id,                # the cursor
            "event_type": row.event_type,
            "at": row.created_at.isoformat() if row.created_at else None,
            "job_id": row.job_id,
            "run_id": row.run_id,
            "kind": row.kind,
            "origin": row.origin,
            "scope": {"type": row.scope_type, "id": row.scope_id},
            "status": row.status,
            "failure_class": row.failure_class,
            "parent_job_id": row.parent_job_id,
            "title": row.title,
        }

    def clear_all(self) -> None:
        try:
            with self._session_factory() as session:
                session.query(ObservabilityEvent).delete()
                session.commit()
        except Exception:
            pass


observability = ObservabilityExportService()
