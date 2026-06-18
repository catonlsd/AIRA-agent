# File: backend/app/operator_inspect.py
"""
Operator inspection — curated, support-safe views over the execution stores.

Today the data needed to diagnose a run lives in four disconnected places: the
durable `execution_jobs` table, the per-turn trace JSONL, the `activity_events`
log, and the retry/replay lineage encoded in job columns. An operator diagnosing a
stuck / failed / canceled / retried job would otherwise have to SQL the DB, grep
the trace file, and cross-reference owner keys by hand.

This service is the seam that correlates them into ONE curated inspection model —
`OperatorJobView` / `OperatorRunView` / `OperatorTimeline`. It is operator-only by
construction (the routes gate on the service principal) and deliberately NOT a raw
dump: it summarizes failure *class* (not stack traces), exposes lineage (this
failed job was retried into X / replayed from Y), links artifacts as safe
references, and orders lifecycle + activity + trace stages into a readable
timeline. It is strictly separate from the user-facing activity layer, which stays
the minimal summary — operators get richer detail here, users never see it.

Operators are trusted, so these views may include scope/owner/actor context and
queue internals (exec_class, priority, dedup_key) that NEVER appear in normal
product APIs. Raw prompt payloads, full tool dumps, and unbounded trace blobs stay
out even here.
"""

from __future__ import annotations

from typing import Any, Optional

from app.db.database import SessionLocal
from app.db.models import ExecutionJob
from app.live_status import job_phase

# Friendly, operator-readable run labels (task/result oriented, not raw modes).
_RUN_LABELS = {
    "general_chat": "Conversation",
    "self_memory": "Conversation",
    "web_research": "Web research",
    "document_qa": "Document answer",
    "execution": "Workflow run",
    "execution_planning": "Plan prepared",
    "research_then_execution": "Research & build",
    "multi_question": "Multi-task",
    "clarification": "Clarification",
}

# Activity types that correlate meaningfully onto a job/run timeline.
_TIMELINE_ACTIVITY = [
    "artifact_created", "artifact_failed", "run_completed", "run_failed",
    "run_canceled", "run_retrying", "validation_passed", "validation_failed",
    "startup_verified", "startup_failed",
]

_TERMINAL = {"completed", "failed", "canceled"}


def _scope_of(owner: Optional[str]) -> dict[str, Optional[str]]:
    """Operator scope context: account / workspace / session — derived from the
    owner key, never the raw durable key passed through verbatim."""
    if not owner:
        return {"type": "unknown", "id": None}
    if owner.startswith("account:"):
        return {"type": "account", "id": owner.split(":", 1)[1]}
    if owner.startswith("workspace:"):
        return {"type": "workspace", "id": owner.split(":", 1)[1]}
    return {"type": "session", "id": None}  # raw session id is not operator-useful


def _actor(actor_account_id: Optional[str]) -> Optional[dict[str, Any]]:
    if not actor_account_id:
        return None
    try:
        from app.accounts import account_service

        account = account_service.get(actor_account_id)
        name = account.get("display_name") if account else None
    except Exception:
        name = None
    return {"account_id": actor_account_id, "display_name": name}


def _failure_class(result: Any) -> Optional[str]:
    """Summarize the failure CLASS (e.g. 'RuntimeError') from a clean result —
    never the full message or a stack trace."""
    if not isinstance(result, dict):
        return None
    error = result.get("error")
    if not isinstance(error, str) or not error:
        return None
    return error.split(":", 1)[0].strip()[:60]


def _severity(status: str) -> str:
    if status == "failed":
        return "bad"
    if status in ("canceled", "cancel_requested", "repairing"):
        return "warn"
    if status == "completed":
        return "good"
    return "info"


class SupportInspectionService:
    def __init__(self, session_factory=SessionLocal) -> None:
        self._session_factory = session_factory

    # ── jobs ──────────────────────────────────────────────────────────────────

    def _row(self, session, job_id: str) -> Optional[ExecutionJob]:
        return session.get(ExecutionJob, job_id)

    def _children(self, session, job_id: str, origin: str) -> list[str]:
        rows = (
            session.query(ExecutionJob.id)
            .filter(ExecutionJob.parent_job_id == job_id, ExecutionJob.origin == origin)
            .order_by(ExecutionJob.created_at.asc())
            .all()
        )
        return [r[0] for r in rows]

    def _result(self, row: ExecutionJob) -> Any:
        import json
        if not row.result_json:
            return None
        try:
            return json.loads(row.result_json)
        except (TypeError, ValueError):
            return None

    def job_view(self, job_id: str) -> Optional[dict[str, Any]]:
        """Curated operator view of one job — summary, lineage, safe result refs."""
        with self._session_factory() as session:
            row = self._row(session, job_id)
            if row is None:
                return None
            result = self._result(row)
            artifact = None
            if isinstance(result, dict) and result.get("download_url"):
                artifact = {
                    "title": result.get("title"),
                    "filename": result.get("filename"),
                    "download_url": result.get("download_url"),
                }
            return {
                "job_id": row.id,
                "kind": row.kind,
                "status": row.status,
                "phase": job_phase(row.status, origin=row.origin),
                "exec_class": row.exec_class,
                "priority": row.priority,
                "title": row.title,
                "scope": _scope_of(row.owner),
                "actor": _actor(row.actor_account_id),
                "attempts": row.attempts,
                "dedup_key": row.dedup_key,
                "run_id": row.run_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                "lineage": {
                    "origin": row.origin,                       # null | retry | replay
                    "parent_job_id": row.parent_job_id,
                    "retried_into": self._children(session, row.id, "retry"),
                    "replayed_into": self._children(session, row.id, "replay"),
                },
                "result_summary": {
                    "outcome": row.status if row.status in _TERMINAL else "pending",
                    "failure_class": _failure_class(result),
                    "artifact": artifact,                       # safe reference only
                },
                # Queued artifact approval is consumed BEFORE enqueue, so a queued
                # job never itself awaits approval — honest, not a guess.
                "approval": {"required": False, "consumed_before_enqueue": row.kind == "artifact"},
            }

    def job_timeline(self, job_id: str) -> Optional[list[dict[str, Any]]]:
        """A curated, ordered 'what happened' for a job: lifecycle + correlated
        activity + lineage — never a raw log concatenation."""
        with self._session_factory() as session:
            row = self._row(session, job_id)
            if row is None:
                return None
            owner, origin = row.owner, row.origin
            created = row.created_at.isoformat() if row.created_at else None
            started = row.started_at.isoformat() if row.started_at else None
            finished = row.finished_at.isoformat() if row.finished_at else None
            status = row.status
            retried = self._children(session, row.id, "retry")
            replayed = self._children(session, row.id, "replay")
            parent = row.parent_job_id

        events: list[dict[str, Any]] = []
        enqueue_label = "Queued"
        if origin == "retry":
            enqueue_label = f"Queued as a retry of {parent}"
        elif origin == "replay":
            enqueue_label = f"Queued as a replay of {parent}"
        events.append({"at": created, "state": "queued", "label": enqueue_label, "severity": "info"})
        if started:
            events.append({"at": started, "state": "running", "label": "Claimed by a worker", "severity": "info"})

        # Correlated user-scope activity (already curated/clean) within the window.
        for ev in self._activity_in_window(owner, created, finished):
            events.append({
                "at": ev.get("created_at"), "state": ev.get("type"),
                "label": ev.get("title"), "severity": "warn" if ev.get("severity") == "warn" else "info",
            })

        if finished:
            term = {"completed": "Completed", "failed": "Could not complete", "canceled": "Canceled"}.get(status, status)
            events.append({"at": finished, "state": status, "label": term, "severity": _severity(status)})
        for child in retried:
            events.append({"at": finished, "state": "retried", "label": f"Retried into {child}", "severity": "info"})
        for child in replayed:
            events.append({"at": finished, "state": "replayed", "label": f"Replayed into {child}", "severity": "info"})

        events.sort(key=lambda e: (e.get("at") or ""))
        return events

    def list_jobs(
        self, *, status: Optional[str] = None, origin: Optional[str] = None,
        kind: Optional[str] = None, failures: bool = False, limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Minimal operator query to FIND the right job — not an admin console."""
        with self._session_factory() as session:
            query = session.query(ExecutionJob)
            if failures:
                query = query.filter(ExecutionJob.status == "failed")
            elif status:
                query = query.filter(ExecutionJob.status == status)
            if origin == "normal":
                query = query.filter(ExecutionJob.origin.is_(None))
            elif origin:
                query = query.filter(ExecutionJob.origin == origin)
            if kind:
                query = query.filter(ExecutionJob.kind == kind)
            rows = query.order_by(ExecutionJob.created_at.desc()).limit(min(limit, 100)).all()
            return [{
                "job_id": r.id,
                "kind": r.kind,
                "status": r.status,
                "origin": r.origin,
                "scope": _scope_of(r.owner),
                "title": r.title,
                "failure_class": _failure_class(self._result(r)),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            } for r in rows]

    # ── runs (inline / trace world) ───────────────────────────────────────────

    def _trace_for(self, run_id: str) -> Optional[dict[str, Any]]:
        try:
            from app.services.trace_service import TraceService

            for record in reversed(TraceService().recent(limit=500)):
                if record.get("run_id") == run_id:
                    return record
        except Exception:
            return None
        return None

    def run_view(self, run_id: str) -> Optional[dict[str, Any]]:
        record = self._trace_for(run_id)
        if record is None:
            return None
        mode = record.get("mode") or ""
        stages = [e.get("stage") for e in record.get("trace_events", [])
                  if isinstance(e, dict) and e.get("event") == "stage" and e.get("stage")]
        return {
            "run_id": run_id,
            "label": _RUN_LABELS.get(mode, "Run"),
            "status": record.get("final_status") or "completed",
            "source_type": record.get("source_type"),
            "scope": _scope_of(record.get("owner")),
            "created_at": record.get("created_at"),
            "latency_ms": record.get("latency_ms"),
            "stages": stages,  # curated stage names only — no raw event payloads
        }

    def run_timeline(self, run_id: str) -> Optional[list[dict[str, Any]]]:
        record = self._trace_for(run_id)
        if record is None:
            return None
        created = record.get("created_at")
        events: list[dict[str, Any]] = [
            {"at": created, "state": "started", "label": "Turn started", "severity": "info"}
        ]
        for e in record.get("trace_events", []):
            if not isinstance(e, dict):
                continue
            if e.get("event") == "stage" and e.get("stage"):
                events.append({"at": created, "state": "stage", "label": str(e["stage"]), "severity": "info"})
        status = record.get("final_status") or "completed"
        events.append({"at": created, "state": status,
                       "label": "Completed" if status == "completed" else status,
                       "severity": _severity(status)})
        # Correlate the owner's activity around the run.
        for ev in self._activity_in_window(record.get("owner"), created, None):
            events.append({"at": ev.get("created_at"), "state": ev.get("type"),
                           "label": ev.get("title"), "severity": "warn" if ev.get("severity") == "warn" else "info"})
        events.sort(key=lambda e: (e.get("at") or ""))
        return events

    # ── shared ──────────────────────────────────────────────────────────────

    @staticmethod
    def _activity_in_window(owner: Optional[str], start: Optional[str], end: Optional[str]) -> list[dict[str, Any]]:
        if not owner:
            return []
        try:
            from app.activity import activity_service

            items = activity_service.recent(owner, limit=25, types=_TIMELINE_ACTIVITY)
        except Exception:
            return []
        out = []
        for ev in items:
            at = ev.get("created_at")
            if start and at and at < start:
                continue
            if end and at and at > end:
                continue
            out.append(ev)
        return out


support_inspection = SupportInspectionService()
