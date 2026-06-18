# File: backend/app/routes/operator.py
"""
Operator endpoints — a clean, gated boundary for service/operator tooling.

Distinct from normal account/workspace users: these require the configured
service API key (an operator principal), not an account token. No dashboard, no
admin maze — just one honest, authorized visibility endpoint and a seam where
future support/audit/policy-override tooling can live without muddying user
roles. When no API key is configured (local dev), there is no operator and these
paths are simply unavailable.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.auth import resolve_operator_principal
from app.db.database import SessionLocal
from app.db.models import Account, Workspace

router = APIRouter(prefix="/operator", tags=["AIRA-X Operator"])


def _require_operator(request: Request) -> None:
    if resolve_operator_principal(request) is None:
        raise HTTPException(status_code=403, detail="Operator access required.")


@router.get("/overview")
def operator_overview(request: Request) -> dict:
    """Minimal operator visibility: durable-resource counts. No PII, no content."""
    _require_operator(request)
    with SessionLocal() as session:
        return {
            "accounts": session.query(Account).count(),
            "workspaces": session.query(Workspace).count(),
        }


@router.post("/jobs/{job_id}/replay")
def operator_replay_job(job_id: str, request: Request) -> dict:
    """Operator-safe replay: re-run any execution job (even a completed one) as a
    fresh attempt linked via `origin=replay`, preserving the job's own scope. This
    is the gated seam for support/audit replay — never exposed to normal users, so
    no operator control leaks into the product UI. Idempotent per operator."""
    _require_operator(request)
    from app.execution_queue import execution_queue

    job = execution_queue.replay(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"job": job}
