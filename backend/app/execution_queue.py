# File: backend/app/execution_queue.py
"""
Durable execution queue — the production backbone for long-running work.

A small, DB-backed queue so heavy work (artifact generation today; execution /
repair loops later) is durably scheduled, survives client disconnect, and runs
out-of-request on a worker. Deliberately staged: one clean interface over the
existing SQLAlchemy/SQLite engine, with a single-`UPDATE` atomic claim (the same
idempotency primitive proven by the guided-flow store), so it swaps for
Redis/RQ/Arq/Celery later without touching call sites.

Guarantees that matter here:
  * **idempotent enqueue** — a `dedup_key` (e.g. the approved flow's run id) means
    a duplicate approval can't double-queue the same work.
  * **single execution** — `claim()` flips exactly one row queued -> running via a
    guarded UPDATE; SQLite serializes writers, so two workers can't both win.
  * **honest failure + bounded retry** — a handler error re-queues up to
    `job_max_attempts`, then records an honest `failed` with a clean message.
  * **scope-owned** — every job carries its owner key, so status/cancel inherit
    the same access boundaries as runs and artifacts. Reads are UI-ready only.

Handlers are registered per `kind`; the worker (`app/worker.py`) just drains the
queue by calling `run_once()`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from uuid import uuid4

from sqlalchemy import update

from app import job_policy
from app.core.config import settings
from app.db.database import Base, SessionLocal, engine
from app.db.models import ExecutionJob

# ── lifecycle states ─────────────────────────────────────────────────────────
QUEUED = "queued"
RUNNING = "running"
AWAITING_APPROVAL = "awaiting_approval"
VALIDATING = "validating"
REPAIRING = "repairing"
COMPLETED = "completed"
FAILED = "failed"
CANCEL_REQUESTED = "cancel_requested"
CANCELED = "canceled"

_ACTIVE = {QUEUED, RUNNING, AWAITING_APPROVAL, VALIDATING, REPAIRING, CANCEL_REQUESTED}
_TERMINAL = {COMPLETED, FAILED, CANCELED}
# A running job can be asked to stop; a queued one cancels outright.
_INTERRUPTIBLE = {RUNNING, VALIDATING, REPAIRING, AWAITING_APPROVAL}
# Only a terminally-failed job is user-retryable (cancellation/completion aren't).
_RETRYABLE = {FAILED}

# A handler runs a job and returns (result_dict, title) or raises on failure.
JobHandler = Callable[["JobView"], dict[str, Any]]


class JobCanceled(Exception):
    """Raised by a handler that cooperatively aborts at a safe checkpoint."""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class JobView:
    """A plain, read-only view of a job handed to handlers — no ORM session.

    `cancelled()` lets a handler cooperatively check for a cancel request at safe
    checkpoints (e.g. before starting expensive generation) and bail by raising
    `JobCanceled`, so cancellation is honest, not a force-kill mid-write."""

    def __init__(self, row: ExecutionJob, service: "ExecutionQueueService" | None = None) -> None:
        self.id = row.id
        self.owner = row.owner
        self.session_id = row.session_id
        self.actor_account_id = row.actor_account_id
        self.kind = row.kind
        self.title = row.title
        self.attempts = row.attempts
        self._service = service
        try:
            self.payload = json.loads(row.payload_json)
        except (TypeError, ValueError):
            self.payload = {}

    def cancelled(self) -> bool:
        return bool(self._service and self._service._is_cancelled(self.id))


class ExecutionQueueService:
    def __init__(self, session_factory: Callable[[], Any] = SessionLocal) -> None:
        self._session_factory = session_factory
        self._handlers: dict[str, JobHandler] = {}
        self._ensure_table()

    def _ensure_table(self) -> None:
        try:
            ExecutionJob.__table__.create(bind=engine, checkfirst=True)
        except Exception:
            Base.metadata.create_all(bind=engine)

    # ── handler registry (swappable per kind) ─────────────────────────────────

    def register_handler(self, kind: str, handler: JobHandler) -> None:
        self._handlers[kind] = handler

    # ── observability emission (best-effort; never affects execution) ─────────

    @staticmethod
    def _emit(event_type: str, **fields: Any) -> None:
        try:
            from app.observability import observability

            observability.record(event_type, **fields)
        except Exception:
            pass

    # ── enqueue (idempotent via dedup_key) ────────────────────────────────────

    def enqueue(
        self,
        owner: str,
        kind: str,
        payload: dict[str, Any],
        *,
        session_id: Optional[str] = None,
        actor_account_id: Optional[str] = None,
        title: Optional[str] = None,
        dedup_key: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        if not owner or not kind:
            return None
        with self._session_factory() as session:
            if dedup_key:
                # Idempotent: an in-flight job with the same key returns as-is, so a
                # duplicate approval can never queue (or run) the same work twice.
                existing = (
                    session.query(ExecutionJob)
                    .filter(
                        ExecutionJob.owner == owner,
                        ExecutionJob.dedup_key == dedup_key,
                        ExecutionJob.status.in_(tuple(_ACTIVE)),
                    )
                    .first()
                )
                if existing is not None:
                    return self._clean(existing)
            exec_class = job_policy.class_for(kind)
            row = ExecutionJob(
                id=uuid4().hex,
                owner=owner,
                session_id=session_id,
                actor_account_id=actor_account_id,
                kind=kind,
                status=QUEUED,
                exec_class=exec_class.name,
                priority=exec_class.priority,
                title=(title or None),
                progress="Queued",
                payload_json=json.dumps(payload or {}),
                dedup_key=dedup_key,
                run_id=run_id,
                attempts=0,
            )
            session.add(row)
            session.commit()
            cleaned = self._clean(row)
        from app.observability import EVT_QUEUED  # local: avoid import cycle
        self._emit(EVT_QUEUED, owner=owner, job_id=cleaned["id"], kind=kind,
                   run_id=run_id, status=QUEUED, title=title)
        return cleaned

    # ── claim (atomic; exactly one worker wins) ───────────────────────────────

    def claim(self) -> Optional[JobView]:
        """Claim the next eligible job. Priority-aware (higher class first, then
        created_at FIFO) and bounded: a class at its concurrency cap or an owner
        already running their fair share is skipped, so nothing monopolises workers
        and nothing starves forever. The claim itself stays a single guarded UPDATE
        (race-safe: exactly one worker wins). Falls back to plain FIFO when
        scheduling is disabled."""
        with self._session_factory() as session:
            query = session.query(ExecutionJob).filter(ExecutionJob.status == QUEUED)
            if job_policy.scheduling_enabled(settings):
                # Count what's currently occupying a worker slot, by class and owner.
                in_flight = (
                    session.query(ExecutionJob.exec_class, ExecutionJob.owner)
                    .filter(ExecutionJob.status.in_(tuple(_INTERRUPTIBLE)))
                    .all()
                )
                class_counts: dict[str, int] = {}
                owner_counts: dict[str, int] = {}
                for exec_class, owner in in_flight:
                    class_counts[exec_class or ""] = class_counts.get(exec_class or "", 0) + 1
                    owner_counts[owner] = owner_counts.get(owner, 0) + 1
                blocked_classes = job_policy.blocked_classes(class_counts, settings)
                blocked_owners = job_policy.blocked_owners(owner_counts, settings)
                if blocked_classes:
                    query = query.filter(
                        (ExecutionJob.exec_class.is_(None))
                        | (ExecutionJob.exec_class.notin_(blocked_classes))
                    )
                if blocked_owners:
                    query = query.filter(ExecutionJob.owner.notin_(blocked_owners))
                query = query.order_by(ExecutionJob.priority.desc(), ExecutionJob.created_at.asc())
            else:
                query = query.order_by(ExecutionJob.created_at.asc())  # plain FIFO

            row = query.first()
            if row is None:
                return None
            now = _now()
            claimed = session.execute(
                update(ExecutionJob)
                .where(ExecutionJob.id == row.id, ExecutionJob.status == QUEUED)
                .values(status=RUNNING, started_at=now, updated_at=now,
                        progress="Working", attempts=ExecutionJob.attempts + 1)
            )
            session.commit()
            if claimed.rowcount != 1:
                return None  # another worker won the race
            row = session.get(ExecutionJob, row.id)
            view = JobView(row, service=self)
        from app.observability import EVT_CLAIMED
        self._emit(EVT_CLAIMED, owner=view.owner, job_id=view.id, kind=view.kind,
                   status=RUNNING, title=view.title)
        return view

    # ── transitions ───────────────────────────────────────────────────────────

    def transition(
        self,
        job_id: str,
        status: str,
        *,
        progress: Optional[str] = None,
        result: Optional[dict[str, Any]] = None,
    ) -> None:
        with self._session_factory() as session:
            row = session.get(ExecutionJob, job_id)
            if row is None:
                return
            # Terminal is terminal: never resurrect a completed/failed/canceled job
            # (guards a worker race from overwriting an honest final state).
            if row.status in _TERMINAL and status != row.status:
                return
            row.status = status
            if progress is not None:
                row.progress = progress
            if result is not None:
                row.result_json = json.dumps(result)
            row.updated_at = _now()
            if status in _TERMINAL:
                row.finished_at = _now()
            session.commit()

    # ── cancellation (honest, cooperative) ────────────────────────────────────

    def request_cancel(self, owner: str, job_id: str) -> dict[str, Any]:
        """Honestly cancel an accessible job. A queued job cancels outright; a
        running one is marked `cancel_requested` and stops at the worker's next
        safe checkpoint. Already-terminal jobs report the truth, never a fake
        cancel. Scope-checked: an inaccessible job is reported not-found."""
        with self._session_factory() as session:
            row = session.get(ExecutionJob, job_id)
            if row is None or row.owner != owner:
                return {"ok": False, "not_found": True, "status": None,
                        "message": "Job not found in this scope."}
            status = row.status
            if status in _TERMINAL:
                return {"ok": False, "status": status,
                        "message": "That job already finished — nothing to cancel."}
            if status == CANCEL_REQUESTED:
                return {"ok": True, "status": CANCEL_REQUESTED,
                        "message": "Cancel already requested — it'll stop at the next safe point."}
            if status == QUEUED:
                row.status = CANCELED
                row.progress = "Canceled"
                row.finished_at = _now()
                row.updated_at = _now()
                kind, title = row.kind, row.title
                session.commit()
                self._record_canceled(owner, row.actor_account_id, title)
                from app.observability import EVT_CANCELED
                self._emit(EVT_CANCELED, owner=owner, job_id=job_id, kind=kind,
                           status=CANCELED, title=title)
                return {"ok": True, "status": CANCELED, "message": "Canceled."}
            # Running / validating / repairing / awaiting_approval -> cooperative.
            row.status = CANCEL_REQUESTED
            row.progress = "Cancel requested"
            row.updated_at = _now()
            session.commit()
            return {"ok": True, "status": CANCEL_REQUESTED,
                    "message": "Cancel requested — stopping at the next safe point."}

    def cancel_request(self, owner: str, job_id: str) -> bool:
        """Back-compat boolean wrapper over `request_cancel`."""
        return bool(self.request_cancel(owner, job_id).get("ok"))

    def _is_cancelled(self, job_id: str) -> bool:
        with self._session_factory() as session:
            row = session.get(ExecutionJob, job_id)
            return bool(row and row.status in (CANCEL_REQUESTED, CANCELED))

    # ── retry (user, of a failed terminal job) + replay (operator) ────────────

    def retry(self, owner: str, job_id: str) -> dict[str, Any]:
        """User-requested retry of a *failed* job: schedules a real NEW execution
        (new id, attempts reset) that re-runs the same work, linked to the original
        via `parent_job_id`/`origin=retry`. Idempotent — a retry already in flight
        is returned rather than duplicated, so a double click can't double-run."""
        with self._session_factory() as session:
            row = session.get(ExecutionJob, job_id)
            if row is None or row.owner != owner:
                return {"ok": False, "not_found": True,
                        "message": "Job not found in this scope."}
            if row.status not in _RETRYABLE:
                return {"ok": False, "status": row.status,
                        "message": "Only a job that failed can be retried."}
            payload = row.payload_json
            kind, session_id, actor, title = row.kind, row.session_id, row.actor_account_id, row.title
        new_job = self._enqueue_clone(
            owner, kind, payload, session_id=session_id, actor_account_id=actor,
            title=title, parent_job_id=job_id, origin="retry",
            dedup_key=f"retry:{job_id}",
        )
        self._record_retry(owner, actor, title)
        return {"ok": True, "job": new_job}

    def replay(self, job_id: str, *, requested_by: str = "operator") -> Optional[dict[str, Any]]:
        """Operator-safe replay primitive: re-run ANY job (even a completed one) as
        a fresh execution linked via `origin=replay`. No user route exposes this —
        it's the clean seam for an operator/admin replay tool. Returns the new job."""
        with self._session_factory() as session:
            row = session.get(ExecutionJob, job_id)
            if row is None:
                return None
            owner, kind, payload = row.owner, row.kind, row.payload_json
            session_id, actor, title = row.session_id, row.actor_account_id, row.title
        return self._enqueue_clone(
            owner, kind, payload, session_id=session_id, actor_account_id=actor,
            title=title, parent_job_id=job_id, origin="replay",
            dedup_key=f"replay:{job_id}:{requested_by}",
        )

    def _enqueue_clone(
        self, owner: str, kind: str, payload_json: str, *,
        session_id: Optional[str], actor_account_id: Optional[str], title: Optional[str],
        parent_job_id: str, origin: str, dedup_key: str,
    ) -> dict[str, Any]:
        with self._session_factory() as session:
            existing = (
                session.query(ExecutionJob)
                .filter(ExecutionJob.owner == owner, ExecutionJob.dedup_key == dedup_key,
                        ExecutionJob.status.in_(tuple(_ACTIVE)))
                .first()
            )
            if existing is not None:
                return self._clean(existing)  # idempotent: re-run already in flight
            # Retry keeps the original class/priority; operator replay drops to the
            # isolated maintenance class so re-runs never jump ahead of user work.
            exec_class = job_policy.class_for(kind, origin=origin)
            row = ExecutionJob(
                id=uuid4().hex, owner=owner, session_id=session_id,
                actor_account_id=actor_account_id, kind=kind, status=QUEUED,
                exec_class=exec_class.name, priority=exec_class.priority,
                title=title, progress="Queued", payload_json=payload_json,
                dedup_key=dedup_key, parent_job_id=parent_job_id, origin=origin, attempts=0,
            )
            session.add(row)
            session.commit()
            cleaned = self._clean(row)
        # The lineage signal: the new run is queued AS a retry/replay of its parent.
        from app.observability import EVT_REPLAYED, EVT_RETRYING
        self._emit(EVT_RETRYING if origin == "retry" else EVT_REPLAYED,
                   owner=owner, job_id=cleaned["id"], kind=kind, origin=origin,
                   status=QUEUED, parent_job_id=parent_job_id, title=title)
        return cleaned

    # ── activity integration (honest, scope-attributed) ───────────────────────

    @staticmethod
    def _record_canceled(owner: str, actor_id: Optional[str], title: Optional[str]) -> None:
        try:
            from app.activity import RUN_CANCELED, activity_service
            activity_service.record(owner, RUN_CANCELED, f"Canceled {title or 'a background task'}",
                                    actor_id=actor_id, status="canceled")
        except Exception:
            pass

    @staticmethod
    def _record_retry(owner: str, actor_id: Optional[str], title: Optional[str]) -> None:
        try:
            from app.activity import RUN_RETRYING, activity_service
            activity_service.record(owner, RUN_RETRYING, f"Retrying {title or 'a background task'}",
                                    actor_id=actor_id, status="queued")
        except Exception:
            pass

    # ── worker step ───────────────────────────────────────────────────────────

    def run_once(self) -> Optional[dict[str, Any]]:
        """Claim and execute one job. Returns the clean job dict, or None when the
        queue is empty. Handler errors re-queue up to `job_max_attempts`, then the
        job is recorded as honestly failed — never silently dropped."""
        view = self.claim()
        if view is None:
            return None
        # Checkpoint 1: a cancel requested before the work starts stops cleanly.
        if self._is_cancelled(view.id):
            self._finish_canceled(view)
            return self.get_raw(view.id)
        handler = self._handlers.get(view.kind)
        if handler is None:
            self.transition(view.id, FAILED, progress="No handler",
                            result={"error": f"no handler for {view.kind}"})
            self._emit_failed(view, "NoHandler")
            return self.get_raw(view.id)
        try:
            result = handler(view)
        except JobCanceled:  # the handler bailed at a safe checkpoint
            self._finish_canceled(view)
            return self.get_raw(view.id)
        except Exception as error:  # honest failure + bounded internal repair retry
            if view.attempts < max(1, settings.job_max_attempts) and not self._is_cancelled(view.id):
                self.transition(view.id, QUEUED, progress="Retrying")
            elif self._is_cancelled(view.id):
                self._finish_canceled(view)
            else:
                self.transition(view.id, FAILED, progress="Failed",
                                result={"error": f"{type(error).__name__}: {error}"[:300]})
                self._emit_failed(view, type(error).__name__)
            return self.get_raw(view.id)
        # Checkpoint 2: honor a cancel that arrived DURING the run — the honest
        # outcome is canceled, and the (now-orphaned) result is not delivered.
        if self._is_cancelled(view.id):
            self._finish_canceled(view)
        else:
            self.transition(view.id, COMPLETED, progress="Completed", result=result)
            from app.observability import EVT_COMPLETED
            self._emit(EVT_COMPLETED, owner=view.owner, job_id=view.id, kind=view.kind,
                       status=COMPLETED, title=view.title)
        return self.get_raw(view.id)

    def _emit_failed(self, view: "JobView", failure_class: str) -> None:
        from app.observability import EVT_FAILED
        self._emit(EVT_FAILED, owner=view.owner, job_id=view.id, kind=view.kind,
                   status=FAILED, failure_class=failure_class, title=view.title)

    def _finish_canceled(self, view: "JobView") -> None:
        self.transition(view.id, CANCELED, progress="Canceled",
                        result={"canceled": True})
        self._record_canceled(view.owner, view.actor_account_id, view.title)
        from app.observability import EVT_CANCELED
        self._emit(EVT_CANCELED, owner=view.owner, job_id=view.id, kind=view.kind,
                   status=CANCELED, title=view.title)

    def drain(self, max_jobs: int = 50) -> int:
        """Run queued jobs until the queue is empty (used by the worker loop and
        tests). Returns how many job-executions ran."""
        ran = 0
        while ran < max_jobs and self.run_once() is not None:
            ran += 1
        return ran

    # ── reads (scope-aware, UI-ready) ─────────────────────────────────────────

    def get(self, owner: str, job_id: str) -> Optional[dict[str, Any]]:
        with self._session_factory() as session:
            row = session.get(ExecutionJob, job_id)
            if row is None or row.owner != owner:
                return None  # not in this scope — existence never leaks
            return self._clean(row)

    def get_raw(self, job_id: str) -> Optional[dict[str, Any]]:
        with self._session_factory() as session:
            row = session.get(ExecutionJob, job_id)
            return self._clean(row) if row is not None else None

    def recent(self, owner: Optional[str], *, limit: int = 10, active_only: bool = False) -> list[dict[str, Any]]:
        if not owner:
            return []
        try:
            with self._session_factory() as session:
                query = session.query(ExecutionJob).filter(ExecutionJob.owner == owner)
                if active_only:
                    query = query.filter(ExecutionJob.status.in_(tuple(_ACTIVE)))
                rows = query.order_by(ExecutionJob.created_at.desc()).limit(limit).all()
        except Exception:
            return []
        return [self._clean(r) for r in rows]

    @staticmethod
    def is_active(status: str) -> bool:
        return status in _ACTIVE

    @staticmethod
    def can_cancel(status: str) -> bool:
        return status == QUEUED or status in _INTERRUPTIBLE

    @staticmethod
    def can_retry(status: str) -> bool:
        return status in _RETRYABLE

    @classmethod
    def _clean(cls, row: ExecutionJob) -> dict[str, Any]:
        result: Any = None
        if row.result_json:
            try:
                result = json.loads(row.result_json)
            except (TypeError, ValueError):
                result = None
        return {
            "id": row.id,
            "kind": row.kind,
            "status": row.status,
            "title": row.title,
            "progress": row.progress,
            "result": result,  # clean handler outcome (title/download/error)
            "origin": row.origin,  # null | retry | replay — was this a re-run?
            "can_cancel": cls.can_cancel(row.status),
            "can_retry": cls.can_retry(row.status),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def clear_all(self) -> None:
        """Test isolation — wipe the queue."""
        try:
            with self._session_factory() as session:
                session.query(ExecutionJob).delete()
                session.commit()
        except Exception:
            pass


execution_queue = ExecutionQueueService()
