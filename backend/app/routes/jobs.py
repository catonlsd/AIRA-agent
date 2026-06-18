# File: backend/app/routes/jobs.py
"""
Background job status — reconnect-safe, scope-aware, calm (not a job console).

  GET  /jobs            -> { scope, jobs }     recent jobs in the active scope
  GET  /jobs/{id}       -> { scope, job }      one job's clean status
  POST /jobs/{id}/cancel-> { ok }              request cancellation

So a client that disconnected mid-generation can reconnect and ask "is it done?"
without a polling console. Every route resolves the active scope like a turn
(account-first; workspace header member-only). Reading needs `view`; an
inaccessible job is a plain 404 (its existence never leaks). Cancelling mutates a
shared run, so it needs `edit` (a personal user always can). Payloads are
UI-ready only — status, progress, and a clean result (title / download / error) —
never worker ids, queue internals, payloads, or owner keys.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.auth import resolve_scope
from app.authz import PERM_EDIT, PERM_VIEW, can
from app.execution_queue import execution_queue

router = APIRouter(prefix="/jobs", tags=["AIRA-X Jobs"])


def _scope_dict(scope) -> dict:
    return {"kind": scope.kind, "label": scope.label or scope.kind, "is_workspace": scope.is_workspace}


def _scope_or_403(request: Request, session_id: str | None, perm: str):
    scope = resolve_scope(request, session_id)
    if not can(scope, perm):
        raise HTTPException(status_code=403, detail="You don't have access in this scope.")
    return scope


@router.get("")
def list_jobs(
    request: Request,
    session_id: str | None = None,
    active: bool = False,
) -> dict:
    scope = _scope_or_403(request, session_id, PERM_VIEW)
    owner = scope.owner_key or "default"
    return {"scope": _scope_dict(scope), "jobs": execution_queue.recent(owner, active_only=active)}


@router.get("/{job_id}")
def get_job(
    job_id: str,
    request: Request,
    session_id: str | None = None,
) -> dict:
    scope = _scope_or_403(request, session_id, PERM_VIEW)
    owner = scope.owner_key or "default"
    job = execution_queue.get(owner, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found in this scope.")
    return {"scope": _scope_dict(scope), "job": job}


@router.post("/{job_id}/cancel")
def cancel_job(
    job_id: str,
    request: Request,
    session_id: str | None = None,
) -> dict:
    scope = _scope_or_403(request, session_id, PERM_EDIT)
    owner = scope.owner_key or "default"
    return {"ok": execution_queue.cancel_request(owner, job_id)}
