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
    max_attempts: int | None = None
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
    max_attempts: int | None = None
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
        max_attempts=body.max_attempts, secret=body.secret, enabled=body.enabled)
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


@router.get("/destinations/{dest_id}/health")
def operator_destination_health(dest_id: str, request: Request) -> dict:
    """One destination's health/SLO view: status counts, cooldown state, escalation
    eligibility, last error class, and a calm health label + reason. Operator-only."""
    _require_operator(request)
    from app.webhooks import delivery_service

    health = delivery_service.destination_health_one(dest_id)
    if health is None:
        raise HTTPException(status_code=404, detail="Destination not found.")
    return {"health": health}


@router.get("/destinations/{dest_id}/policy")
def operator_destination_policy(dest_id: str, request: Request) -> dict:
    """One destination's effective delivery-control policy: adapter, retry budget
    (with provenance), backoff class, and cooldown configuration/state."""
    _require_operator(request)
    from app.webhooks import delivery_service

    policy = delivery_service.destination_policy(dest_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Destination not found.")
    return {"policy": policy}


@router.post("/destinations/{dest_id}/cooldown/clear")
def operator_clear_cooldown(dest_id: str, request: Request) -> dict:
    """Operator recovery: clear a destination's cooldown + failure streak so it
    resumes receiving deliveries. Honest and bounded — never a silent black hole."""
    _require_operator(request)
    from app.webhooks import delivery_service

    if not delivery_service.clear_cooldown(dest_id):
        raise HTTPException(status_code=404, detail="Destination not found.")
    return {"ok": True}


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
    request: Request, status: str | None = None, destination_id: str | None = None,
    redrives: bool | None = None, limit: int = 50,
) -> dict:
    """Inspect recent delivery attempts (history) — status, attempts, last error
    class, destination name, and redrive lineage. Filter `?status=failed` for
    terminally-failed, `?redrives=true` for redrive attempts, `?destination_id=`."""
    _require_operator(request)
    from app.webhooks import delivery_service

    return {"deliveries": delivery_service.recent_deliveries(
        status=status, destination_id=destination_id, redrives=redrives, limit=limit)}


@router.get("/deliveries/{delivery_id}/lineage")
def operator_delivery_lineage(delivery_id: str, request: Request) -> dict:
    """The full redrive chain for one delivery — the original attempt plus every
    redrive, in order, each curated. Operators see history, not just the current
    dead-letter state."""
    _require_operator(request)
    from app.webhooks import delivery_service

    lineage = delivery_service.delivery_lineage(delivery_id)
    if lineage is None:
        raise HTTPException(status_code=404, detail="Delivery not found.")
    return {"lineage": lineage}


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
    scheduled worker calls the same path later). Also refreshes operator incidents:
    opens/bumps current conditions and recovers cleared ones."""
    _require_operator(request)
    from app.incidents import incident_service, signal_of
    from app.ops_policy import ops_policy
    from app.webhooks import delivery_service

    alerts = ops_policy.alerts()
    incident_service.observe(alerts)  # open/bump before routing (silence then gates)
    routing = delivery_service.route_alerts_detailed(alerts)
    result = delivery_service.deliver_pending()
    incident_service.recover_stale([signal_of(a) for a in alerts])
    try:  # best-effort: retry any pending external incident syncs
        from app.incident_sync import incident_sync_service
        incident_sync_service.flush_pending()
    except Exception:
        pass
    return {"routing": routing, **result}


# ── Operator incident workflow (acknowledge / silence / recovery) ─────────────


class IncidentNote(BaseModel):
    note: str = Field(..., max_length=280)


class SilenceBody(BaseModel):
    seconds: int | None = None


class AssignBody(BaseModel):
    # The operator-declared handle taking ownership. Service-key auth has no verified
    # identity, so this is an honest self-declared label, bounded and operator-only.
    assignee: str = Field(..., min_length=1, max_length=80)


# A relieving operator may declare who they are via this header; it is recorded as
# the actor on the action trail. Optional — never a verified identity.
_OPERATOR_NAME_HEADER = "X-Operator-Name"


def _operator_name(request: Request) -> str | None:
    try:
        raw = request.headers.get(_OPERATOR_NAME_HEADER)
    except Exception:
        raw = None
    if not raw:
        return None
    name = raw.strip()[:80]
    return name or None


def _refresh_incidents() -> None:
    """Make the incident list a live view: open/bump current conditions and recover
    cleared ones from the current policy alert set. Best-effort."""
    try:
        from app.incidents import incident_service, signal_of
        from app.ops_policy import ops_policy

        alerts = ops_policy.alerts()
        incident_service.observe(alerts)
        incident_service.recover_stale([signal_of(a) for a in alerts])
    except Exception:
        pass


@router.get("/incidents")
def operator_list_incidents(request: Request, include_recovered: bool = True, limit: int = 100) -> dict:
    """Current operator incidents (live): open / acknowledged / silenced / recovered
    for recurring operational conditions. Operator-only; curated (no internals)."""
    _require_operator(request)
    from app.incidents import incident_service

    _refresh_incidents()
    return {"incidents": incident_service.list(include_recovered=include_recovered, limit=limit)}


@router.get("/incidents/{incident_id}")
def operator_get_incident(incident_id: str, request: Request) -> dict:
    _require_operator(request)
    from app.incidents import incident_service

    incident = incident_service.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return {"incident": incident}


@router.post("/incidents/{incident_id}/ack")
def operator_ack_incident(incident_id: str, request: Request) -> dict:
    _require_operator(request)
    from app.incidents import incident_service

    incident = incident_service.acknowledge(incident_id, actor=_operator_name(request))
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return {"incident": incident}


@router.post("/incidents/{incident_id}/silence")
def operator_silence_incident(incident_id: str, body: SilenceBody, request: Request) -> dict:
    """Silence a noisy recurring condition for a BOUNDED window (capped by
    `incident_max_silence_seconds`). The incident still exists; routing for its
    signal is muted until the window elapses, then it reopens honestly if it recurs."""
    _require_operator(request)
    from app.incidents import incident_service

    incident = incident_service.silence(incident_id, seconds=body.seconds, actor=_operator_name(request))
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return {"incident": incident}


@router.post("/incidents/{incident_id}/unsilence")
def operator_unsilence_incident(incident_id: str, request: Request) -> dict:
    _require_operator(request)
    from app.incidents import incident_service

    incident = incident_service.unsilence(incident_id, actor=_operator_name(request))
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return {"incident": incident}


@router.post("/incidents/{incident_id}/assign")
def operator_assign_incident(incident_id: str, body: AssignBody, request: Request) -> dict:
    """Take/transfer ownership of an incident. The assignee is an operator-declared
    handle (bounded); re-assigning to a different handle records a `reassigned`
    event. Operator-only; recorded on the action trail."""
    _require_operator(request)
    from app.incidents import incident_service

    incident = incident_service.assign(incident_id, body.assignee, actor=_operator_name(request))
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return {"incident": incident}


@router.post("/incidents/{incident_id}/unassign")
def operator_unassign_incident(incident_id: str, request: Request) -> dict:
    _require_operator(request)
    from app.incidents import incident_service

    incident = incident_service.unassign(incident_id, actor=_operator_name(request))
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return {"incident": incident}


@router.get("/incidents/{incident_id}/history")
def operator_incident_history(incident_id: str, request: Request, limit: int = 50) -> dict:
    """The curated, ordered action trail for one incident (handoff context)."""
    _require_operator(request)
    from app.incidents import incident_service

    if incident_service.get(incident_id) is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return {"history": incident_service.history(incident_id, limit=limit)}


@router.patch("/incidents/{incident_id}")
def operator_note_incident(incident_id: str, body: IncidentNote, request: Request) -> dict:
    _require_operator(request)
    from app.incidents import incident_service

    incident = incident_service.set_note(incident_id, body.note, actor=_operator_name(request))
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return {"incident": incident}


# ── External incident sync (operator-only OUTBOUND export targets + records) ──


class IncidentTargetBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    url: str = Field(..., min_length=1, max_length=500)
    kind: str = Field(default="generic", max_length=24)
    sync_actions: str | None = Field(default=None, max_length=255)
    secret: str | None = Field(default=None, max_length=255)
    enabled: bool = True


class IncidentTargetUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    url: str | None = Field(default=None, max_length=500)
    kind: str | None = Field(default=None, max_length=24)
    sync_actions: str | None = Field(default=None, max_length=255)
    secret: str | None = Field(default=None, max_length=255)
    enabled: bool | None = None


@router.get("/incident-targets")
def operator_list_incident_targets(request: Request) -> dict:
    """Configured outbound incident-sync targets (curated; secrets never returned)."""
    _require_operator(request)
    from app.incident_sync import incident_sync_service

    return {"targets": incident_sync_service.list_targets()}


@router.post("/incident-targets")
def operator_create_incident_target(body: IncidentTargetBody, request: Request) -> dict:
    _require_operator(request)
    from app.incident_sync import incident_sync_service

    target = incident_sync_service.create_target(
        name=body.name, url=body.url, kind=body.kind,
        sync_actions=body.sync_actions, secret=body.secret, enabled=body.enabled)
    if target is None:
        raise HTTPException(status_code=400, detail="Invalid target (name, http(s) url, and known kind required).")
    return {"target": target}


@router.patch("/incident-targets/{target_id}")
def operator_update_incident_target(target_id: str, body: IncidentTargetUpdate, request: Request) -> dict:
    _require_operator(request)
    from app.incident_sync import incident_sync_service

    target = incident_sync_service.update_target(target_id, **body.model_dump(exclude_none=True))
    if target is None:
        raise HTTPException(status_code=404, detail="Target not found or invalid update.")
    return {"target": target}


@router.delete("/incident-targets/{target_id}")
def operator_delete_incident_target(target_id: str, request: Request) -> dict:
    _require_operator(request)
    from app.incident_sync import incident_sync_service

    if not incident_sync_service.delete_target(target_id):
        raise HTTPException(status_code=404, detail="Target not found.")
    return {"ok": True}


@router.get("/incident-sync")
def operator_list_incident_sync(request: Request, status: str | None = None,
                                incident_id: str | None = None, limit: int = 50) -> dict:
    """Recent incident-sync attempts (curated). Filter by status / incident."""
    _require_operator(request)
    from app.incident_sync import incident_sync_service

    return {"records": incident_sync_service.list_records(status=status, incident_id=incident_id, limit=limit)}


@router.get("/incident-sync/drift")
def operator_incident_sync_drift(request: Request, limit: int = 50) -> dict:
    """Operator triage list: externally-linked incidents whose reconciliation verdict
    is actionable (drifted / missing_external / stale). Declared before the
    `/{record_id}` route so "drift" is not parsed as a record id."""
    _require_operator(request)
    from app.incident_sync import incident_sync_service

    return {"links": incident_sync_service.drifted(limit=limit)}


@router.get("/incident-sync/{record_id}")
def operator_get_incident_sync(record_id: str, request: Request) -> dict:
    _require_operator(request)
    from app.incident_sync import incident_sync_service

    record = incident_sync_service.get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Sync record not found.")
    return {"record": record}


@router.post("/incident-sync/{record_id}/redrive")
def operator_redrive_incident_sync(record_id: str, request: Request) -> dict:
    """Operator redrive of a terminal-failed incident sync (bounded, idempotent)."""
    _require_operator(request)
    from app.incident_sync import incident_sync_service

    result = incident_sync_service.redrive(record_id)
    if not result.get("ok") and result.get("message") == "Sync record not found.":
        raise HTTPException(status_code=404, detail=result["message"])
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("message", "Cannot redrive."))
    return result


@router.get("/incidents/{incident_id}/sync")
def operator_incident_sync_status(incident_id: str, request: Request) -> dict:
    """Per-incident external sync health + linkage (curated): durable external
    links, recent attempts, and an honest reconciliation summary (linked / behind /
    stale / drifted / missing / recovered)."""
    _require_operator(request)
    from app.incidents import incident_service
    from app.incident_sync import incident_sync_service

    incident = incident_service.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return incident_sync_service.incident_sync_status(incident_id, incident_state=incident.get("state"))


@router.post("/incidents/{incident_id}/sync/refresh")
def operator_incident_sync_refresh(incident_id: str, request: Request) -> dict:
    """Bounded inbound recheck of the incident's external links (only adapters that
    support it). Updates last-observed external status/existence — never mutates the
    local incident. 409 if the incident has no external links to refresh."""
    _require_operator(request)
    from app.incidents import incident_service
    from app.incident_sync import incident_sync_service

    incident = incident_service.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    refreshed = incident_sync_service.refresh(incident_id, incident_state=incident.get("state"))
    if refreshed is None:
        raise HTTPException(status_code=409, detail="Incident has no external links to refresh.")
    return refreshed


@router.get("/incident-targets/{target_id}/health")
def operator_incident_target_health(target_id: str, request: Request) -> dict:
    """Curated health for one sync target (recent attempt mix + last success/fail)."""
    _require_operator(request)
    from app.incident_sync import incident_sync_service

    health = incident_sync_service.target_health(target_id)
    if health is None:
        raise HTTPException(status_code=404, detail="Target not found.")
    return {"target": health}
