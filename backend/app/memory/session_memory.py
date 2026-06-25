# File: backend/app/memory/session_memory.py
"""
Ephemeral, owner+session-scoped working memory.

Session memory holds the *current* working context for an active conversation —
the live task/thread, working assumptions, recent user-provided constraints. It
is intentionally ephemeral (process-local, not persisted): it dies with the
process and is never promoted to durable storage unless a higher layer decides
to (e.g. extracting a stable preference, which goes to `PreferenceMemory`).

Scoping is strict: keyed by (owner, session), so one principal's working context
never bleeds into another's. The interface is small so it can later be backed by
a TTL cache / Redis without changing callers.
"""

from __future__ import annotations

import threading
from typing import Any


def _scope(owner: str | None, session_id: str | None) -> tuple[str, str]:
    return ((owner or "").strip() or "anonymous", (session_id or "").strip() or "default")


class SessionMemory:
    """Process-local working context, scoped to (owner, session)."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = threading.Lock()

    def note(self, owner: str | None, session_id: str | None, key: str, value: Any) -> None:
        scope = _scope(owner, session_id)
        with self._lock:
            self._store.setdefault(scope, {})[key] = value

    def get(self, owner: str | None, session_id: str | None) -> dict[str, Any]:
        scope = _scope(owner, session_id)
        with self._lock:
            return dict(self._store.get(scope, {}))

    def value(self, owner: str | None, session_id: str | None, key: str) -> Any:
        return self.get(owner, session_id).get(key)

    def clear(self, owner: str | None, session_id: str | None) -> None:
        scope = _scope(owner, session_id)
        with self._lock:
            self._store.pop(scope, None)

    def clear_all(self) -> None:
        """Wipe all working context (test isolation / new process)."""
        with self._lock:
            self._store.clear()


session_memory = SessionMemory()
