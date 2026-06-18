# File: backend/tests/test_webhooks.py
"""External delivery — webhook destinations + durable, bounded-retry delivery.

Operator-configured destinations receive curated observability events / alert-worthy
policy results as durable delivery attempts with bounded retry and honest terminal
failure. Secrets are never returned; routing respects subscription + severity;
delivery never breaks execution; nothing leaks into the user surface."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.accounts import account_service
from app.auth import make_account_token
import app.core.config as config_mod
from app.core.config import Settings
import app.execution_queue as eq
from app.execution_queue import execution_queue
from app.job_handlers import register_default_handlers
from app.main import app
from app.middleware import reset_rate_limit
from app.observability import observability
from app.ops_policy import SLOPolicy
from app.webhooks import STATUS_DELIVERED, STATUS_FAILED, STATUS_PENDING, delivery_service

register_default_handlers()
client = TestClient(app)
OP = {"X-API-Key": "service-secret"}


@pytest.fixture
def op(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "api_key", "service-secret")
    reset_rate_limit()
    yield


@pytest.fixture
def send_ok(monkeypatch):
    calls = []
    def _fake(self, url, body, secret):
        calls.append({"url": url, "body": body, "secret": secret})
        return (True, 200, None)
    monkeypatch.setattr(delivery_service, "_send", _fake.__get__(delivery_service))
    return calls


@pytest.fixture
def send_fail(monkeypatch):
    monkeypatch.setattr(delivery_service, "_send",
                        (lambda self, url, body, secret: (False, 500, "HTTP500")).__get__(delivery_service))


def _account():
    return account_service.register(f"u_{uuid4().hex[:10]}@example.com", "password123", "Alice")


def _dest(**over):
    body = {"name": "ops", "url": "https://hooks.example.com/x", "subscription": "events", **over}
    return delivery_service.create_destination(**body)


# ── Destination config (operator-only; secrets hidden) ───────────────────────


def test_destination_crud_over_http(op):
    created = client.post("/operator/destinations", headers=OP, json={
        "name": "pager", "url": "https://hooks.example.com/p", "subscription": "alerts",
        "min_severity": "critical", "secret": "s3cr3t"}).json()["destination"]
    assert created["has_secret"] is True and "secret" not in created  # secret never returned
    listed = client.get("/operator/destinations", headers=OP).json()["destinations"]
    assert any(d["id"] == created["id"] for d in listed)
    # Disable it.
    upd = client.patch(f"/operator/destinations/{created['id']}", headers=OP, json={"enabled": False}).json()["destination"]
    assert upd["enabled"] is False
    assert client.delete(f"/operator/destinations/{created['id']}", headers=OP).json()["ok"] is True


def test_destination_requires_operator(op):
    acct = _account()
    denied = client.post("/operator/destinations", headers={"Authorization": f"Bearer {make_account_token(acct['id'])}"},
                         json={"name": "x", "url": "https://e.com"})
    assert denied.status_code in (401, 403)


def test_invalid_destination_rejected(op):
    bad = client.post("/operator/destinations", headers=OP, json={"name": "x", "url": "ftp://nope"})
    assert bad.status_code == 400


def test_invalid_webhook_config_is_rejected():
    with pytest.raises(ValueError):
        Settings(webhook_max_attempts=0)


# ── Routing: observability events + policy alerts ────────────────────────────


def test_observability_event_creates_delivery_for_events_destination():
    _dest(subscription="events")
    execution_queue.register_handler("wh_ok", lambda j: {"ok": True})
    execution_queue.enqueue(f"account:{uuid4().hex}", "wh_ok", {}, title="T")
    execution_queue.drain()
    deliveries = delivery_service.recent_deliveries()
    assert deliveries and any(d["event_type"] == "job_queued" for d in deliveries)
    # Correlation preserved.
    assert all(d["source_type"] == "observability" for d in deliveries)


def test_alert_routing_creates_delivery_and_is_idempotent():
    # A stuck job -> a warning alert -> routed to an alerts destination.
    dest = _dest(subscription="alerts", min_severity="warning")
    owner = f"account:{uuid4().hex}"
    job = execution_queue.enqueue(owner, "noop", {}, title="stuck")
    from datetime import timedelta
    from app.db.database import SessionLocal
    from app.db.models import ExecutionJob
    from app.ops_policy import _now
    with SessionLocal() as s:
        s.get(ExecutionJob, job["id"]).created_at = _now() - timedelta(seconds=900)
        s.commit()
    from app.ops_policy import ops_policy
    tight = SLOPolicy(enabled=True, queued_seconds=300,
                      running_seconds={"default": 120, "artifact": 600, "validation": 300, "maintenance": 600},
                      cancel_seconds=60, backlog_threshold=2)
    alerts = ops_policy.alerts(policy=tight)
    assert delivery_service.route_alerts(alerts) >= 1
    # Idempotent: routing the same open alert again does not duplicate.
    before = len(delivery_service.recent_deliveries(destination_id=dest["id"]))
    delivery_service.route_alerts(alerts)
    assert len(delivery_service.recent_deliveries(destination_id=dest["id"])) == before


def test_alerts_only_destination_ignores_raw_events():
    _dest(subscription="alerts")
    execution_queue.register_handler("wh_ok2", lambda j: {"ok": True})
    execution_queue.enqueue(f"account:{uuid4().hex}", "wh_ok2", {}, title="T")
    execution_queue.drain()
    # An alerts-only destination receives no raw lifecycle events.
    assert delivery_service.recent_deliveries() == []


def test_disabled_destination_receives_nothing():
    _dest(subscription="events", enabled=False)
    execution_queue.register_handler("wh_ok3", lambda j: {"ok": True})
    execution_queue.enqueue(f"account:{uuid4().hex}", "wh_ok3", {}, title="T")
    execution_queue.drain()
    assert delivery_service.recent_deliveries() == []


# ── Delivery: success / bounded retry / terminal failure ─────────────────────


def test_successful_delivery_is_recorded(send_ok):
    _dest(subscription="events")
    execution_queue.register_handler("wh_ok4", lambda j: {"ok": True})
    execution_queue.enqueue(f"account:{uuid4().hex}", "wh_ok4", {}, title="T")
    execution_queue.drain()
    result = delivery_service.deliver_pending()
    assert result["delivered"] >= 1 and send_ok  # _send was actually invoked
    assert all(d["status"] == STATUS_DELIVERED for d in delivery_service.recent_deliveries())


def test_failed_delivery_retries_then_terminally_fails(send_fail, monkeypatch):
    monkeypatch.setattr(eq.settings, "webhook_max_attempts", 2)
    _dest(subscription="events")
    execution_queue.register_handler("wh_ok5", lambda j: {"ok": True})
    execution_queue.enqueue(f"account:{uuid4().hex}", "wh_ok5", {}, title="T")
    execution_queue.drain()
    # First sweep -> still pending (retry); second -> terminally failed.
    delivery_service.deliver_pending()
    assert any(d["status"] == STATUS_PENDING for d in delivery_service.recent_deliveries())
    delivery_service.deliver_pending()
    failed = delivery_service.recent_deliveries(status=STATUS_FAILED)
    assert failed and failed[0]["last_error"] == "HTTP500" and failed[0]["attempts"] == 2


def test_delivery_failure_does_not_break_execution(send_fail):
    _dest(subscription="events")
    execution_queue.register_handler("wh_ok6", lambda j: {"ok": True})
    job = execution_queue.enqueue(f"account:{uuid4().hex}", "wh_ok6", {}, title="T")
    execution_queue.drain()
    delivery_service.deliver_pending()  # deliveries fail...
    # ...but the job itself completed honestly.
    assert execution_queue.get_raw(job["id"])["status"] == "completed"


# ── Inspection + separation ──────────────────────────────────────────────────


def test_operator_can_inspect_deliveries_and_payload_is_clean(op, send_ok):
    _dest(subscription="events")
    execution_queue.register_handler("wh_ok7", lambda j: {"ok": True})
    execution_queue.enqueue(f"account:{uuid4().hex}", "wh_ok7", {"secret": "x"}, title="T")
    execution_queue.drain()
    delivery_service.deliver_pending()
    listed = client.get("/operator/deliveries", headers=OP).json()["deliveries"]
    assert listed
    one = client.get(f"/operator/deliveries/{listed[0]['id']}", headers=OP).json()["delivery"]
    blob = str(one)
    for banned in ("payload_json", "trace_events", "owner", "boom"):
        assert banned not in blob


def test_delivery_does_not_leak_into_user_surfaces():
    assert client.get("/operator/destinations").status_code in (401, 403)  # no key
    assert client.get("/destinations").status_code == 404                  # no user route
    assert client.get("/deliveries").status_code == 404
    owner = _account()
    job = execution_queue.enqueue(f"account:{owner['id']}", "noop", {}, title="T")
    auth = {"Authorization": f"Bearer {make_account_token(owner['id'])}"}
    user_job = client.get(f"/jobs/{job['id']}", headers=auth).json()["job"]
    for operator_only in ("destination_id", "delivery", "secret", "subscription"):
        assert operator_only not in user_job
