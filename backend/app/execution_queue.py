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

# A handler runs a job and returns (result_dict, title) or raises on failure.
JobHandler = Callable[["JobView"], dict[str, Any]]


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class JobView:
    """A plain, read-only view of a job handed to handlers — no ORM session."""

    def __init__(self, row: ExecutionJob) -> None:
        self.id = row.id
        self.owner = row.owner
        self.session_id = row.session_id
        self.actor_account_id = row.actor_account_id
        self.kind = row.kind
        self.attempts = row.attempts
        try:
            self.payload = json.loads(row.payload_json)
        except (TypeError, ValueError):
            self.payload = {}


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
            row = ExecutionJob(
                id=uuid4().hex,
                owner=owner,
                session_id=session_id,
                actor_account_id=actor_account_id,
                kind=kind,
                status=QUEUED,
                title=(title or None),
                progress="Queued",
                payload_json=json.dumps(payload or {}),
                dedup_key=dedup_key,
                run_id=run_id,
                attempts=0,
            )
            session.add(row)
            session.commit()
            return self._clean(row)

    # ── claim (atomic; exactly one worker wins) ───────────────────────────────

    def claim(self) -> Optional[JobView]:
        with self._session_factory() as session:
            row = (
                session.query(ExecutionJob)
                .filter(ExecutionJob.status == QUEUED)
                .order_by(ExecutionJob.created_at.asc())
                .first()
            )
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
            return JobView(row)

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
            row.status = status
            if progress is not None:
                row.progress = progress
            if result is not None:
                row.result_json = json.dumps(result)
            row.updated_at = _now()
            if status in _TERMINAL:
                row.finished_at = _now()
            session.commit()

    def cancel_request(self, owner: str, job_id: str) -> bool:
        """Foundation for cancellation: mark an active job for cancel. The worker
        checks this before running terminal work; a finished job is left alone."""
        with self._session_factory() as session:
            row = session.get(ExecutionJob, job_id)
            if row is None or row.owner != owner:
                return False
            if row.status in _TERMINAL or row.status == CANCELED:
                return False
            row.status = CANCELED if row.status == QUEUED else CANCEL_REQUESTED
            row.updated_at = _now()
            session.commit()
            return True

    def _is_cancelled(self, job_id: str) -> bool:
        with self._session_factory() as session:
            row = session.get(ExecutionJob, job_id)
            return bool(row and row.status in (CANCEL_REQUESTED, CANCELED))

    # ── worker step ───────────────────────────────────────────────────────────

    def run_once(self) -> Optional[dict[str, Any]]:
        """Claim and execute one job. Returns the clean job dict, or None when the
        queue is empty. Handler errors re-queue up to `job_max_attempts`, then the
        job is recorded as honestly failed — never silently dropped."""
        view = self.claim()
        if view is None:
            return None
        if self._is_cancelled(view.id):
            self.transition(view.id, CANCELED, progress="Canceled")
            return self.get_raw(view.id)
        handler = self._handlers.get(view.kind)
        if handler is None:
            self.transition(view.id, FAILED, progress="No handler",
                            result={"error": f"no handler for {view.kind}"})
            return self.get_raw(view.id)
        try:
            result = handler(view)
            self.transition(view.id, COMPLETED, progress="Completed", result=result)
        except Exception as error:  # honest failure + bounded retry
            if view.attempts < max(1, settings.job_max_attempts):
                self.transition(view.id, QUEUED, progress="Retrying")
            else:
                self.transition(view.id, FAILED, progress="Failed",
                                result={"error": f"{type(error).__name__}: {error}"[:300]})
        return self.get_raw(view.id)

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
    def _clean(row: ExecutionJob) -> dict[str, Any]:
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
