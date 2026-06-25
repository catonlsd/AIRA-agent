# File: backend/app/routes/runs.py
"""
Scoped run history + chat-native continuation — "pick up where we left off".

  GET  /runs/recent          -> { scope, runs }   recent runs in the active scope
  GET  /runs/{run_id}         -> { scope, run }    one run's clean summary
  POST /runs/{run_id}/continue-> { scope, mode, prompt, run_id }  prepared turn

Resolves the active scope exactly like a turn (account-first; a workspace header
is honoured only for members), so personal runs stay personal, workspace runs are
visible to authorized members, and a non-member silently falls back to their own
scope — never another team's runs. Reading needs `view`; continuation re-checks
that the run is accessible in *this* scope, so an inaccessible run is simply
"not found" and its existence never leaks.

Continuation is chat-first: it returns the exact prompt the client sends as a
normal turn — `resume` claims a pending flow, `continue` seeds an on-topic build,
`retry` re-runs a failed goal. No separate execution subsystem, no internals.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth import resolve_scope
from app.authz import PERM_VIEW, can
from app.db.database import get_db
from app.run_history import run_history_service

router = APIRouter(prefix="/runs", tags=["AIRA-X Runs"])


def _scope_or_403(request: Request, session_id: str | None):
    scope = resolve_scope(request, session_id)
    if not can(scope, PERM_VIEW):  # safety net — view is granted in every real scope
        raise HTTPException(status_code=403, detail="You don't have access to these runs.")
    return scope


def _scope_dict(scope) -> dict:
    return {"kind": scope.kind, "label": scope.label or scope.kind, "is_workspace": scope.is_workspace}


@router.get("/recent")
def recent_runs(
    request: Request,
    session_id: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    scope = _scope_or_403(request, session_id)
    owner = scope.owner_key or "default"
    return {"scope": _scope_dict(scope), "runs": run_history_service.recent(owner, db=db)}


@router.get("/{run_id}")
def get_run(
    run_id: str,
    request: Request,
    session_id: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    scope = _scope_or_403(request, session_id)
    owner = scope.owner_key or "default"
    run = run_history_service.get(owner, run_id, db=db)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found in this scope.")
    return {"scope": _scope_dict(scope), "run": run}


@router.post("/{run_id}/continue")
def continue_run(
    run_id: str,
    request: Request,
    session_id: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    scope = _scope_or_403(request, session_id)
    owner = scope.owner_key or "default"
    prepared = run_history_service.continuation_for(owner, run_id, db=db)
    if prepared is None:
        raise HTTPException(status_code=404, detail="Run not found in this scope.")
    return {"scope": _scope_dict(scope), **prepared}
