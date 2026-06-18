# File: backend/tests/test_webhook_policy.py
"""Adapter-specific retry policy, destination health/SLO classification, bounded
cooldown, and health-aware routing (F-12).

Retry budget is per-adapter/per-destination (Slack is tighter than webhook).
Repeated terminal failures cool a destination down (bounded, recoverable); routing
skips a cooling destination honestly (no fake delivery), and an escalation target
that's failing becomes escalation-ineligible. Operator-only; secrets hidden; user
surfaces unchanged."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.accounts import account_service
from app.auth import make_account_token
import app.core.config as config_mod
from app.core.config import Settings
from app.db.database import SessionLocal, ensure_runtime_columns
from app.db.models import WebhookDelivery, WebhookDestination
from app.execution_queue import execution_queue
from app.job_handlers import register_default_handlers
from app.main import app
from app.middleware import reset_rate_limit
from app.webhooks import (
    STATUS_DELIVERED,
    STATUS_FAILED,
    STATUS_PENDING,
    effective_max_attempts,
    in_cooldown,
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


@pytest.fixture
def send_fail(monkeypatch):
    monkeypatch.setattr(delivery_service, "_send",
                        (lambda self, url, body, secret: (False, 500, "HTTP500")).__get__(delivery_service))


def _account():
    return account_service.register(f"u_{uuid4().hex[:10]}@example.com", "password123", "Alice")


def _dest(**over):
    body = {"name": "d", "url": "https://h.example.com/x", "subscription": "events", **over}
    return delivery_service.create_destination(**body)


def _emit_event_to(dest_kind="webhook", **dest_over):
    dest = _dest(kind=dest_kind, **dest_over)
    h = f"pol_{uuid4().hex[:6]}"
    execution_queue.register_handler(h, lambda j: {"ok": True})
    execution_queue.enqueue(f"account:{uuid4().hex}", h, {}, title="T")
    execution_queue.drain()
    return dest


# ── Adapter-specific retry policy ────────────────────────────────────────────


def test_effective_max_attempts_precedence(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "webhook_max_attempts", 4)
    # destination override wins
    assert effective_max_attempts("webhook", 7) == 7
    # adapter default (slack = 2) when no destination override
    assert effective_max_attempts("slack", None) == 2
    # global default for webhook (adapter default None)
    assert effective_max_attempts("webhook", None) == 4


def test_slack_destination_uses_tighter_retry_budget(send_fail, monkeypatch):
    monkeypatch.setattr(config_mod.settings, "webhook_max_attempts", 5)
    _emit_event_to("slack")
    # Slack's adapter budget is 2 -> two sweeps exhaust it (vs 5 for webhook).
    delivery_service.deliver_pending()
    assert any(d["status"] == STATUS_PENDING for d in delivery_service.recent_deliveries())
    delivery_service.deliver_pending()
    failed = delivery_service.recent_deliveries(status=STATUS_FAILED)
    assert failed and failed[0]["attempts"] == 2


# ── Health classification ────────────────────────────────────────────────────


def test_health_healthy_then_failing(monkeypatch, send_fail):
    monkeypatch.setattr(config_mod.settings, "webhook_max_attempts", 1)
    dest = _emit_event_to("webhook")
    # Before delivery attempts -> healthy.
    assert delivery_service.destination_health_one(dest["id"])["health"] == "healthy"
    delivery_service.deliver_pending()  # all fail terminally
    h = delivery_service.destination_health_one(dest["id"])
    assert h["health"] in ("failing", "cooling_down") and h["failed_terminal"] >= 1


def test_disabled_destination_is_labeled_disabled():
    dest = _dest(enabled=False)
    assert delivery_service.destination_health_one(dest["id"])["health"] == "disabled"


# ── Cooldown: bounded, visible, recoverable ──────────────────────────────────


def test_repeated_failures_trigger_cooldown(monkeypatch, send_fail):
    monkeypatch.setattr(config_mod.settings, "webhook_max_attempts", 1)
    monkeypatch.setattr(config_mod.settings, "webhook_cooldown_threshold", 2)
    monkeypatch.setattr(config_mod.settings, "webhook_cooldown_seconds", 600)
    dest = _dest(kind="webhook")
    # Generate two terminal failures by enqueuing + draining twice.
    for _ in range(2):
        h = f"cd_{uuid4().hex[:6]}"
        execution_queue.register_handler(h, lambda j: {"ok": True})
        execution_queue.enqueue(f"account:{uuid4().hex}", h, {}, title="T")
        execution_queue.drain()
        delivery_service.deliver_pending()
    health = delivery_service.destination_health_one(dest["id"])
    assert health["cooling_down"] is True and health["health"] == "cooling_down"
    assert health["consecutive_failures"] >= 2


def test_cooldown_skips_routing_honestly(monkeypatch):
    # A cooling-down destination is skipped during alert routing — no fake delivery.
    monkeypatch.setattr(config_mod.settings, "webhook_suppress_seconds", 0)
    dest = _dest(subscription="alerts", min_severity="warning")
    from app.webhooks import _utc_now
    from datetime import timedelta
    with SessionLocal() as s:
        row = s.get(WebhookDestination, dest["id"])
        row.cooldown_until = _utc_now() + timedelta(seconds=300)
        s.commit()
    alert = {"classification": "stuck", "severity": "critical", "job_id": "cd-skip"}
    detailed = delivery_service.route_alerts_detailed([alert])
    assert detailed["routed"] == 0 and detailed["skipped"] >= 1
    assert delivery_service.recent_deliveries(destination_id=dest["id"]) == []  # no record


def test_success_recovers_from_unhealthy(monkeypatch):
    dest = _dest(kind="webhook")
    from app.webhooks import _utc_now
    from datetime import timedelta
    # Cooling down, AND an already-pending delivery exists (e.g. a redrive). Routing
    # is skipped while cooling, but an existing pending delivery still attempts —
    # and a success is the honest recovery: streak + cooldown clear.
    with SessionLocal() as s:
        row = s.get(WebhookDestination, dest["id"])
        row.consecutive_failures = 9
        row.cooldown_until = _utc_now() + timedelta(seconds=300)
        s.add(WebhookDelivery(id=uuid4().hex, destination_id=dest["id"], source_type="observability",
                              status=STATUS_PENDING, attempts=0, payload_json="{}"))
        s.commit()
    monkeypatch.setattr(delivery_service, "_send",
                        (lambda self, url, body, secret: (True, 200, None)).__get__(delivery_service))
    delivery_service.deliver_pending()
    health = delivery_service.destination_health_one(dest["id"])
    assert health["cooling_down"] is False and health["consecutive_failures"] == 0


def test_operator_clear_cooldown(op):
    dest = _dest()
    with SessionLocal() as s:
        row = s.get(WebhookDestination, dest["id"])
        from app.webhooks import _utc_now
        from datetime import timedelta
        row.cooldown_until = _utc_now() + timedelta(seconds=300)
        row.consecutive_failures = 5
        s.commit()
    assert client.post(f"/operator/destinations/{dest['id']}/cooldown/clear", headers=OP).json()["ok"] is True
    assert delivery_service.destination_health_one(dest["id"])["cooling_down"] is False


# ── Health-aware escalation ──────────────────────────────────────────────────


def test_escalation_eligibility_reflects_health(monkeypatch):
    dest = _dest(subscription="alerts", escalate_after=2)
    # Healthy escalation target -> eligible.
    assert delivery_service.destination_health_one(dest["id"])["escalation_eligible"] is True
    # Cooling down -> not eligible.
    with SessionLocal() as s:
        row = s.get(WebhookDestination, dest["id"])
        from app.webhooks import _utc_now
        from datetime import timedelta
        row.cooldown_until = _utc_now() + timedelta(seconds=300)
        s.commit()
    assert delivery_service.destination_health_one(dest["id"])["escalation_eligible"] is False


# ── Config validation ────────────────────────────────────────────────────────


def test_invalid_cooldown_config_rejected():
    with pytest.raises(ValueError):
        Settings(webhook_cooldown_threshold=0)
    with pytest.raises(ValueError):
        Settings(webhook_cooldown_seconds=-1)


# ── HTTP: operator policy/health + separation ────────────────────────────────


def test_policy_and_health_endpoints(op):
    dest = _dest(kind="slack")
    policy = client.get(f"/operator/destinations/{dest['id']}/policy", headers=OP).json()["policy"]
    assert policy["max_attempts"] == 2 and policy["max_attempts_source"] == "adapter" and policy["backoff"] == "fast"
    health = client.get(f"/operator/destinations/{dest['id']}/health", headers=OP).json()["health"]
    assert health["health"] in ("healthy", "disabled") and "secret" not in health


def test_policy_requires_operator(op):
    dest = _dest()
    acct = _account()
    denied = client.get(f"/operator/destinations/{dest['id']}/policy",
                        headers={"Authorization": f"Bearer {make_account_token(acct['id'])}"})
    assert denied.status_code in (401, 403)


def test_max_attempts_override_over_http(op):
    created = client.post("/operator/destinations", headers=OP, json={
        "name": "w", "url": "https://h.example.com/w", "subscription": "events", "max_attempts": 8}).json()["destination"]
    assert created["max_attempts"] == 8 and created["effective_max_attempts"] == 8
    assert "secret" not in created


def test_policy_does_not_leak_to_user_surfaces():
    assert client.get("/operator/destinations/x/policy").status_code in (401, 403, 404)
    owner = _account()
    job = execution_queue.enqueue(f"account:{owner['id']}", "noop", {}, title="T")
    auth = {"Authorization": f"Bearer {make_account_token(owner['id'])}"}
    user_job = client.get(f"/jobs/{job['id']}", headers=auth).json()["job"]
    for operator_only in ("max_attempts", "cooling_down", "cooldown_until", "consecutive_failures", "escalation_eligible"):
        assert operator_only not in user_job
