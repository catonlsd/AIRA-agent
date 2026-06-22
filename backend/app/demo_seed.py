"""Deterministic, operator-only incident-sync demo seed (Phase 6 — demonstrability).

A fresh AIRA-X clone has an empty database, so the operator console, the observability
dashboard, the runbooks, and the drift/recovery flows have nothing to show. This module
makes the whole platform **instantly demonstrable**: one operator-gated call populates a
realistic, deterministic incident-sync scenario that lights up every Phase 1–5 capability
at once — varied target readiness, linked/drifted/missing/stale incidents, a populated
SLO/trend dashboard, and a live candidate alert.

Guarantees it preserves:
- **Namespaced & non-destructive.** Every demo entity lives in the `demo.aira-x.local`
  target namespace and the `demo:` incident-signal namespace. Seeding/resetting touches
  *only* those rows — real operator data and the chat product are never affected.
- **Deterministic.** Fixed names, fixed structure, timestamps as fixed offsets from
  "now". Same seed → same readiness distribution, same drift backlog, same alerts.
- **No network, no side effects.** Rows are inserted directly; nothing calls a real
  adapter transport (`_send`/`_fetch`) or the live sweep.
- **Operator-only.** The routes are service-key gated and additionally guarded by the
  `demo_seed_enabled` setting.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import uuid4

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models import (
    ExternalIncidentTarget,
    IncidentExternalLink,
    IncidentReconciliationEvent,
    IncidentSyncRecord,
    IncidentTargetCheckEvent,
    OperatorIncident,
    OperatorIncidentEvent,
)
from app.incident_sync import _now, default_profile_for_kind

# Namespaces that make the demo data identifiable and safe to clear in isolation.
DEMO_HOST = "demo.aira-x.local"
DEMO_SIGNAL_PREFIX = "demo:"
DEMO_INCIDENT_PREFIX = "demo-inc-"
DEMO_SECRET = "demo-signing-secret"  # never returned by any read API


def is_enabled() -> bool:
    return bool(getattr(settings, "demo_seed_enabled", True))


def _h(now: datetime, hours: float) -> datetime:
    return now - timedelta(hours=hours)


def _d(now: datetime, days: float) -> datetime:
    return now - timedelta(days=days)


# ── the scenario (declarative + deterministic) ────────────────────────────────

def _target_specs(now: datetime) -> list[dict[str, Any]]:
    """Six targets spanning every readiness state + adapter variety. Evidence columns
    are set so the EXISTING `compute_readiness` derives the intended state — the demo
    never fakes a state, it sets honest evidence."""
    return [
        # key, name, kind, enabled, + readiness evidence
        {"key": "pd_prod", "name": "PagerDuty Prod (demo)", "kind": "pagerduty", "enabled": True,
         "secret": DEMO_SECRET, "last_validated_at": _h(now, 1), "last_success_at": _h(now, 1),
         "last_check_kind": "connectivity"},                                   # → ready
        {"key": "og_eu", "name": "Opsgenie EU (demo)", "kind": "opsgenie", "enabled": True,
         "secret": DEMO_SECRET, "last_validated_at": _h(now, 3), "last_success_at": _h(now, 3),
         "last_check_kind": "connectivity"},                                   # → ready
        {"key": "pd_staging", "name": "PagerDuty Staging (demo)", "kind": "pagerduty", "enabled": True,
         "secret": DEMO_SECRET, "last_validated_at": _d(now, 9), "last_success_at": _d(now, 9),
         "last_check_kind": "connectivity"},                                   # → stale (>7d)
        {"key": "generic_hook", "name": "Generic Webhook (demo)", "kind": "generic", "enabled": True},  # → unverified
        {"key": "pd_legacy", "name": "PagerDuty Legacy (demo)", "kind": "pagerduty", "enabled": True,
         "secret": DEMO_SECRET, "last_validated_at": _h(now, 2), "last_failure_at": _h(now, 2),
         "last_check_error": "HTTP401", "last_check_kind": "connectivity"},     # → auth_failed
        {"key": "jira_bridge", "name": "Jira Bridge (demo)", "kind": "jira", "enabled": False},  # → disabled
    ]


def _incident_specs(now: datetime) -> list[dict[str, Any]]:
    """Five incidents spanning the link/drift verdicts. `link` describes the external
    linkage to seed; `target` is a target key."""
    return [
        {"id": f"{DEMO_INCIDENT_PREFIX}1", "signal": f"{DEMO_SIGNAL_PREFIX}db-pool-exhausted",
         "classification": "stuck", "subject": "payments-api", "severity": "critical", "state": "open",
         "target": "pd_prod", "ref": "PD-4821", "ext_status": "open", "ext_exists": True,
         "synced": _h(now, 0.5), "checked": _h(now, 0.3), "action": "opened"},   # healthy linked
        {"id": f"{DEMO_INCIDENT_PREFIX}2", "signal": f"{DEMO_SIGNAL_PREFIX}disk-pressure",
         "classification": "stuck", "subject": "ingest-worker", "severity": "critical", "state": "open",
         "target": "pd_prod", "ref": "PD-4830", "ext_status": "resolved", "ext_exists": True,
         "synced": _h(now, 2), "checked": _h(now, 1), "action": "opened"},       # DRIFTED (ext resolved, local open)
        {"id": f"{DEMO_INCIDENT_PREFIX}3", "signal": f"{DEMO_SIGNAL_PREFIX}cert-expiry",
         "classification": "failing", "subject": "edge-gateway", "severity": "warning", "state": "open",
         "target": "og_eu", "ref": "OG-1190", "ext_status": "missing", "ext_exists": False,
         "synced": _h(now, 5), "checked": _h(now, 2), "action": "opened"},       # MISSING_EXTERNAL
        {"id": f"{DEMO_INCIDENT_PREFIX}4", "signal": f"{DEMO_SIGNAL_PREFIX}latency-regression",
         "classification": "degraded", "subject": "search-svc", "severity": "warning", "state": "open",
         "target": "pd_prod", "ref": "PD-4795", "ext_status": "open", "ext_exists": True,
         "synced": _d(now, 3), "checked": _d(now, 3), "action": "opened"},       # STALE link (age > 1d)
        {"id": f"{DEMO_INCIDENT_PREFIX}5", "signal": f"{DEMO_SIGNAL_PREFIX}oom-kills",
         "classification": "stuck", "subject": "render-svc", "severity": "critical", "state": "recovered",
         "recovered_at": _h(now, 14), "target": "og_eu", "ref": "OG-1188", "ext_status": "resolved",
         "ext_exists": True, "synced": _h(now, 12), "checked": _h(now, 10), "action": "recovered"},  # aligned/healthy
    ]


def _check_event_specs(now: datetime, key_to_id: dict[str, str]) -> list[IncidentTargetCheckEvent]:
    """Validation/lifecycle history spread across the 24h/7d/30d windows so the
    observability rollups are populated. The auth-failed target gets 4 failed
    validations inside 24h → trips the repeated-auth-failure candidate alert."""
    rows: list[tuple[str, str, str, Optional[str], datetime]] = [
        ("pd_prod", "validate", "ready", None, _h(now, 1)),
        ("pd_prod", "revalidate", "ready", None, _d(now, 2)),
        ("pd_prod", "validate", "ready", None, _d(now, 12)),
        ("pd_prod", "secret_rotated", "unverified", "rotated by demo", _d(now, 15)),
        ("og_eu", "validate", "ready", None, _h(now, 3)),
        ("og_eu", "validate", "ready", None, _d(now, 6)),
        ("pd_staging", "validate", "ready", None, _d(now, 9)),
        ("pd_legacy", "validate", "auth_failed", "HTTP401", _h(now, 1)),
        ("pd_legacy", "validate", "auth_failed", "HTTP401", _h(now, 4)),
        ("pd_legacy", "validate", "auth_failed", "HTTP401", _h(now, 9)),
        ("pd_legacy", "validate", "auth_failed", "HTTP401", _h(now, 20)),
    ]
    return [IncidentTargetCheckEvent(target_id=key_to_id[k], event=e, outcome=o, actor="demo",
                                     detail=d, created_at=ts)
            for (k, e, o, d, ts) in rows if k in key_to_id]


def _recon_event_specs(now: datetime, key_to_id: dict[str, str]) -> list[IncidentReconciliationEvent]:
    """Reconciliation history (refresh/apply/relink/detach) across windows so the
    reconciliation + refresh rollups are populated with real pass/fail."""
    rows = [
        (f"{DEMO_INCIDENT_PREFIX}1", "pd_prod", "refresh", "ok", None, _h(now, 0.3)),
        (f"{DEMO_INCIDENT_PREFIX}1", "pd_prod", "refresh", "ok", None, _d(now, 2)),
        (f"{DEMO_INCIDENT_PREFIX}2", "pd_prod", "refresh", "ok", "external resolved", _h(now, 1)),
        (f"{DEMO_INCIDENT_PREFIX}2", "pd_prod", "refresh", "ok", None, _d(now, 4)),
        (f"{DEMO_INCIDENT_PREFIX}3", "og_eu", "refresh", "missing", "not found", _h(now, 2)),
        (f"{DEMO_INCIDENT_PREFIX}5", "og_eu", "apply:accept_resolved", "ok", "recovered locally", _d(now, 1)),
        (f"{DEMO_INCIDENT_PREFIX}4", "pd_prod", "relink", "ok", "re-linked", _d(now, 6)),
        (f"{DEMO_INCIDENT_PREFIX}3", "og_eu", "detach", "ok", "stale link removed", _d(now, 8)),
    ]
    return [IncidentReconciliationEvent(incident_id=i, target_id=key_to_id.get(k), action=a,
                                        outcome=o, actor="demo", detail=d, created_at=ts)
            for (i, k, a, o, d, ts) in rows]


def _sync_record_specs(now: datetime, key_to_id: dict[str, str], inc_by_key) -> list[IncidentSyncRecord]:
    """Outbound sync history (synced/failed) across windows so the sync rollup shows a
    realistic <100% success rate."""
    rows = [
        (f"{DEMO_INCIDENT_PREFIX}1", "pd_prod", "opened", "synced", "critical", None, _h(now, 0.5)),
        (f"{DEMO_INCIDENT_PREFIX}2", "pd_prod", "opened", "synced", "critical", None, _h(now, 2)),
        (f"{DEMO_INCIDENT_PREFIX}1", "pd_prod", "opened", "synced", "critical", None, _d(now, 1)),
        (f"{DEMO_INCIDENT_PREFIX}4", "pd_prod", "opened", "synced", "warning", None, _d(now, 3)),
        (f"{DEMO_INCIDENT_PREFIX}3", "og_eu", "opened", "failed", "warning", "HTTP503", _h(now, 5)),
        (f"{DEMO_INCIDENT_PREFIX}5", "og_eu", "recovered", "synced", "critical", None, _d(now, 1)),
    ]
    out = []
    for (inc, k, action, status, sev, err, ts) in rows:
        out.append(IncidentSyncRecord(
            id=uuid4().hex, target_id=key_to_id[k], incident_id=inc, signal=f"{DEMO_SIGNAL_PREFIX}sync",
            action=action, actor="demo", state=("recovered" if action == "recovered" else "open"),
            severity=sev, status=status, attempts=1, last_error=err, created_at=ts))
    return out


# ── the guided walkthrough (static, deterministic) ────────────────────────────

TOUR: list[dict[str, str]] = [
    {"step": "1", "area": "Targets & readiness",
     "look_at": "Operator console → Incidents tab → External sync",
     "shows": "Six targets across ready / stale / unverified / auth-failed / disabled — each with a deterministic recommended next action."},
    {"step": "2", "area": "Observability & SLOs",
     "look_at": "Incidents tab → Sync observability panel",
     "shows": "Live readiness / validation / reconciliation / sync SLOs, 24h–30d trend pass rates, a drift backlog, and a repeated-auth-failure candidate alert."},
    {"step": "3", "area": "Drift & deliberate recovery",
     "look_at": "Expand the 'ingest-worker' incident → History",
     "shows": "A drifted incident (external resolved, local still open) offering Refresh + Apply — recovery is always an explicit, audited operator action."},
    {"step": "4", "area": "Audit trail",
     "look_at": "A target's health view / an incident's reconciliation history",
     "shows": "Durable, secret-free check + reconciliation events behind every state — nothing is unexplained."},
    {"step": "5", "area": "Operator/user separation",
     "look_at": "The chat product at /chat",
     "shows": "None of the operator surface is visible to end users — it is entirely service-key gated."},
]


def _manifest(counts: dict[str, int]) -> dict[str, Any]:
    return {
        "demo": True,
        "namespace": DEMO_HOST,
        "counts": counts,
        "tour": TOUR,
        "note": (f"Deterministic incident-sync demo in the `{DEMO_HOST}` namespace. "
                 "Operator-only; reset with POST /operator/demo/reset. Does not touch "
                 "real operator data or the chat product."),
    }


# ── seed / reset / status (namespaced; never touches real data) ───────────────

def _demo_target_ids(session) -> list[str]:
    return [r.id for r in session.query(ExternalIncidentTarget.id)
            .filter(ExternalIncidentTarget.url.like(f"%{DEMO_HOST}%")).all()]


def _demo_incident_ids(session) -> list[str]:
    return [r.id for r in session.query(OperatorIncident.id)
            .filter(OperatorIncident.signal.like(f"{DEMO_SIGNAL_PREFIX}%")).all()]


def reset() -> dict[str, int]:
    """Remove ONLY the demo namespace (by `demo.aira-x.local` targets + `demo:` incident
    signals) and everything referencing it. Real operator data is never touched."""
    removed = {"targets": 0, "incidents": 0, "links": 0, "check_events": 0,
               "reconciliation_events": 0, "sync_records": 0}
    try:
        with SessionLocal() as session:
            target_ids = _demo_target_ids(session)
            incident_ids = _demo_incident_ids(session)
            if target_ids:
                removed["check_events"] = (session.query(IncidentTargetCheckEvent)
                    .filter(IncidentTargetCheckEvent.target_id.in_(target_ids))
                    .delete(synchronize_session=False))
            if incident_ids:
                removed["reconciliation_events"] = (session.query(IncidentReconciliationEvent)
                    .filter(IncidentReconciliationEvent.incident_id.in_(incident_ids))
                    .delete(synchronize_session=False))
            if target_ids or incident_ids:
                removed["links"] = (session.query(IncidentExternalLink)
                    .filter(IncidentExternalLink.target_id.in_(target_ids or [""]) |
                            IncidentExternalLink.incident_id.in_(incident_ids or [""]))
                    .delete(synchronize_session=False))
                removed["sync_records"] = (session.query(IncidentSyncRecord)
                    .filter(IncidentSyncRecord.target_id.in_(target_ids or [""]) |
                            IncidentSyncRecord.incident_id.in_(incident_ids or [""]))
                    .delete(synchronize_session=False))
            if target_ids:
                removed["targets"] = (session.query(ExternalIncidentTarget)
                    .filter(ExternalIncidentTarget.id.in_(target_ids))
                    .delete(synchronize_session=False))
            if incident_ids:
                session.query(OperatorIncidentEvent).filter(
                    OperatorIncidentEvent.incident_id.in_(incident_ids)).delete(synchronize_session=False)
                removed["incidents"] = (session.query(OperatorIncident)
                    .filter(OperatorIncident.id.in_(incident_ids))
                    .delete(synchronize_session=False))
            session.commit()
    except Exception:
        pass
    return removed


def seed() -> dict[str, Any]:
    """Reset the demo namespace, then insert the deterministic scenario. Idempotent —
    re-seeding yields the same shape without accumulating duplicates. Returns the demo
    manifest (counts + guided tour)."""
    reset()
    now = _now()
    counts = {"targets": 0, "incidents": 0, "links": 0, "check_events": 0,
              "reconciliation_events": 0, "sync_records": 0}
    try:
        with SessionLocal() as session:
            key_to_id: dict[str, str] = {}
            for spec in _target_specs(now):
                tid = uuid4().hex
                key_to_id[spec["key"]] = tid
                session.add(ExternalIncidentTarget(
                    id=tid, name=spec["name"], url=f"https://{DEMO_HOST}/{spec['key']}",
                    kind=spec["kind"], profile=default_profile_for_kind(spec["kind"]),
                    enabled=spec["enabled"], secret=spec.get("secret"),
                    last_validated_at=spec.get("last_validated_at"),
                    last_test_at=spec.get("last_test_at"),
                    last_success_at=spec.get("last_success_at"),
                    last_failure_at=spec.get("last_failure_at"),
                    last_check_error=spec.get("last_check_error"),
                    last_check_kind=spec.get("last_check_kind")))
                counts["targets"] += 1

            inc_specs = _incident_specs(now)
            for spec in inc_specs:
                session.add(OperatorIncident(
                    id=spec["id"], signal=spec["signal"], classification=spec["classification"],
                    subject=spec["subject"], source="alert", state=spec["state"],
                    severity=spec["severity"], occurrences=3, note=None,
                    recovered_at=spec.get("recovered_at"),
                    first_seen=_d(now, 7), last_seen=_h(now, 1)))
                counts["incidents"] += 1
                session.add(IncidentExternalLink(
                    id=uuid4().hex, incident_id=spec["id"], target_id=key_to_id[spec["target"]],
                    external_ref=spec["ref"], external_url=f"https://{DEMO_HOST}/ext/{spec['ref']}",
                    last_action=spec["action"], last_synced_at=spec["synced"],
                    last_checked_at=spec["checked"], external_status=spec["ext_status"],
                    external_exists=spec["ext_exists"]))
                counts["links"] += 1

            for ev in _check_event_specs(now, key_to_id):
                session.add(ev); counts["check_events"] += 1
            for ev in _recon_event_specs(now, key_to_id):
                session.add(ev); counts["reconciliation_events"] += 1
            for rec in _sync_record_specs(now, key_to_id, inc_specs):
                session.add(rec); counts["sync_records"] += 1
            session.commit()
    except Exception:
        return _manifest(counts)
    return _manifest(counts)


def status() -> dict[str, Any]:
    """Whether demo data is currently present, with counts + the guided tour. Used by
    the console to show a demo banner/walkthrough."""
    counts = {"targets": 0, "incidents": 0}
    try:
        with SessionLocal() as session:
            counts["targets"] = (session.query(ExternalIncidentTarget)
                .filter(ExternalIncidentTarget.url.like(f"%{DEMO_HOST}%")).count())
            counts["incidents"] = (session.query(OperatorIncident)
                .filter(OperatorIncident.signal.like(f"{DEMO_SIGNAL_PREFIX}%")).count())
    except Exception:
        pass
    present = counts["targets"] > 0 or counts["incidents"] > 0
    return {"present": present, "enabled": is_enabled(), "namespace": DEMO_HOST,
            "counts": counts, "tour": TOUR if present else []}
