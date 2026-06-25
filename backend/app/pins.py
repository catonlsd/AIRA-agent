# File: backend/app/pins.py
"""
Pinned items — a small, durable, scope-owned way to keep important work findable.

A pin is just a reference (`ref_type` + `ref_id`) plus a clean display title — it
never copies the underlying resource payload, so the artifact / run / document
stays the single source of truth. Scope-owned (`owner` = account:<id> /
workspace:<id> / session), so pins list by the active scope and inherit the same
access boundaries as everything else. Pinning is idempotent per
(owner, ref_type, ref_id): re-pinning refreshes the title instead of duplicating.

Reads return only UI-ready fields — never owner keys, raw rows, or payloads. The
route layer resolves a pinned `artifact` ref to its access-controlled download URL
and a pinned `run` ref to its live status/continue affordance; this service stays
a thin durable store so richer saved collections layer on later for free.
"""

from __future__ import annotations

from typing import Any, Callable, Optional
from uuid import uuid4

from app.db.database import Base, SessionLocal, engine
from app.db.models import PinnedItem

REF_ARTIFACT = "artifact"
REF_RUN = "run"
REF_DOCUMENT = "document"
_REF_TYPES = {REF_ARTIFACT, REF_RUN, REF_DOCUMENT}


class PinService:
    def __init__(self, session_factory: Callable[[], Any] = SessionLocal) -> None:
        self._session_factory = session_factory
        self._ensure_table()

    def _ensure_table(self) -> None:
        try:
            PinnedItem.__table__.create(bind=engine, checkfirst=True)
        except Exception:
            Base.metadata.create_all(bind=engine)

    # ── write ─────────────────────────────────────────────────────────────────

    def pin(
        self,
        owner: str,
        ref_type: str,
        ref_id: str,
        title: str,
        *,
        subtitle: Optional[str] = None,
    ) -> Optional[dict]:
        """Pin a resource for this owner. Idempotent: re-pinning the same ref
        refreshes the title/subtitle rather than creating a duplicate."""
        if not owner or ref_type not in _REF_TYPES or not ref_id or not title:
            return None
        with self._session_factory() as session:
            row = (
                session.query(PinnedItem)
                .filter(
                    PinnedItem.owner == owner,
                    PinnedItem.ref_type == ref_type,
                    PinnedItem.ref_id == ref_id,
                )
                .first()
            )
            if row is None:
                row = PinnedItem(
                    id=uuid4().hex, owner=owner, ref_type=ref_type,
                    ref_id=ref_id, title=title[:255], subtitle=(subtitle or None),
                )
                session.add(row)
            else:
                row.title = title[:255]
                row.subtitle = subtitle or None
            session.commit()
            return self._clean(row)

    def unpin(self, owner: str, pin_id: str) -> bool:
        """Remove a pin by id, scoped to this owner (no cross-scope delete)."""
        if not owner or not pin_id:
            return False
        with self._session_factory() as session:
            deleted = (
                session.query(PinnedItem)
                .filter(PinnedItem.owner == owner, PinnedItem.id == pin_id)
                .delete()
            )
            session.commit()
            return bool(deleted)

    # ── read ──────────────────────────────────────────────────────────────────

    def list(self, owner: Optional[str], *, limit: int = 20) -> list[dict]:
        if not owner:
            return []
        try:
            with self._session_factory() as session:
                rows = (
                    session.query(PinnedItem)
                    .filter(PinnedItem.owner == owner)
                    .order_by(PinnedItem.created_at.desc())
                    .limit(limit)
                    .all()
                )
        except Exception:
            return []
        return [self._clean(row) for row in rows]

    def is_pinned(self, owner: str, ref_type: str, ref_id: str) -> bool:
        with self._session_factory() as session:
            return session.query(PinnedItem).filter(
                PinnedItem.owner == owner,
                PinnedItem.ref_type == ref_type,
                PinnedItem.ref_id == ref_id,
            ).first() is not None

    @staticmethod
    def _clean(row: PinnedItem) -> dict:
        return {
            "id": row.id,
            "ref_type": row.ref_type,
            "ref_id": row.ref_id,
            "title": row.title,
            "subtitle": row.subtitle,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    def clear_all(self) -> None:
        """Test isolation — wipe all pins."""
        try:
            with self._session_factory() as session:
                session.query(PinnedItem).delete()
                session.commit()
        except Exception:
            pass


pin_service = PinService()
