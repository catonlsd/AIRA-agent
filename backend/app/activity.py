# File: backend/app/activity.py
"""
Activity service — meaningful, user-facing product events (not raw traces).

A thin durable layer that records noteworthy things that happened in a scope —
an artifact created, a document uploaded, a run completed/failed, a workspace
member added, a workspace default changed — and reads them back as clean, minimal
summaries for a calm "recent activity" surface. Deliberately NOT a trace sink:
low-level execution noise, tool payloads, and stack traces stay in the ops logs /
traces, never here.

Scope-owned (`owner` = account:<id> / workspace:<id> / session) and best-effort:
recording must never break the action it describes. Reads return only
UI-ready fields — title, actor display name, type, status, time — never owner
keys, resource internals, or debug blobs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional
from uuid import uuid4

from app.db.database import Base, SessionLocal, engine
from app.db.models import ActivityEvent

# Meaningful event types (a small, curated set — not every trace event).
ARTIFACT_CREATED = "artifact_created"
ARTIFACT_FAILED = "artifact_failed"
DOCUMENT_UPLOADED = "document_uploaded"
RUN_COMPLETED = "run_completed"
RUN_FAILED = "run_failed"
VALIDATION_PASSED = "validation_passed"
VALIDATION_FAILED = "validation_failed"
STARTUP_VERIFIED = "startup_verified"
STARTUP_FAILED = "startup_failed"
PREFERENCE_UPDATED = "preference_updated"
WORKSPACE_MEMBER_ADDED = "workspace_member_added"

# Severity hint for the UI (never a stack trace / raw detail).
_FAILURE_TYPES = {ARTIFACT_FAILED, RUN_FAILED, VALIDATION_FAILED, STARTUP_FAILED}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def severity_for(event_type: str, status: Optional[str]) -> str:
    if event_type in _FAILURE_TYPES or status in ("failed", "error"):
        return "warn"
    return "info"


class ActivityService:
    def __init__(self, session_factory: Callable[[], Any] = SessionLocal) -> None:
        self._session_factory = session_factory
        self._ensure_table()

    def _ensure_table(self) -> None:
        try:
            ActivityEvent.__table__.create(bind=engine, checkfirst=True)
        except Exception:
            Base.metadata.create_all(bind=engine)

    # ── record (best-effort; never raises) ───────────────────────────────────

    def record(
        self,
        owner: Optional[str],
        type: str,
        title: str,
        *,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
        status: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
    ) -> None:
        if not owner or not type or not title:
            return
        try:
            name = actor_name or self._actor_name(actor_id)
            with self._session_factory() as session:
                session.add(
                    ActivityEvent(
                        id=uuid4().hex,
                        owner=owner,
                        actor_account_id=actor_id,
                        actor_name=name,
                        type=type,
                        title=title[:255],
                        status=status,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        created_at=_now(),
                    )
                )
                session.commit()
        except Exception:
            pass  # activity must never break the action it describes

    @staticmethod
    def _actor_name(actor_id: Optional[str]) -> Optional[str]:
        if not actor_id:
            return None
        try:
            from app.accounts import account_service

            account = account_service.get(actor_id)
            return account.get("display_name") if account else None
        except Exception:
            return None

    # ── read (clean, minimal, scope-owned) ───────────────────────────────────

    def recent(self, owner: Optional[str], *, limit: int = 12, types: Optional[list[str]] = None) -> list[dict]:
        if not owner:
            return []
        try:
            with self._session_factory() as session:
                query = session.query(ActivityEvent).filter(ActivityEvent.owner == owner)
                if types:
                    query = query.filter(ActivityEvent.type.in_(types))
                rows = query.order_by(ActivityEvent.created_at.desc()).limit(limit).all()
        except Exception:
            return []
        return [
            {
                "type": row.type,
                "title": row.title,
                "actor": row.actor_name,
                "status": row.status,
                "severity": severity_for(row.type, row.status),
                "resource_type": row.resource_type,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]

    def clear_all(self) -> None:
        """Test isolation — wipe the activity log."""
        try:
            with self._session_factory() as session:
                session.query(ActivityEvent).delete()
                session.commit()
        except Exception:
            pass


activity_service = ActivityService()
