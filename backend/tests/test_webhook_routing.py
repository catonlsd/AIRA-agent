# File: backend/tests/test_webhook_routing.py
"""Per-destination routing policy, bounded alert suppression, adapter payload
policy (F-10).

Destinations filter on event types, alert classifications, origins, and severity;
a bounded suppression window stops a persistent stuck job from re-delivering the
same critical alert every sweep (while a severity change still routes). The
adapter participates in routing/payload shaping. Operator-only; secrets hidden;
the curated payload + user separation hold."""

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.accounts import account_service
from app.auth import make_account_token
import app.core.config as config_mod
from app.db.database import SessionLocal, ensure_runtime_columns
from app.db.models import WebhookDelivery
from app.execution_queue import execution_queue
from app.job_handlers import register_default_handlers
from app.main import app
from app.middleware import reset_rate_limit
from app.webhooks import (
    STATUS_DELIVERED,
    STATUS_FAILED,
    STATUS_PENDING,
    alert_routing_decision,
    delivery_service,
)

ensure_runtime_columns()
register_default_handlers()
client = TestClient(app)
OP = {"X-API-Key": "service-secret"}


@pytest.fixture
def op(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "api_key", "service-secret")
    reset_rate_limit()
    yield


def _account():
    return account_service.register(f"u_{uuid4().hex[:10]}@example.com", "password123", "Alice")


def _dest(**over):
    body = {"name": "d", "url": "https://h.example.com/x", "subscription": "events", **over}
    return delivery_service.create_destination(**body)


def _alert(classification="stuck", severity="critical", job_id=None):
    return {"classification": classification, "severity": severity,
            "job_id": job_id or uuid4().hex, "reason": "x"}


def _run_event_job(handler_kind):
    execution_queue.register_handler(handler_kind, lambda j: {"ok": True})
    execution_queue.enqueue(f"account:{uuid4().hex}", handler_kind, {}, title="T")
    execution_queue.drain()


# ── Event-type + origin filtering ────────────────────────────────────────────


def test_event_type_filter_is_enforced():
    _dest(subscription="events", event_filter="job_failed")  # only failures
    _run_event_job(f"rt_{uuid4().hex[:6]}")  # emits queued/claimed/completed (no failed)
    assert delivery_service.recent_deliveries() == []  # none matched the filter


def test_origin_filter_is_enforced():
    # Only retry/replay-origin events; a normal job's events are filtered out.
    _dest(subscription="events", origin_filter="retry,replay")
    _run_event_job(f"rt_{uuid4().hex[:6]}")
    assert delivery_service.recent_deliveries() == []


# ── Alert classification + severity filtering ────────────────────────────────


def test_alert_classification_filter_is_enforced():
    dest = _dest(subscription="alerts", min_severity="warning", alert_filter="retry_exhausted")
    routed = delivery_service.route_alerts([
        _alert(classification="stuck", severity="critical"),          # filtered out
        _alert(classification="retry_exhausted", severity="critical"),  # allowed
    ])
    assert routed == 1
    deliveries = delivery_service.recent_deliveries(destination_id=dest["id"])
    assert all(d["event_type"] == "retry_exhausted" for d in deliveries)


def test_min_severity_filter_still_applies():
    dest = _dest(subscription="alerts", min_severity="critical")
    routed = delivery_service.route_alerts([_alert(severity="warning"), _alert(severity="critical")])
    assert routed == 1
    assert all(d["severity"] == "critical" for d in delivery_service.recent_deliveries(destination_id=dest["id"]))


def test_disabled_destination_receives_nothing():
    _dest(subscription="both", enabled=False)
    delivery_service.route_alerts([_alert()])
    _run_event_job(f"rt_{uuid4().hex[:6]}")
    assert delivery_service.recent_deliveries() == []


# ── Suppression / dedup (the noise gap) ──────────────────────────────────────


def test_repeated_identical_critical_alert_is_suppressed(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "webhook_suppress_seconds", 300)
    dest = _dest(subscription="alerts", min_severity="warning")
    job_id = uuid4().hex
    alert = _alert(classification="stuck", severity="critical", job_id=job_id)
    # First sweep routes; the delivery lands (mark delivered so it's not "in_flight").
    assert delivery_service.route_alerts([alert]) == 1
    _mark_delivered(dest["id"])
    # A second sweep of the SAME signal inside the window is suppressed — no spam.
    detailed = delivery_service.route_alerts_detailed([alert])
    assert detailed["routed"] == 0 and detailed["suppressed"] == 1


def test_severity_change_is_not_suppressed(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "webhook_suppress_seconds", 300)
    dest = _dest(subscription="alerts", min_severity="warning")
    job_id = uuid4().hex
    delivery_service.route_alerts([_alert("stuck", "warning", job_id)])
    _mark_delivered(dest["id"])
    # Escalation to critical for the SAME signal is a real state change -> routes.
    assert delivery_service.route_alerts([_alert("stuck", "critical", job_id)]) == 1


def test_suppression_clears_after_window(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "webhook_suppress_seconds", 60)
    dest = _dest(subscription="alerts", min_severity="warning")
    job_id = uuid4().hex
    alert = _alert("stuck", "critical", job_id)
    delivery_service.route_alerts([alert])
    # Age the existing delivery past the window -> the recurring alert routes again.
    with SessionLocal() as s:
        row = s.query(WebhookDelivery).filter(WebhookDelivery.destination_id == dest["id"]).first()
        row.status = STATUS_DELIVERED
        from app.webhooks import _utc_now
        row.created_at = _utc_now() - timedelta(seconds=120)
        s.commit()
    assert delivery_service.route_alerts([alert]) == 1


def test_suppression_does_not_create_fake_delivered_records(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "webhook_suppress_seconds", 300)
    dest = _dest(subscription="alerts", min_severity="warning")
    alert = _alert("stuck", "critical")
    delivery_service.route_alerts([alert])
    _mark_delivered(dest["id"])
    before = len(delivery_service.recent_deliveries(destination_id=dest["id"]))
    delivery_service.route_alerts([alert])  # suppressed
    assert len(delivery_service.recent_deliveries(destination_id=dest["id"])) == before


def _mark_delivered(dest_id):
    with SessionLocal() as s:
        for row in s.query(WebhookDelivery).filter(WebhookDelivery.destination_id == dest_id,
                                                   WebhookDelivery.status == STATUS_PENDING).all():
            row.status = STATUS_DELIVERED
        s.commit()


# ── Pure decision helper ─────────────────────────────────────────────────────


def test_routing_decision_helper_is_explainable():
    dest = type("D", (), {"id": "d1", "min_severity": "warning", "alert_filter": "stuck"})()
    a = _alert("stuck", "critical")
    assert alert_routing_decision(dest=dest, alert=a, in_flight=False, last_severity=None,
                                  last_age_seconds=None, window_seconds=300) == ("route", "ok")
    assert alert_routing_decision(dest=dest, alert=_alert("backlog_pressure", "critical"), in_flight=False,
                                  last_severity=None, last_age_seconds=None, window_seconds=300)[1] == "classification_filtered"
    assert alert_routing_decision(dest=dest, alert=a, in_flight=True, last_severity=None,
                                  last_age_seconds=None, window_seconds=300) == ("skip", "in_flight")
    assert alert_routing_decision(dest=dest, alert=a, in_flight=False, last_severity="critical",
                                  last_age_seconds=10, window_seconds=300) == ("suppress", "within_window")


# ── Adapter participation ────────────────────────────────────────────────────


def test_destination_exposes_adapter_payload_shape():
    web = _dest(kind="webhook")
    slack = _dest(kind="slack", name="s")
    assert web["payload_shape"] == "structured_json"
    assert slack["payload_shape"] == "slack_text"


# ── Operator routing inspection ──────────────────────────────────────────────


def test_operator_routing_preview(op):
    dest = _dest(subscription="alerts", min_severity="critical", alert_filter="retry_exhausted")
    body = client.get(f"/operator/destinations/{dest['id']}/routing", headers=OP)
    assert body.status_code == 200
    data = body.json()
    assert data["destination"]["alert_filter"] == "retry_exhausted"
    assert "decisions" in data and "has_secret" not in str(data.get("secret", ""))


def test_routing_config_is_operator_only(op):
    dest = _dest()
    acct = _account()
    denied = client.get(f"/operator/destinations/{dest['id']}/routing",
                        headers={"Authorization": f"Bearer {make_account_token(acct['id'])}"})
    assert denied.status_code in (401, 403)


def test_update_routing_filters_over_http(op):
    created = client.post("/operator/destinations", headers=OP, json={
        "name": "p", "url": "https://h.example.com/p", "subscription": "alerts",
        "min_severity": "warning", "alert_filter": "stuck", "suppress_seconds": 120}).json()["destination"]
    assert created["alert_filter"] == "stuck" and created["suppress_seconds"] == 120
    upd = client.patch(f"/operator/destinations/{created['id']}", headers=OP,
                       json={"alert_filter": "retry_exhausted,backlog_pressure"}).json()["destination"]
    assert upd["alert_filter"] == "retry_exhausted,backlog_pressure"
    # Secret still never returned even with routing config present.
    assert "secret" not in upd


# ── Separation ───────────────────────────────────────────────────────────────


def test_routing_does_not_leak_to_user_surfaces():
    assert client.get("/operator/destinations").status_code in (401, 403)  # no key
    assert client.get("/destinations").status_code == 404                  # no user route
    owner = _account()
    job = execution_queue.enqueue(f"account:{owner['id']}", "noop", {}, title="T")
    auth = {"Authorization": f"Bearer {make_account_token(owner['id'])}"}
    user_job = client.get(f"/jobs/{job['id']}", headers=auth).json()["job"]
    for operator_only in ("alert_filter", "origin_filter", "suppress_seconds", "payload_shape"):
        assert operator_only not in user_job
