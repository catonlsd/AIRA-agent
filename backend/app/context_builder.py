# File: backend/app/context_builder.py
"""
Builds one normalized context object for a chat turn.

Routes should not assemble conversation history, file context, or memory
themselves — they hand the raw request to `build_turn_context` and pass the
resulting `TurnContext` to the supervisor. This removes context-building
duplication and gives every capability the same inputs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import uuid4

DEFAULT_SESSION_ID = "default"


@dataclass
class TurnTrace:
    """Lightweight trace seam.

    Records ordered events for one turn. Phase 4 turns this into a persisted
    tracing layer; for now it is an in-memory accumulator so the supervisor can
    instrument every path from day one without a later retrofit.
    """

    turn_id: str
    events: list[dict] = field(default_factory=list)
    _t0: float = field(default_factory=time.perf_counter)

    def event(self, name: str, **data: Any) -> None:
        self.events.append(
            {
                "name": name,
                "elapsed_ms": self.elapsed_ms(),
                **data,
            }
        )

    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self._t0) * 1000, 2)

    def as_dict(self) -> dict:
        return {"turn_id": self.turn_id, "events": self.events}


@dataclass
class TurnContext:
    message: str
    session_id: str
    run_id: str
    trace: TurnTrace

    history: list[dict] = field(default_factory=list)
    preferences: dict = field(default_factory=dict)

    uploaded_file_names: list[str] = field(default_factory=list)
    has_uploaded_files: bool = False

    # Set when this turn resumes a paused (approval) workflow.
    resume_run_id: Optional[str] = None

    @property
    def is_resume(self) -> bool:
        return self.resume_run_id is not None


def build_turn_context(
    message: str,
    *,
    session_id: Optional[str] = None,
    run_id: Optional[str] = None,
    db: Any | None = None,
    uploaded_file_names: Optional[list[str]] = None,
    history: Optional[list[dict]] = None,
    history_limit: Optional[int] = None,
) -> TurnContext:
    """Assemble the normalized context for one turn.

    Conversation history comes from one of two sources:
    - `history`: recent {role, content} turns supplied by the caller (e.g. the
      client sends the visible conversation). Used as-is when provided.
    - `db`: when no explicit history is given but a DB session is, recent history
      and preferences are loaded from server-side memory.

    `db` is optional so this stays unit-testable without a database.
    """
    resolved_session = (session_id or DEFAULT_SESSION_ID).strip() or DEFAULT_SESSION_ID
    turn_id = uuid4().hex
    trace = TurnTrace(turn_id=turn_id)

    file_names = [name for name in (uploaded_file_names or []) if name]

    context = TurnContext(
        message=message,
        session_id=resolved_session,
        run_id=run_id or uuid4().hex,
        trace=trace,
        uploaded_file_names=file_names,
        has_uploaded_files=bool(file_names),
        resume_run_id=run_id,
    )

    if history is not None:
        context.history = _normalize_history(history)
    elif db is not None:
        loaded_history, preferences = _load_memory(db, history_limit)
        context.history = loaded_history
        context.preferences = preferences

    trace.event(
        "context_built",
        session_id=resolved_session,
        has_uploaded_files=context.has_uploaded_files,
        history_len=len(context.history),
    )

    return context


def _normalize_history(history: list[dict]) -> list[dict]:
    """Keep only well-formed {role, content} entries with non-empty content."""
    normalized: list[dict] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        role = item.get("role")
        role = role if role in ("user", "assistant") else "user"
        normalized.append({"role": role, "content": content})
    return normalized


def _load_memory(db: Any, history_limit: Optional[int]) -> tuple[list[dict], dict]:
    # Imported lazily so context building stays usable without the DB stack.
    from app.memory.service import MemoryService

    service = MemoryService()
    history = service.recent_history(db, limit=history_limit)
    preferences = service.preferences(db)
    return history, preferences
