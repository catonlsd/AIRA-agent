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
