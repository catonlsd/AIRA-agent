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

from app.auth import require_operator_principal
from app.db.database import SessionLocal
from app.db.models import Account, Workspace

router = APIRouter(prefix="/operator", tags=["AIRA-X Operator"])


def _require_operator(request: Request) -> None:
    require_operator_principal(request)


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
    try:  # best-effort: retry pending syncs + reconcile stale links + revalidate targets
        from app.incident_sync import incident_sync_service
        incident_sync_service.flush_pending()
        incident_sync_service.reconcile()
        incident_sync_service.revalidate_stale()
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
    # Onboard from a profile/preset (G-14). When set it determines the adapter kind.
    profile: str | None = Field(default=None, max_length=40)
    sync_actions: str | None = Field(default=None, max_length=255)
    secret: str | None = Field(default=None, max_length=255)
    enabled: bool = True


class IncidentTargetUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    url: str | None = Field(default=None, max_length=500)
    kind: str | None = Field(default=None, max_length=24)
    profile: str | None = Field(default=None, max_length=40)  # switch the target's profile (G-14)
    sync_actions: str | None = Field(default=None, max_length=255)
    secret: str | None = Field(default=None, max_length=255)
    enabled: bool | None = None
    # Per-target action policy overrides (G-12). Tri-state at the model layer too —
    # null leaves it unchanged; True/False sets the explicit override (still bounded
    # by adapter capability when an action is actually invoked).
    allow_apply_resolved: bool | None = None
    allow_apply_missing: bool | None = None
    allow_external_resolve: bool | None = None
    allow_external_reopen: bool | None = None
    allow_external_acknowledge: bool | None = None
    allow_push_outward: bool | None = None
    # Per-target INBOUND-field visibility overrides (G-13).
    allow_external_assignee: bool | None = None
    allow_external_severity: bool | None = None
    allow_external_updated_at: bool | None = None
    allow_external_comment_count: bool | None = None
    allow_external_suggestions: bool | None = None


class SyncDetachBody(BaseModel):
    target_id: str = Field(..., min_length=1, max_length=36)


class SyncRelinkBody(BaseModel):
    target_id: str = Field(..., min_length=1, max_length=36)
    external_ref: str = Field(..., min_length=1, max_length=120)
    external_url: str | None = Field(default=None, max_length=500)


class SyncApplyBody(BaseModel):
    # Explicit local-vs-external resolution chosen by the operator.
    action: str = Field(..., pattern="^(accept_resolved|accept_missing)$")


class SyncPushBody(BaseModel):
    target_id: str | None = Field(default=None, max_length=36)


class SyncExternalActionBody(BaseModel):
    # Vendor-typed external action (effect: external only; never changes local state).
    action: str = Field(..., pattern="^(external_resolve|external_reopen|external_acknowledge)$")
    target_id: str | None = Field(default=None, max_length=36)


class RotateSecretBody(BaseModel):
    # The new signing secret (omit/null to clear it). Never returned by read APIs.
    secret: str | None = Field(default=None, max_length=255)


@router.get("/incident-target-profiles")
def operator_list_incident_target_profiles(request: Request) -> dict:
    """Available adapter profiles/presets an operator can onboard a target from (G-14):
    each with kind, support level, human summary, and default inbound/outbound policy."""
    _require_operator(request)
    from app.incident_sync import list_profiles

    return {"profiles": list_profiles()}


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
        name=body.name, url=body.url, kind=body.kind, profile=body.profile,
        sync_actions=body.sync_actions, secret=body.secret, enabled=body.enabled)
    if target is None:
        raise HTTPException(status_code=400,
                            detail="Invalid target (name, http(s) url, and a known kind/profile required).")
    return {"target": target}


@router.patch("/incident-targets/{target_id}")
def operator_update_incident_target(target_id: str, body: IncidentTargetUpdate, request: Request) -> dict:
    _require_operator(request)
    from app.incident_sync import incident_sync_service

    target = incident_sync_service.update_target(target_id, _actor=_operator_name(request),
                                                 **body.model_dump(exclude_none=True))
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


@router.get("/incident-sync/metrics")
def operator_incident_sync_metrics(request: Request) -> dict:
    """Bounded, deterministic observability for incident sync — readiness distribution,
    windowed (24h/7d/30d) validation/reconciliation/refresh/apply/external-action/sync
    rollups, a drift snapshot, SLO percentages, and candidate-alert observations. All
    computed on read from existing audit/history. Observe-only; declared before
    `/{record_id}` so "metrics" is not parsed as a record id."""
    _require_operator(request)
    from app.incident_sync import incident_sync_service

    return incident_sync_service.incident_metrics()


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


@router.get("/incidents/{incident_id}/sync/actions")
def operator_incident_sync_actions(incident_id: str, request: Request) -> dict:
    """Per-action availability + EFFECT (local / linkage / external / none) for this
    incident — curated for the console so action gating lives in one place. Each
    entry says exactly what an action will change before the operator clicks."""
    _require_operator(request)
    from app.incidents import incident_service
    from app.incident_sync import incident_sync_service

    incident = incident_service.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return {"actions": incident_sync_service.incident_actions(incident_id, incident_state=incident.get("state"))}


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
    refreshed = incident_sync_service.refresh(incident_id, incident_state=incident.get("state"),
                                              actor=_operator_name(request))
    if refreshed is None:
        raise HTTPException(status_code=409, detail="Incident has no external links to refresh.")
    return refreshed


@router.post("/incidents/{incident_id}/sync/redrive")
def operator_incident_sync_redrive(incident_id: str, request: Request) -> dict:
    """Redrive the most recent failed external sync for this incident, from its
    context. 404 if the incident is unknown, 409 if there is nothing to redrive."""
    _require_operator(request)
    from app.incidents import incident_service
    from app.incident_sync import incident_sync_service

    if incident_service.get(incident_id) is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    result = incident_sync_service.redrive_incident_latest(incident_id)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("message", "Cannot redrive."))
    return result


@router.post("/incidents/{incident_id}/sync/detach")
def operator_incident_sync_detach(incident_id: str, body: SyncDetachBody, request: Request) -> dict:
    """Intentionally detach a bad/missing external link (preserved for lineage,
    excluded from drift). Local incident state is untouched."""
    _require_operator(request)
    from app.incidents import incident_service
    from app.incident_sync import incident_sync_service

    incident = incident_service.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    status = incident_sync_service.detach(incident_id, body.target_id,
                                          actor=_operator_name(request), incident_state=incident.get("state"))
    if status is None:
        raise HTTPException(status_code=404, detail="No external link for that target.")
    return status


@router.post("/incidents/{incident_id}/sync/relink")
def operator_incident_sync_relink(incident_id: str, body: SyncRelinkBody, request: Request) -> dict:
    """Repair/establish an external link to a known reference, VALIDATED through the
    adapter. Refused honestly if the adapter is outbound-only or the reference can't
    be verified. Local incident state is untouched."""
    _require_operator(request)
    from app.incidents import incident_service
    from app.incident_sync import incident_sync_service

    incident = incident_service.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    result = incident_sync_service.relink(incident_id, body.target_id, body.external_ref,
                                          external_url=body.external_url, actor=_operator_name(request),
                                          incident_state=incident.get("state"))
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("message", "Relink refused."))
    return result


@router.post("/incidents/{incident_id}/sync/apply")
def operator_incident_sync_apply(incident_id: str, body: SyncApplyBody, request: Request) -> dict:
    """EXPLICITLY apply observed external state to the local side — the only path that
    may change local incident state from an external observation. Bounded to the cases
    the disagreement supports (accept_resolved → local recovery; accept_missing →
    detach). Refused (409) when not currently applicable."""
    _require_operator(request)
    from app.incidents import incident_service
    from app.incident_sync import incident_sync_service

    if incident_service.get(incident_id) is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    result = incident_sync_service.apply_from_external(incident_id, body.action, actor=_operator_name(request))
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("message", "Cannot apply."))
    return result


@router.post("/incidents/{incident_id}/sync/push")
def operator_incident_sync_push(incident_id: str, body: SyncPushBody, request: Request) -> dict:
    """EXPLICITLY re-send the current local incident state outward to push-capable
    targets (e.g. push a local recovery so the external incident resolves). Targets
    whose adapter can't push are skipped; never changes local state."""
    _require_operator(request)
    from app.incidents import incident_service
    from app.incident_sync import incident_sync_service

    incident = incident_service.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    result = incident_sync_service.push_outward(incident_id, target_id=body.target_id,
                                                actor=_operator_name(request), incident=incident)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("message", "Cannot push."))
    return result


@router.post("/incidents/{incident_id}/sync/external-action")
def operator_incident_sync_external_action(incident_id: str, body: SyncExternalActionBody, request: Request) -> dict:
    """Invoke a richer VENDOR-TYPED external action (resolve / reopen / acknowledge),
    gated by adapter capability AND per-target policy. Effect is strictly external —
    local incident state is never changed. 409 when capability/policy/state refuse it."""
    _require_operator(request)
    from app.incidents import incident_service
    from app.incident_sync import incident_sync_service

    incident = incident_service.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    result = incident_sync_service.external_action(incident_id, body.action, target_id=body.target_id,
                                                   actor=_operator_name(request), incident=incident)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("message", "Cannot perform external action."))
    return result


@router.post("/incident-sync/reconcile")
def operator_incident_sync_reconcile(request: Request, limit: int | None = None) -> dict:
    """Bounded scheduled reconciliation: recheck the active, refresh-capable links
    that most need it (stale / never-checked), capped per sweep. Operator-triggered;
    the same path a scheduled worker can call later."""
    _require_operator(request)
    from app.incident_sync import incident_sync_service

    return {"reconciled": incident_sync_service.reconcile(max_incidents=limit, actor=_operator_name(request))}


@router.get("/incident-targets/{target_id}/health")
def operator_incident_target_health(target_id: str, request: Request) -> dict:
    """Curated health for one sync target (recent attempt mix + last success/fail) +
    durable readiness (state / source / last validated / tested / failure)."""
    _require_operator(request)
    from app.incident_sync import incident_sync_service

    health = incident_sync_service.target_health(target_id)
    if health is None:
        raise HTTPException(status_code=404, detail="Target not found.")
    return {"target": health}


@router.post("/incident-targets/{target_id}/validate")
def operator_incident_target_validate(target_id: str, request: Request) -> dict:
    """Run bounded PREFLIGHT validation (config + profile compatibility + policy +
    secret sanity + a real connectivity probe for refresh-capable adapters). Records
    durable evidence; never touches a real incident or local state."""
    _require_operator(request)
    from app.incident_sync import incident_sync_service

    result = incident_sync_service.validate(target_id, actor=_operator_name(request))
    if result is None:
        raise HTTPException(status_code=404, detail="Target not found.")
    return result


@router.post("/incident-targets/{target_id}/test")
def operator_incident_target_test(target_id: str, request: Request) -> dict:
    """Send ONE bounded, clearly-synthetic test event through the real adapter
    transport (a no-op vendor resolve of a synthetic ref). Never creates/mutates a
    real incident or writes incident history. 409 for disabled/invalid targets."""
    _require_operator(request)
    from app.incident_sync import incident_sync_service

    result = incident_sync_service.test_send(target_id, actor=_operator_name(request))
    if result is None:
        raise HTTPException(status_code=404, detail="Target not found.")
    if not result.get("ok") and result.get("code") in ("disabled", "invalid_config"):
        raise HTTPException(status_code=409, detail=result.get("message", "Cannot test this target."))
    return result


@router.post("/incident-targets/{target_id}/rotate-secret")
def operator_incident_target_rotate_secret(target_id: str, body: RotateSecretBody, request: Request) -> dict:
    """Rotate a target's signing secret (or clear it). Invalidates prior readiness
    evidence so the target reads `unverified` until revalidated; records the rotation.
    The secret value is never returned."""
    _require_operator(request)
    from app.incident_sync import incident_sync_service

    result = incident_sync_service.rotate_secret(target_id, body.secret, actor=_operator_name(request))
    if result is None:
        raise HTTPException(status_code=404, detail="Target not found.")
    return result


@router.get("/incident-targets/attention")
def operator_incident_targets_attention(request: Request) -> dict:
    """Targets that need operator attention — enabled but not ready (stale / degraded /
    auth_failed / test_failed / invalid_config / unverified). Curated triage list."""
    _require_operator(request)
    from app.incident_sync import incident_sync_service

    return {"targets": incident_sync_service.targets_needing_attention()}


@router.get("/incident-targets/attention/summary")
def operator_incident_targets_attention_summary(request: Request) -> dict:
    """Bounded, deterministic triage rollup over all targets: readiness rollup
    (ready/attention/disabled/total), grouped attention reasons (by readiness state and
    by recommended action), and the single oldest unresolved attention item. Summary
    only — never a history dump."""
    _require_operator(request)
    from app.incident_sync import incident_sync_service

    return incident_sync_service.attention_summary()


@router.get("/incident-targets/{target_id}/capabilities")
def operator_incident_target_capabilities(target_id: str, request: Request) -> dict:
    """The honest adapter capability set for a target (refresh / push_outward /
    relink_validation / status_sync) + a single support_level label. Lets the console
    show exactly what's possible for this kind, no fake vendor claims."""
    _require_operator(request)
    from app.incident_sync import incident_sync_service, adapter_capabilities

    target = incident_sync_service.get_target(target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target not found.")
    caps = adapter_capabilities(target.get("kind"))
    return {"target_id": target_id, "kind": target.get("kind"),
            "support_level": caps["support_level"], "capabilities": caps}


@router.get("/incident-targets/{target_id}/policy")
def operator_incident_target_policy(target_id: str, request: Request) -> dict:
    """Per-target action+inbound policy: for each bounded action/field, what the adapter
    is CAPABLE of, the PROFILE default, the per-target OVERRIDE (null/true/false), and
    the net EFFECTIVE decision with its `source` (capability/profile/override/default)."""
    _require_operator(request)
    from app.incident_sync import incident_sync_service

    policy = incident_sync_service.target_policy(target_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Target not found.")
    return policy


@router.get("/incident-targets/{target_id}/profile")
def operator_incident_target_profile(target_id: str, request: Request) -> dict:
    """Onboarding view (G-14): the target's profile + its defaults + effective policy
    with per-decision sources — what this target will actually do, before relying on it."""
    _require_operator(request)
    from app.incident_sync import incident_sync_service

    profile = incident_sync_service.target_profile(target_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Target not found.")
    return profile


# ── demo seed (Phase 6) — operator-only, namespaced, deterministic ────────────

def _require_demo(request: Request) -> None:
    """Operator-gated AND feature-flagged. The demo lives in an isolated namespace and
    never touches real data, but writes are still operator-only + opt-out-able."""
    _require_operator(request)
    from app import demo_seed
    if not demo_seed.is_enabled():
        raise HTTPException(status_code=403, detail="Demo seed is disabled (set demo_seed_enabled).")


@router.get("/demo/status")
def operator_demo_status(request: Request) -> dict:
    """Whether the deterministic incident-sync demo is currently present, plus counts
    and the guided walkthrough. Read-only; operator-only."""
    _require_operator(request)
    from app import demo_seed

    return demo_seed.status()


@router.post("/demo/seed")
def operator_demo_seed(request: Request) -> dict:
    """Populate a deterministic, namespaced incident-sync showcase (targets across every
    readiness state, linked/drifted/missing/stale incidents, populated SLO/trend
    dashboard, a live candidate alert). Idempotent; touches only the demo namespace."""
    _require_demo(request)
    from app import demo_seed

    return demo_seed.seed()


@router.post("/demo/reset")
def operator_demo_reset(request: Request) -> dict:
    """Remove ONLY the demo namespace and everything referencing it. Real operator data
    and the chat product are never affected."""
    _require_demo(request)
    from app import demo_seed

    return {"removed": demo_seed.reset()}
