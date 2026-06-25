# File: backend/app/routes/resources.py
"""
Recent shared resources for the active scope — one clean, permission-aware read.

  GET /resources/recent  -> { scope, artifacts, documents, runs }

Resolves the active scope exactly like a turn (account-first; a workspace header
is honoured only for members). Reading shared resources needs `view`, which every
scope grants, so a viewer can discover/download while a non-member silently gets
their personal scope — never another team's data. Returns only minimal, clean
metadata: no owner keys, raw rows, or trace internals.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.auth import resolve_scope
from app.authz import PERM_VIEW, can
from app.db.database import get_db
from app.shared_resources import shared_resource_service
from fastapi import Depends
from sqlalchemy.orm import Session

router = APIRouter(prefix="/resources", tags=["AIRA-X Resources"])


@router.get("/recent")
def recent_resources(
    request: Request,
    session_id: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    scope = resolve_scope(request, session_id)
    if not can(scope, PERM_VIEW):  # safety net — view is granted in every real scope
        raise HTTPException(status_code=403, detail="You don't have access to these resources.")
    owner = scope.owner_key or "default"
    return {
        "scope": {"kind": scope.kind, "label": scope.label or scope.kind, "is_workspace": scope.is_workspace},
        "artifacts": shared_resource_service.recent_artifacts(owner),
        "documents": shared_resource_service.recent_documents(owner, db),
        "runs": shared_resource_service.recent_runs(owner),
    }
