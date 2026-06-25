# File: backend/tests/test_webhook_escalation.py
"""Multi-destination escalation policy + delivery analytics (F-11).

A primary destination fires on the first occurrence; an escalation destination
(escalate_after=N) fires only once a matching condition has PERSISTED N detections
— bounded, suppression-compatible, never an uncontrolled fan-out. Operator
analytics summarize delivery health/coverage durably. Operator-only; secrets
hidden; user surfaces unchanged."""

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
from app.webhooks import STATUS_DELIVERED, STATUS_FAILED, STATUS_PENDING, delivery_service

ensure_runtime_columns()
register_default_handlers()
client = TestClient(app)
OP = {"X-API-Key": "service-secret"}


@pytest.fixture
def op(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "api_key", "service-secret")
    reset_rate_limit()
    yield


@pytest.fixture(autouse=True)
def _no_suppression(monkeypatch):
    # Isolate escalation behavior from the suppression window unless a test wants it.
    monkeypatch.setattr(config_mod.settings, "webhook_suppress_seconds", 0)
    monkeypatch.setattr(config_mod.settings, "webhook_escalation_resolve_seconds", 1800)
    yield


def _account():
    return account_service.register(f"u_{uuid4().hex[:10]}@example.com", "password123", "Alice")


def _dest(**over):
    body = {"name": "d", "url": "https://h.example.com/x", "subscription": "alerts",
            "min_severity": "warning", **over}
    return delivery_service.create_destination(**body)


def _alert(classification="retry_exhausted", severity="critical", job_id=None):
    return {"classification": classification, "severity": severity,
            "job_id": job_id or "fixed-job", "reason": "x"}


def _count_for(dest_id):
    return len(delivery_service.recent_deliveries(destination_id=dest_id, limit=200))


# ── Escalation behavior ──────────────────────────────────────────────────────


def test_primary_fires_immediately_escalation_waits():
    primary = _dest(name="slack")                      # escalate_after=None -> primary
    escalation = _dest(name="pager", escalate_after=3)  # fires only after 3 detections
    alert = _alert()
    delivery_service.route_alerts([alert])  # occurrence 1
    assert _count_for(primary["id"]) == 1 and _count_for(escalation["id"]) == 0


def test_escalation_fires_after_persistence_threshold():
    escalation = _dest(name="pager", escalate_after=3)
    alert = _alert(job_id="persist-1")
    for _ in range(2):
        delivery_service.route_alerts([alert])  # occurrences 1, 2 -> below threshold
    assert _count_for(escalation["id"]) == 0
    delivery_service.route_alerts([alert])       # occurrence 3 -> escalates
    assert _count_for(escalation["id"]) == 1


def test_lower_severity_does_not_escalate():
    escalation = _dest(name="pager", escalate_after=2, min_severity="critical")
    warn = _alert(severity="warning", job_id="warn-1")
    for _ in range(5):
        delivery_service.route_alerts([warn])  # below the destination's floor
    assert _count_for(escalation["id"]) == 0


def test_classification_specific_escalation():
    escalation = _dest(name="pager", escalate_after=1, alert_filter="retry_exhausted")
    delivery_service.route_alerts([_alert(classification="stuck", job_id="s1")])           # filtered out
    delivery_service.route_alerts([_alert(classification="retry_exhausted", job_id="r1")])  # escalates
    deliveries = delivery_service.recent_deliveries(destination_id=escalation["id"])
    assert len(deliveries) == 1 and deliveries[0]["event_type"] == "retry_exhausted"


def test_resolved_episode_resets_occurrence_count(monkeypatch):
    escalation = _dest(name="pager", escalate_after=3)
    alert = _alert(job_id="episodic")
    delivery_service.route_alerts([alert])  # occ 1
    delivery_service.route_alerts([alert])  # occ 2
    # Simulate the condition resolving (occurrence goes stale beyond resolve window).
    from app.db.models import AlertOccurrence
    from app.webhooks import _alert_signal, _utc_now
    from datetime import timedelta
    with SessionLocal() as s:
        row = s.get(AlertOccurrence, _alert_signal(alert))
        row.last_seen = _utc_now() - timedelta(seconds=3600)  # > resolve window
        s.commit()
    delivery_service.route_alerts([alert])  # fresh episode -> occ resets to 1, no escalation
    assert _count_for(escalation["id"]) == 0


def test_suppression_still_prevents_repeat_escalation(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "webhook_suppress_seconds", 300)
    escalation = _dest(name="pager", escalate_after=1)
    alert = _alert(job_id="supp-esc")
    assert delivery_service.route_alerts([alert]) >= 1  # escalates once
    _mark_delivered(escalation["id"])
    # Same persistent critical condition next sweep: suppressed, not re-escalated.
    detailed = delivery_service.route_alerts_detailed([alert])
    assert detailed["suppressed"] >= 1


def _mark_delivered(dest_id):
    with SessionLocal() as s:
        for row in s.query(WebhookDelivery).filter(WebhookDelivery.destination_id == dest_id,
                                                   WebhookDelivery.status == STATUS_PENDING).all():
            row.status = STATUS_DELIVERED
        s.commit()


# ── Analytics ────────────────────────────────────────────────────────────────


def test_analytics_counts_delivered_failed_and_routing(monkeypatch):
    dest = _dest(name="webhook-d", subscription="events", kind="webhook")
    # Route + deliver one success and one failure.
    monkeypatch.setattr(delivery_service, "_send",
                        (lambda self, url, body, secret: (True, 200, None)).__get__(delivery_service))
    execution_queue.register_handler("esc_ok", lambda j: {"ok": True})
    execution_queue.enqueue(f"account:{uuid4().hex}", "esc_ok", {}, title="T")
    execution_queue.drain()
    delivery_service.deliver_pending()
    a = delivery_service.analytics()
    assert a["totals"]["delivered"] >= 1 and a["totals"]["attempted"] >= 1
    assert "webhook" in a["by_kind"]
    assert any(d["destination_id"] == dest["id"] for d in a["by_destination"])


def test_analytics_includes_durable_suppression_counter():
    dest = _dest(name="alerts-d")
    alert = _alert(job_id="sup-count")
    delivery_service.route_alerts([alert])  # routed
    a = delivery_service.analytics()
    assert a["routing"]["routed"] >= 1


def test_destination_health_is_clean_and_labeled(monkeypatch):
    dest = _dest(name="failing", subscription="events")
    monkeypatch.setattr(config_mod.settings, "webhook_max_attempts", 1)
    monkeypatch.setattr(delivery_service, "_send",
                        (lambda self, url, body, secret: (False, 500, "HTTP500")).__get__(delivery_service))
    execution_queue.register_handler("esc_fail", lambda j: {"ok": True})
    execution_queue.enqueue(f"account:{uuid4().hex}", "esc_fail", {}, title="T")
    execution_queue.drain()
    delivery_service.deliver_pending()
    health = {h["destination_id"]: h for h in delivery_service.destination_health()}
    h = health[dest["id"]]
    assert h["failed_terminal"] >= 1 and h["health"] in ("failing", "degraded")
    assert "secret" not in h and "url" not in str(h.get("secret", ""))


# ── HTTP: operator-only escalation config + analytics ────────────────────────


def test_escalation_config_over_http(op):
    created = client.post("/operator/destinations", headers=OP, json={
        "name": "pager", "url": "https://h.example.com/p", "subscription": "alerts",
        "min_severity": "critical", "escalate_after": 3}).json()["destination"]
    assert created["escalate_after"] == 3 and created["is_escalation"] is True
    assert "secret" not in created


def test_analytics_and_health_require_operator(op):
    assert client.get("/operator/delivery/analytics", headers=OP).status_code == 200
    assert client.get("/operator/delivery/health", headers=OP).status_code == 200
    acct = _account()
    denied = client.get("/operator/delivery/analytics",
                        headers={"Authorization": f"Bearer {make_account_token(acct['id'])}"})
    assert denied.status_code in (401, 403)


def test_analytics_does_not_leak_to_user_surfaces():
    assert client.get("/delivery/analytics").status_code == 404
    assert client.get("/delivery/health").status_code == 404
    owner = _account()
    job = execution_queue.enqueue(f"account:{owner['id']}", "noop", {}, title="T")
    auth = {"Authorization": f"Bearer {make_account_token(owner['id'])}"}
    user_job = client.get(f"/jobs/{job['id']}", headers=auth).json()["job"]
    for operator_only in ("escalate_after", "is_escalation", "stat_routed", "health", "by_destination"):
        assert operator_only not in user_job
