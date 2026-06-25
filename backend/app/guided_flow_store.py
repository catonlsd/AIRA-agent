# File: backend/app/guided_flow_store.py
"""
Durable, multi-process-safe store for guided-flow pending state.

Guided flows (plan approval, runtime-action approval, artifact approval,
clarification follow-up) used to live in process memory, so they died on
restart and broke across multiple server instances. This store persists them in
the database and makes the consume (resume) step atomic, so approvals are:

  * durable      — survive process restarts
  * multi-process safe — request on process A, approval on process B
  * idempotent   — a single atomic status flip "pending" -> "consumed" means a
                   resume runs exactly once, even under duplicate clicks/races
  * honest       — missing / expired / already-consumed states resolve to None,
                   never a fabricated continuation

The backend is the existing SQLAlchemy/SQLite engine; the `GuidedFlowStore`
interface is deliberately small so it can be re-pointed at Redis/Postgres later
without touching the supervisor. `GuidedFlowAdapter` wraps it per pending-kind
with serialize/deserialize, preserving the old `.get/.set/.clear` API and
adding atomic `.consume`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional
from uuid import uuid4

from sqlalchemy import delete, update

from app.db.database import Base, SessionLocal, engine
from app.db.models import GuidedFlow

# Pending guided steps expire after this long if never resumed (stale-state
# policy). Generous, since a user may approve a plan minutes or hours later.
DEFAULT_TTL_SECONDS = 24 * 60 * 60


def _now() -> datetime:
    # Naive UTC: SQLite DateTime stores/returns naive, so comparisons stay
    # consistent. Avoids the deprecated datetime.utcnow().
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _session_key(session_id: Optional[str]) -> str:
    return session_id or "anonymous"


class GuidedFlowStore:
    """Persistent pending-state store with an atomic, idempotent consume."""

    def __init__(self, session_factory: Callable[[], Any] = SessionLocal) -> None:
        self._session_factory = session_factory
        self._ensure_table()

    def _ensure_table(self) -> None:
        # Works even when a test never calls init_db().
        try:
            GuidedFlow.__table__.create(bind=engine, checkfirst=True)
        except Exception:
            Base.metadata.create_all(bind=engine)

    def set(
        self,
        session_id: Optional[str],
        kind: str,
        payload: dict,
        *,
        run_id: Optional[str] = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> str:
        """Persist a pending flow, replacing any prior pending one for this key."""
        key = _session_key(session_id)
        flow_id = uuid4().hex
        now = _now()
        with self._session_factory() as session:
            # One pending step per (session, kind): drop any prior pending row.
            session.execute(
                delete(GuidedFlow).where(
                    GuidedFlow.session_key == key,
                    GuidedFlow.kind == kind,
                    GuidedFlow.status == "pending",
                )
            )
            session.add(
                GuidedFlow(
                    id=flow_id,
                    session_key=key,
                    kind=kind,
                    status="pending",
                    payload_json=json.dumps(payload, default=str),
                    run_id=run_id,
                    created_at=now,
                    updated_at=now,
                    expires_at=now + timedelta(seconds=ttl_seconds) if ttl_seconds else None,
                )
            )
            session.commit()
        return flow_id

    def peek(self, session_id: Optional[str], kind: str) -> Optional[dict]:
        """Read the pending payload WITHOUT consuming it (expired rows included
        so the caller can still respond honestly)."""
        key = _session_key(session_id)
        with self._session_factory() as session:
            row = (
                session.query(GuidedFlow)
                .filter(
                    GuidedFlow.session_key == key,
                    GuidedFlow.kind == kind,
                    GuidedFlow.status == "pending",
                )
                .order_by(GuidedFlow.created_at.desc())
                .first()
            )
            return json.loads(row.payload_json) if row else None

    def consume(self, session_id: Optional[str], kind: str) -> Optional[dict]:
        """Atomically claim the pending flow. Returns the payload exactly once.

        Returns None when the flow is missing, expired, or already consumed —
        the idempotency + stale-state guarantee. The single guarded UPDATE is
        atomic per row; SQLite serializes writers via its file lock, so two
        processes racing to approve cannot both win.
        """
        key = _session_key(session_id)
        now = _now()
        with self._session_factory() as session:
            row = (
                session.query(GuidedFlow)
                .filter(
                    GuidedFlow.session_key == key,
                    GuidedFlow.kind == kind,
                    GuidedFlow.status == "pending",
                )
                .order_by(GuidedFlow.created_at.desc())
                .first()
            )
            if row is None:
                return None
            if row.expires_at is not None and row.expires_at < now:
                return None  # stale: honest miss
            payload = json.loads(row.payload_json)
            # Atomic claim guarded by status — only one caller flips it.
            claimed = session.execute(
                update(GuidedFlow)
                .where(GuidedFlow.id == row.id, GuidedFlow.status == "pending")
                .values(status="consumed", updated_at=now)
            )
            session.commit()
            return payload if claimed.rowcount == 1 else None

    def clear(self, session_id: Optional[str], kind: str) -> None:
        key = _session_key(session_id)
        with self._session_factory() as session:
            session.execute(
                delete(GuidedFlow).where(
                    GuidedFlow.session_key == key, GuidedFlow.kind == kind
                )
            )
            session.commit()

    def count_pending(self, session_id: Optional[str]) -> int:
        """Number of in-flight (pending, non-expired) flows for this owner.

        Used by the per-owner pending-flow quota — durable and multi-process
        safe (counts DB rows, not in-memory state).
        """
        key = _session_key(session_id)
        now = _now()
        with self._session_factory() as session:
            return (
                session.query(GuidedFlow)
                .filter(
                    GuidedFlow.session_key == key,
                    GuidedFlow.status == "pending",
                )
                .filter((GuidedFlow.expires_at.is_(None)) | (GuidedFlow.expires_at >= now))
                .count()
            )

    def list_pending(self, session_id: Optional[str]) -> list[dict]:
        """Every in-flight (pending, non-expired) flow for this owner, newest first.

        Read-only and clean: returns `{kind, run_id, created_at, data}` so the
        run-history layer can surface genuinely resumable runs without consuming
        them. The atomic resume primitive stays `consume`; this only peeks.
        """
        key = _session_key(session_id)
        now = _now()
        with self._session_factory() as session:
            rows = (
                session.query(GuidedFlow)
                .filter(
                    GuidedFlow.session_key == key,
                    GuidedFlow.status == "pending",
                )
                .filter((GuidedFlow.expires_at.is_(None)) | (GuidedFlow.expires_at >= now))
                .order_by(GuidedFlow.created_at.desc())
                .all()
            )
            out: list[dict] = []
            for row in rows:
                try:
                    data = json.loads(row.payload_json)
                except (TypeError, ValueError):
                    continue
                out.append({
                    "kind": row.kind,
                    "run_id": row.run_id,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "data": data,
                })
            return out

    def clear_all(self) -> None:
        """Wipe every guided flow (used by tests for isolation)."""
        with self._session_factory() as session:
            session.execute(delete(GuidedFlow))
            session.commit()

    def purge_expired(self) -> int:
        with self._session_factory() as session:
            result = session.execute(
                delete(GuidedFlow).where(GuidedFlow.expires_at < _now())
            )
            session.commit()
            return result.rowcount or 0


# Process-wide durable store (backed by the real DB, so restart-safe).
guided_flow_store = GuidedFlowStore()


class GuidedFlowAdapter:
    """Per-kind facade preserving the old store API over the durable store.

    `.get` peeks, `.set` persists, `.clear` deletes, and `.consume` atomically
    claims (the idempotent resume primitive). Serialization keeps the supervisor
    working with rich dataclasses while the store sees plain JSON.
    """

    def __init__(
        self,
        kind: str,
        to_dict: Callable[[Any], dict],
        from_dict: Callable[[dict], Any],
        *,
        store: GuidedFlowStore = guided_flow_store,
        run_id_of: Optional[Callable[[Any], Optional[str]]] = None,
    ) -> None:
        self.kind = kind
        self._to_dict = to_dict
        self._from_dict = from_dict
        self._store = store
        self._run_id_of = run_id_of

    def set(self, session_id: Optional[str], pending: Any) -> None:
        run_id = self._run_id_of(pending) if self._run_id_of else None
        self._store.set(session_id, self.kind, self._to_dict(pending), run_id=run_id)

    def get(self, session_id: Optional[str]) -> Optional[Any]:
        data = self._store.peek(session_id, self.kind)
        return self._from_dict(data) if data is not None else None

    def consume(self, session_id: Optional[str]) -> Optional[Any]:
        data = self._store.consume(session_id, self.kind)
        return self._from_dict(data) if data is not None else None

    def clear(self, session_id: Optional[str]) -> None:
        self._store.clear(session_id, self.kind)
