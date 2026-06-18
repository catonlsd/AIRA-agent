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


# ── Inspection (operator-only, curated — never a raw dump) ────────────────────


@router.get("/jobs")
def operator_list_jobs(
    request: Request,
    status: str | None = None,
    origin: str | None = None,
    kind: str | None = None,
    failures: bool = False,
    limit: int = 25,
) -> dict:
    """Find the right job to inspect — by status / origin (normal/retry/replay) /
    kind, or recent failures. A minimal locator, not an admin search console."""
    _require_operator(request)
    from app.operator_inspect import support_inspection

    return {"jobs": support_inspection.list_jobs(
        status=status, origin=origin, kind=kind, failures=failures, limit=limit)}


@router.get("/jobs/{job_id}")
def operator_job_view(job_id: str, request: Request) -> dict:
    """A curated operator view of one job: summary, current/terminal phase, retry/
    replay lineage, summarized failure class, and safe artifact references."""
    _require_operator(request)
    from app.operator_inspect import support_inspection

    view = support_inspection.job_view(job_id)
    if view is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"job": view}


@router.get("/jobs/{job_id}/timeline")
def operator_job_timeline(job_id: str, request: Request) -> dict:
    """A curated, ordered timeline correlating lifecycle, activity, and lineage."""
    _require_operator(request)
    from app.operator_inspect import support_inspection

    timeline = support_inspection.job_timeline(job_id)
    if timeline is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"job_id": job_id, "timeline": timeline}


@router.get("/runs/{run_id}")
def operator_run_view(run_id: str, request: Request) -> dict:
    """A curated operator view of one inline run, from its persisted trace —
    friendly label, status, source, and curated stage names (no raw payloads)."""
    _require_operator(request)
    from app.operator_inspect import support_inspection

    view = support_inspection.run_view(run_id)
    if view is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return {"run": view}


@router.get("/runs/{run_id}/timeline")
def operator_run_timeline(run_id: str, request: Request) -> dict:
    """A curated, ordered run timeline: turn start, stage progression, outcome,
    and correlated activity — never a raw trace-event dump."""
    _require_operator(request)
    from app.operator_inspect import support_inspection

    timeline = support_inspection.run_timeline(run_id)
    if timeline is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return {"run_id": run_id, "timeline": timeline}


# ── Observability export + failure triage (operator-only) ─────────────────────


@router.get("/observability")
def operator_observability(
    request: Request,
    since: int | None = None,
    type: str | None = None,
    limit: int = 100,
) -> dict:
    """Curated, cursor-based export of the operational signal stream — the seam for
    external dashboards/alerting. Poll `?since=<cursor>` for incremental export;
    the response carries the next `cursor`. Bounded; never raw payloads/traces."""
    _require_operator(request)
    from app.observability import observability

    types = [t.strip() for t in type.split(",") if t.strip()] if type else None
    return observability.recent(since=since, limit=limit, types=types)


@router.get("/triage")
def operator_triage(request: Request, limit: int = 25) -> dict:
    """Curated terminal-failed jobs needing attention, classified honestly
    (retry_exhausted / replay_candidate / in_progress / resolved) with lineage —
    the dead-letter / failure-triage foundation. Operator-only."""
    _require_operator(request)
    from app.observability import observability

    return {"triage": observability.triage(limit=limit)}
