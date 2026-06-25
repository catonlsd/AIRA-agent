# File: backend/app/routes/jobs.py
"""
Background job status — reconnect-safe, scope-aware, calm (not a job console).

  GET  /jobs            -> { scope, jobs }       recent jobs in the active scope
  GET  /jobs/{id}       -> { scope, job }        one job's clean status
  POST /jobs/{id}/cancel-> { ok, status, message } honest, cooperative cancel
  POST /jobs/{id}/retry -> { ok, job | message }   real new attempt of a failed job

So a client that disconnected mid-generation can reconnect and ask "is it done?"
without a polling console. Every route resolves the active scope like a turn
(account-first; workspace header member-only). Reading needs `view`; an
inaccessible job is a plain 404 (its existence never leaks). Cancel/retry mutate a
shared run, so they need `edit` (a personal user always can). Cancel is honest: a
queued job cancels outright, a running one stops at the worker's next safe
checkpoint, and an already-finished job is told the truth. Retry of a failed job
schedules a real new attempt (idempotent). Payloads are UI-ready only — status,
progress, and a clean result (title / download / error) — never worker ids, queue
internals, payloads, or owner keys. Operator replay lives behind `/operator/*`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.auth import resolve_scope
from app.authz import PERM_EDIT, PERM_VIEW, can
from app.execution_queue import execution_queue
from app.live_status import enrich_phase, live_status_service

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
    jobs = [enrich_phase(j) for j in execution_queue.recent(owner, active_only=active)]
    return {"scope": _scope_dict(scope), "jobs": jobs}


@router.get("/live")
def live_jobs(
    request: Request,
    session_id: str | None = None,
) -> dict:
    """Reconnect-safe: the active (non-terminal) work in this scope, as unified
    live-status snapshots — what a reloaded client lists to restore the live view."""
    scope = _scope_or_403(request, session_id, PERM_VIEW)
    owner = scope.owner_key or "default"
    return {"scope": _scope_dict(scope), "live": live_status_service.active(owner)}


@router.get("/{job_id}")
def get_job(
    job_id: str,
    request: Request,
    session_id: str | None = None,
) -> dict:
    scope = _scope_or_403(request, session_id, PERM_VIEW)
    owner = scope.owner_key or "default"
    job = enrich_phase(execution_queue.get(owner, job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found in this scope.")
    return {"scope": _scope_dict(scope), "job": job}


@router.get("/{job_id}/live")
def get_job_live(
    job_id: str,
    request: Request,
    session_id: str | None = None,
) -> dict:
    """Reconnect-safe snapshot for one job — resume the right phase after a reload,
    or resolve honestly to the terminal state if it already finished."""
    scope = _scope_or_403(request, session_id, PERM_VIEW)
    owner = scope.owner_key or "default"
    snapshot = live_status_service.snapshot(owner, job_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Job not found in this scope.")
    return {"scope": _scope_dict(scope), "live": snapshot}


@router.post("/{job_id}/cancel")
def cancel_job(
    job_id: str,
    request: Request,
    session_id: str | None = None,
) -> dict:
    scope = _scope_or_403(request, session_id, PERM_EDIT)
    owner = scope.owner_key or "default"
    result = execution_queue.request_cancel(owner, job_id)
    if result.get("not_found"):
        raise HTTPException(status_code=404, detail="Job not found in this scope.")
    return result


@router.post("/{job_id}/retry")
def retry_job(
    job_id: str,
    request: Request,
    session_id: str | None = None,
) -> dict:
    scope = _scope_or_403(request, session_id, PERM_EDIT)
    owner = scope.owner_key or "default"
    result = execution_queue.retry(owner, job_id)
    if result.get("not_found"):
        raise HTTPException(status_code=404, detail="Job not found in this scope.")
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("message", "Cannot retry this job."))
    return {"scope": _scope_dict(scope), **result}
