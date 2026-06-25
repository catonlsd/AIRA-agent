# File: backend/app/routes/activity.py
"""
Recent activity for the active scope — one clean, permission-aware read.

  GET /activity/recent  -> { scope, events }

Meaningful, user-facing product events (artifact created, document uploaded, run
completed/failed, validation/startup result, preference changed, member added) —
NOT raw traces or operator diagnostics (those stay in the ops logs). Resolves the
active scope like a turn (account-first; a workspace header is honoured only for
members), requires `view` (granted in every real scope) so a viewer can see
authorized workspace activity while a non-member silently gets their personal
scope. Returns only UI-ready fields: title, actor, type, status, severity, time.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.activity import activity_service
from app.auth import resolve_scope
from app.authz import PERM_VIEW, can

router = APIRouter(prefix="/activity", tags=["AIRA-X Activity"])


@router.get("/recent")
def recent_activity(request: Request, session_id: str | None = None, type: str | None = None) -> dict:
    scope = resolve_scope(request, session_id)
    if not can(scope, PERM_VIEW):
        raise HTTPException(status_code=403, detail="You don't have access to this activity.")
    types = [t.strip() for t in type.split(",")] if type else None
    return {
        "scope": {"kind": scope.kind, "label": scope.label or scope.kind, "is_workspace": scope.is_workspace},
        "events": activity_service.recent(scope.owner_key or "default", types=types),
    }
