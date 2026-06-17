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

from app.auth import resolve_scope
from app.authz import PERM_MANAGE, can
from app.memory.preference_memory import preference_memory
from app.memory.preference_policy import (
    catalogue_with_values,
    is_valid_preference,
)

router = APIRouter(prefix="/preferences", tags=["AIRA-X Preferences"])


def _require_manage(scope) -> None:
    """Editing shared defaults is a workspace-settings action (owner-only).
    Personal scope is always self-managed."""
    decision = can(scope, PERM_MANAGE)
    if not decision:
        raise HTTPException(status_code=403, detail=decision.reason)


def _scope_for(request: Request | None, session_id: str | None):
    """Resolve the active scope for a preferences request (account / workspace /
    session). Editing always targets the ACTIVE scope, so a member acting in a
    workspace edits the workspace's shared defaults, and a personal user edits
    their own — explicit, never blurred."""
    return resolve_scope(request, session_id)


class PreferenceUpdate(BaseModel):
    session_id: str | None = None
    key: str
    value: str


def _payload(scope) -> dict:
    """The catalogue annotated with the ACTIVE scope's own values, plus which
    scope is being edited (no raw internals)."""
    owner = scope.owner_key or "default"
    saved = preference_memory.get(owner)
    return {
        "preferences": catalogue_with_values(saved),
        "scope": {"kind": scope.kind, "label": scope.label or scope.kind, "is_workspace": scope.is_workspace},
    }


@router.get("")
def list_preferences(request: Request, session_id: str | None = None) -> dict:
    """List the preference catalogue with the active scope's current values."""
    return _payload(_scope_for(request, session_id))


@router.put("")
def set_preference(update: PreferenceUpdate, request: Request) -> dict:
    """Set/update one preference in the active scope. Rejects keys/values outside
    the catalogue."""
    if not is_valid_preference(update.key, update.value):
        raise HTTPException(
            status_code=400,
            detail="Unsupported preference. Only the listed preferences and values can be saved.",
        )
    scope = _scope_for(request, update.session_id)
    _require_manage(scope)
    preference_memory.set(scope.owner_key or "default", update.key, update.value, source="settings_ui")
    return _payload(scope)


@router.delete("/{key}")
def clear_preference(key: str, request: Request, session_id: str | None = None) -> dict:
    """Clear one saved preference in the active scope (no error if unset)."""
    scope = _scope_for(request, session_id)
    _require_manage(scope)
    preference_memory.delete(scope.owner_key or "default", key)
    return _payload(scope)


@router.delete("")
def clear_all_preferences(request: Request, session_id: str | None = None) -> dict:
    """Clear all of the active scope's saved preferences."""
    scope = _scope_for(request, session_id)
    _require_manage(scope)
    preference_memory.clear(scope.owner_key or "default")
    return _payload(scope)
