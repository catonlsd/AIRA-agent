# File: backend/app/bundles.py
"""
Context bundles ("handoff packs") — save a useful combination of prior work.

A small, durable, scope-owned store of REFERENCES (documents / artifacts / runs),
never payloads — so a bundle is just a named shortcut to a set of resources that
stay the single source of truth. "Save this strategy doc + last roadmap deck +
failed run as the Q3 planning pack", reopen it later, or hand it to a teammate in
a workspace where permissions allow.

Scope-owned (`owner` = account:<id> / workspace:<id> / session), so a personal
pack stays personal and a workspace pack is shared with authorized members. Access
is NOT trusted from the bundle: loading re-resolves every reference against the
*current* scope (via the chat-context service), so an item that is no longer
accessible is simply skipped — a bundle can never smuggle in another scope's work.
Reads return only clean, UI-ready fields — never owner keys, payloads, or rows.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional
from uuid import uuid4

from app.db.database import Base, SessionLocal, engine
from app.db.models import ContextBundle

_MAX_ITEMS = 8
_ALLOWED_REF_TYPES = {"document", "artifact", "run"}


def _clean_items(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Keep only the minimal reference fields — never prompts, payloads, urls."""
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items or []:
        ref_type = str(item.get("ref_type", ""))
        ref_id = str(item.get("ref_id", ""))
        if ref_type not in _ALLOWED_REF_TYPES or not ref_id:
            continue
        key = (ref_type, ref_id)
        if key in seen:
            continue
        seen.add(key)
        out.append({"ref_type": ref_type, "ref_id": ref_id, "title": str(item.get("title") or ref_id)[:255]})
    return out[:_MAX_ITEMS]


class BundleService:
    def __init__(self, session_factory: Callable[[], Any] = SessionLocal) -> None:
        self._session_factory = session_factory
        self._ensure_table()

    def _ensure_table(self) -> None:
        try:
            ContextBundle.__table__.create(bind=engine, checkfirst=True)
        except Exception:
            Base.metadata.create_all(bind=engine)

    # ── write ─────────────────────────────────────────────────────────────────

    def create(self, owner: str, name: str, items: list[dict[str, Any]]) -> Optional[dict]:
        """Save a bundle of references for this owner. Returns None when there's
        nothing valid to save (no accessible items / no name)."""
        clean = _clean_items(items)
        name = (name or "").strip()[:120]
        if not owner or not name or not clean:
            return None
        with self._session_factory() as session:
            row = ContextBundle(id=uuid4().hex, owner=owner, name=name, items_json=json.dumps(clean))
            session.add(row)
            session.commit()
            return self._clean(row)

    def rename(self, owner: str, bundle_id: str, name: str) -> bool:
        name = (name or "").strip()[:120]
        if not name:
            return False
        with self._session_factory() as session:
            row = (
                session.query(ContextBundle)
                .filter(ContextBundle.owner == owner, ContextBundle.id == bundle_id)
                .first()
            )
            if row is None:
                return False
            row.name = name
            session.commit()
            return True

    def delete(self, owner: str, bundle_id: str) -> bool:
        if not owner or not bundle_id:
            return False
        with self._session_factory() as session:
            deleted = (
                session.query(ContextBundle)
                .filter(ContextBundle.owner == owner, ContextBundle.id == bundle_id)
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
                    session.query(ContextBundle)
                    .filter(ContextBundle.owner == owner)
                    .order_by(ContextBundle.created_at.desc())
                    .limit(limit)
                    .all()
                )
        except Exception:
            return []
        return [self._clean(row) for row in rows]

    def item_refs(self, owner: str, bundle_id: str) -> Optional[list[dict[str, str]]]:
        """The stored references for a bundle (owner-scoped), or None if missing."""
        with self._session_factory() as session:
            row = (
                session.query(ContextBundle)
                .filter(ContextBundle.owner == owner, ContextBundle.id == bundle_id)
                .first()
            )
            if row is None:
                return None
            try:
                return _clean_items(json.loads(row.items_json))
            except (TypeError, ValueError):
                return []

    @staticmethod
    def _clean(row: ContextBundle) -> dict:
        try:
            items = _clean_items(json.loads(row.items_json))
        except (TypeError, ValueError):
            items = []
        return {
            "id": row.id,
            "name": row.name,
            "count": len(items),
            "items": [{"ref_type": i["ref_type"], "title": i["title"]} for i in items],
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    def clear_all(self) -> None:
        """Test isolation — wipe all bundles."""
        try:
            with self._session_factory() as session:
                session.query(ContextBundle).delete()
                session.commit()
        except Exception:
            pass


bundle_service = BundleService()
