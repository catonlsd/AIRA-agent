# File: backend/app/memory/preference_memory.py
"""
Durable, owner-scoped preference memory.

Stable user preferences (answer style, artifact style, fallback default) persist
in the database, tagged with the owning principal — so they survive restarts,
work across processes, and never leak between owners. The interface is small and
swappable (re-point at Redis/Postgres later) and mirrors the durable-store
pattern already used for guided flows and usage quotas.

Only the preference *catalogue* in `preference_policy` can be written here, so
this store can never accumulate arbitrary personal facts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from app.db.database import Base, SessionLocal, engine
from app.db.models import MemoryEntry

CATEGORY_PREFERENCE = "preference"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _owner_key(owner: str | None) -> str:
    return (owner or "").strip() or "anonymous"


class PreferenceMemory:
    """Owner-scoped key/value preference store (durable, upsert semantics)."""

    def __init__(
        self,
        session_factory: Callable[[], Any] = SessionLocal,
        category: str = CATEGORY_PREFERENCE,
    ) -> None:
        self._session_factory = session_factory
        self._category = category
        self._ensure_table()

    def _ensure_table(self) -> None:
        try:
            MemoryEntry.__table__.create(bind=engine, checkfirst=True)
        except Exception:
            Base.metadata.create_all(bind=engine)

    def get(self, owner: str | None) -> dict[str, str]:
        key = _owner_key(owner)
        with self._session_factory() as session:
            rows = (
                session.query(MemoryEntry)
                .filter(MemoryEntry.owner == key, MemoryEntry.category == self._category)
                .all()
            )
            return {row.key: row.value for row in rows}

    def set(self, owner: str | None, key: str, value: str, *, source: str | None = None) -> None:
        owner_key = _owner_key(owner)
        with self._session_factory() as session:
            existing = (
                session.query(MemoryEntry)
                .filter(
                    MemoryEntry.owner == owner_key,
                    MemoryEntry.category == self._category,
                    MemoryEntry.key == key,
                )
                .first()
            )
            if existing:
                existing.value = value
                existing.source = source
                existing.updated_at = _now()
            else:
                session.add(
                    MemoryEntry(
                        id=uuid4().hex,
                        owner=owner_key,
                        category=self._category,
                        key=key,
                        value=value,
                        source=source,
                        updated_at=_now(),
                    )
                )
            session.commit()

    def set_many(self, owner: str | None, values: dict[str, str], *, source: str | None = None) -> int:
        for key, value in (values or {}).items():
            self.set(owner, key, value, source=source)
        return len(values or {})

    def delete(self, owner: str | None, key: str) -> bool:
        """Remove a single preference for an owner. Returns True if one existed."""
        owner_key = _owner_key(owner)
        with self._session_factory() as session:
            removed = (
                session.query(MemoryEntry)
                .filter(
                    MemoryEntry.owner == owner_key,
                    MemoryEntry.category == self._category,
                    MemoryEntry.key == key,
                )
                .delete()
            )
            session.commit()
            return bool(removed)

    def clear(self, owner: str | None) -> None:
        owner_key = _owner_key(owner)
        with self._session_factory() as session:
            session.query(MemoryEntry).filter(
                MemoryEntry.owner == owner_key, MemoryEntry.category == self._category
            ).delete()
            session.commit()

    def clear_all(self) -> None:
        """Wipe the category (test isolation)."""
        with self._session_factory() as session:
            session.query(MemoryEntry).filter(
                MemoryEntry.category == self._category
            ).delete()
            session.commit()


preference_memory = PreferenceMemory()
