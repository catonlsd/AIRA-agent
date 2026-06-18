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
from pydantic import BaseModel, Field

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


# ── SLO / health policy + alert-ready classifications (operator-only) ──────────


@router.get("/health")
def operator_health(request: Request, limit: int = 200) -> dict:
    """A bounded operational-policy snapshot: per-job health classifications for
    recent active + terminal-failed work, per-class backlog pressure, and a summary
    count. Derived from durable timestamps/state — not raw log scraping."""
    _require_operator(request)
    from app.ops_policy import ops_policy

    return ops_policy.health(limit=limit)


@router.get("/alerts")
def operator_alerts(request: Request, limit: int = 200) -> dict:
    """Alert-ready policy results: only warning/critical conditions — stuck jobs
    (queued/running/cancel past their SLO), retry-exhausted failures, and backlog
    pressure — bounded and curated for external alert routing. Operator-only."""
    _require_operator(request)
    from app.ops_policy import ops_policy

    return {"alerts": ops_policy.alerts(limit=limit)}


# ── External delivery: webhook destinations + deliveries (operator-only) ──────


class DestinationBody(BaseModel):
    name: str = Field(..., max_length=120)
    url: str = Field(..., max_length=500)
    kind: str = Field(default="webhook", max_length=24)
    subscription: str = Field(default="alerts", max_length=16)
    min_severity: str = Field(default="warning", max_length=16)
    event_filter: str | None = Field(default=None, max_length=255)
    alert_filter: str | None = Field(default=None, max_length=255)
    origin_filter: str | None = Field(default=None, max_length=64)
    suppress_seconds: int | None = None
    escalate_after: int | None = None
    secret: str | None = Field(default=None, max_length=255)
    enabled: bool = True


class DestinationUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    kind: str | None = None
    enabled: bool | None = None
    subscription: str | None = None
    min_severity: str | None = None
    event_filter: str | None = None
    alert_filter: str | None = None
    origin_filter: str | None = None
    suppress_seconds: int | None = None
    escalate_after: int | None = None
    secret: str | None = None


@router.post("/destinations")
def operator_create_destination(body: DestinationBody, request: Request) -> dict:
    """Configure an external delivery target (webhook). Operator-only; the signing
    secret is stored but NEVER returned by any read API."""
    _require_operator(request)
    from app.webhooks import delivery_service

    dest = delivery_service.create_destination(
        name=body.name, url=body.url, kind=body.kind, subscription=body.subscription,
        min_severity=body.min_severity, event_filter=body.event_filter,
        alert_filter=body.alert_filter, origin_filter=body.origin_filter,
        suppress_seconds=body.suppress_seconds, escalate_after=body.escalate_after,
        secret=body.secret, enabled=body.enabled)
    if dest is None:
        raise HTTPException(status_code=400, detail="Invalid destination (url/kind/subscription/severity/filters/escalation).")
    return {"destination": dest}


@router.get("/destinations")
def operator_list_destinations(request: Request) -> dict:
    _require_operator(request)
    from app.webhooks import delivery_service

    return {"destinations": delivery_service.list_destinations()}


@router.get("/destinations/{dest_id}/routing")
def operator_destination_routing(dest_id: str, request: Request) -> dict:
    """Effective routing config for one destination + a dry-run of the CURRENT
    alert set against it: per alert, would it route / suppress / skip, and why.
    Explains delivery decisions without DB spelunking. Creates no deliveries."""
    _require_operator(request)
    from app.ops_policy import ops_policy
    from app.webhooks import delivery_service

    preview = delivery_service.routing_preview(dest_id, ops_policy.alerts())
    if preview is None:
        raise HTTPException(status_code=404, detail="Destination not found.")
    return preview


@router.get("/delivery/analytics")
def operator_delivery_analytics(request: Request, since_minutes: int = 60) -> dict:
    """A compact delivery summary: attempted/delivered/failed/pending/redriven
    totals, durable routing counters (routed/suppressed/skipped + escalation
    destinations), and breakdowns by adapter kind and destination. Operator-only."""
    _require_operator(request)
    from app.webhooks import delivery_service

    return delivery_service.analytics(since_minutes=since_minutes)


@router.get("/delivery/health")
def operator_delivery_health(request: Request) -> dict:
    """Per-destination health: status counts, redrive outcome, durable routing
    counters, last error class, and a calm health label. Operator-only."""
    _require_operator(request)
    from app.webhooks import delivery_service

    return {"destinations": delivery_service.destination_health()}


@router.patch("/destinations/{dest_id}")
def operator_update_destination(dest_id: str, body: DestinationUpdate, request: Request) -> dict:
    _require_operator(request)
    from app.webhooks import delivery_service

    dest = delivery_service.update_destination(dest_id, **body.model_dump(exclude_none=True))
    if dest is None:
        raise HTTPException(status_code=404, detail="Destination not found or invalid update.")
    return {"destination": dest}


@router.delete("/destinations/{dest_id}")
def operator_delete_destination(dest_id: str, request: Request) -> dict:
    _require_operator(request)
    from app.webhooks import delivery_service

    return {"ok": delivery_service.delete_destination(dest_id)}


@router.get("/deliveries")
def operator_list_deliveries(
    request: Request, status: str | None = None, destination_id: str | None = None, limit: int = 50,
) -> dict:
    """Inspect recent delivery attempts — status, attempts, last error class, and
    redrive lineage. Filter `?status=failed` for terminally-failed deliveries."""
    _require_operator(request)
    from app.webhooks import delivery_service

    return {"deliveries": delivery_service.recent_deliveries(
        status=status, destination_id=destination_id, limit=limit)}


@router.get("/deliveries/dead-letters")
def operator_dead_letters(request: Request, limit: int = 50) -> dict:
    """Terminal-failed deliveries needing attention, classified from redrive
    lineage (redrive_candidate / redriven / resolved / exhausted) with source +
    destination correlation. The dead-letter view — recover without DB surgery."""
    _require_operator(request)
    from app.webhooks import delivery_service

    return {"dead_letters": delivery_service.dead_letters(limit=limit)}


@router.post("/deliveries/{delivery_id}/redrive")
def operator_redrive_delivery(delivery_id: str, request: Request) -> dict:
    """Redrive a terminal-failed delivery — a real new attempt linked via
    `redrive_of`, bounded and idempotent. Separate from job retry/replay and from
    automatic delivery retry."""
    _require_operator(request)
    from app.webhooks import delivery_service

    result = delivery_service.redrive(delivery_id)
    if result.get("not_found"):
        raise HTTPException(status_code=404, detail="Delivery not found.")
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("message", "Cannot redrive this delivery."))
    return result


@router.get("/deliveries/{delivery_id}")
def operator_get_delivery(delivery_id: str, request: Request) -> dict:
    _require_operator(request)
    from app.webhooks import delivery_service

    delivery = delivery_service.get_delivery(delivery_id)
    if delivery is None:
        raise HTTPException(status_code=404, detail="Delivery not found.")
    return {"delivery": delivery}


@router.post("/deliveries/sweep")
def operator_deliveries_sweep(request: Request) -> dict:
    """Route current alert-worthy policy results to subscribed destinations, then
    flush pending deliveries. The manual trigger for the delivery foundation (a
    scheduled worker calls the same path later). Returns routing + delivery counts."""
    _require_operator(request)
    from app.ops_policy import ops_policy
    from app.webhooks import delivery_service

    routing = delivery_service.route_alerts_detailed(ops_policy.alerts())
    result = delivery_service.deliver_pending()
    return {"routing": routing, **result}
