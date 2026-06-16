# File: backend/app/routes/preferences.py
"""
Explicit, owner-scoped preference-management API.

The user-controllable surface for AIRA-X's durable preference memory: review,
set, clear-one, and clear-all. It exposes ONLY the product-approved preference
catalogue (answer style/length/format, code-first, artifact style, web
fallback) — never raw rows, internal session memory, arbitrary keys, or policy
internals. Every call is scoped to the requesting principal's owner, exactly
like the rest of the product, so one user can never see or change another's.

Ownership note: with no login yet, the owner is the caller's session id — the
same scope `build_turn_context` uses for a turn — so preferences edited here are
the ones the supervisor applies to that session's answers and artifacts.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.auth import resolve_owner
from app.memory.preference_memory import preference_memory
from app.memory.preference_policy import (
    catalogue_with_values,
    is_valid_preference,
)

router = APIRouter(prefix="/preferences", tags=["AIRA-X Preferences"])


def _owner_for(request: Request | None, session_id: str | None) -> str:
    """Resolve the durable owner for a preferences request.

    Account-first: a signed account token owns "account:<id>"; otherwise the
    session is the owner (a blank session resolves to "default"). This matches
    exactly how a turn resolves its owner, so the preferences a user edits are
    the ones the supervisor applies.
    """
    return resolve_owner(request, session_id) or "default"


class PreferenceUpdate(BaseModel):
    session_id: str | None = None
    key: str
    value: str


def _payload(owner: str) -> dict:
    """The catalogue annotated with this owner's saved values (no raw internals)."""
    saved = preference_memory.get(owner)
    return {"preferences": catalogue_with_values(saved)}


@router.get("")
def list_preferences(request: Request, session_id: str | None = None) -> dict:
    """List the preference catalogue with the owner's current values."""
    return _payload(_owner_for(request, session_id))


@router.put("")
def set_preference(update: PreferenceUpdate, request: Request) -> dict:
    """Set/update one preference. Rejects keys/values outside the catalogue."""
    if not is_valid_preference(update.key, update.value):
        raise HTTPException(
            status_code=400,
            detail="Unsupported preference. Only the listed preferences and values can be saved.",
        )
    owner = _owner_for(request, update.session_id)
    preference_memory.set(owner, update.key, update.value, source="settings_ui")
    return _payload(owner)


@router.delete("/{key}")
def clear_preference(key: str, request: Request, session_id: str | None = None) -> dict:
    """Clear one saved preference (no error if it wasn't set)."""
    owner = _owner_for(request, session_id)
    preference_memory.delete(owner, key)
    return _payload(owner)


@router.delete("")
def clear_all_preferences(request: Request, session_id: str | None = None) -> dict:
    """Clear all of this owner's saved preferences."""
    owner = _owner_for(request, session_id)
    preference_memory.clear(owner)
    return _payload(owner)
