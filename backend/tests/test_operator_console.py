# File: backend/tests/test_operator_console.py
"""Operator delivery-console contract (G-1).

The frontend operator console is backed ONLY by these already-gated /operator/*
APIs. This pins that dependency set: every console endpoint is operator-only
(unavailable to normal users / account tokens), returns curated payloads, and
never leaks a destination secret. Heavy on the separation guarantee the console
relies on — a normal product deployment (no service key) exposes none of it."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.accounts import account_service
from app.auth import make_account_token
import app.core.config as config_mod
from app.db.database import ensure_runtime_columns
from app.execution_queue import execution_queue
from app.job_handlers import register_default_handlers
from app.main import app
from app.middleware import reset_rate_limit
from app.webhooks import delivery_service

ensure_runtime_columns()
register_default_handlers()
client = TestClient(app)
OP = {"X-API-Key": "service-secret"}

# Exactly the endpoints the console (frontend/lib/operator.ts) calls.
CONSOLE_GET = [
    "/operator/overview",
    "/operator/delivery/analytics",
    "/operator/delivery/health",
    "/operator/deliveries/dead-letters",
    "/operator/destinations",
]


@pytest.fixture
def op(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "api_key", "service-secret")
    reset_rate_limit()
    yield


def _account():
    return account_service.register(f"u_{uuid4().hex[:10]}@example.com", "password123", "Alice")


# ── Separation: the console surface is unavailable to normal users ───────────


def test_console_endpoints_unavailable_without_service_key():
    # Default product deployment (no api_key): the operator console simply does
    # not exist — every endpoint denies, even a normal account token.
    acct = _account()
    auth = {"Authorization": f"Bearer {make_account_token(acct['id'])}"}
    for path in CONSOLE_GET:
        assert client.get(path).status_code in (401, 403)
        assert client.get(path, headers=auth).status_code in (401, 403)


def test_console_endpoints_require_the_service_key(op):
    acct = _account()
    auth = {"Authorization": f"Bearer {make_account_token(acct['id'])}"}
    for path in CONSOLE_GET:
        assert client.get(path, headers=OP).status_code == 200       # operator OK
        assert client.get(path, headers=auth).status_code in (401, 403)  # account token NOT


# ── Curated, secret-free payloads ────────────────────────────────────────────


def test_destination_health_payload_is_clean_and_actionable(op):
    dest = delivery_service.create_destination(
        name="ops", url="https://hooks.example.com/x", subscription="alerts",
        min_severity="warning", secret="s3cr3t", escalate_after=3)
    health = client.get("/operator/delivery/health", headers=OP).json()["destinations"]
    one = next(h for h in health if h["destination_id"] == dest["id"])
    # Actionable fields the console renders…
    assert one["health"] == "healthy" and one["reason"]
    assert one["is_escalation"] is True and "escalation_eligible" in one and "cooling_down" in one
    # …but never the secret.
    assert "secret" not in str(health)


def test_destinations_and_policy_never_return_secret(op):
    dest = delivery_service.create_destination(
        name="ops2", url="https://hooks.example.com/y", subscription="events", secret="hidden")
    listed = client.get("/operator/destinations", headers=OP).json()["destinations"]
    one = next(d for d in listed if d["id"] == dest["id"])
    assert one["has_secret"] is True and "secret" not in one
    policy = client.get(f"/operator/destinations/{dest['id']}/policy", headers=OP).json()["policy"]
    assert "max_attempts" in policy and "backoff" in policy and "secret" not in str(policy)


def test_console_redrive_and_cooldown_actions_are_gated(op):
    # Redrive of a missing delivery is an honest 404 for the operator; a normal
    # user can't reach the action at all.
    assert client.post("/operator/deliveries/none/redrive", headers=OP).status_code == 404
    acct = _account()
    auth = {"Authorization": f"Bearer {make_account_token(acct['id'])}"}
    assert client.post("/operator/deliveries/none/redrive", headers=auth).status_code in (401, 403)
    dest = delivery_service.create_destination(name="c", url="https://h.example.com/c", subscription="events")
    assert client.post(f"/operator/destinations/{dest['id']}/cooldown/clear", headers=OP).status_code == 200
    assert client.post(f"/operator/destinations/{dest['id']}/cooldown/clear", headers=auth).status_code in (401, 403)


# ── Delivery history + redrive lineage (G-2) ─────────────────────────────────


def _make_failed_delivery(monkeypatch):
    """One terminal-failed original delivery on an events destination."""
    monkeypatch.setattr(config_mod.settings, "webhook_max_attempts", 1)
    dest = delivery_service.create_destination(name="hist", url="https://h.example.com/x",
                                               kind="webhook", subscription="events")
    handler = f"con_{uuid4().hex[:6]}"
    execution_queue.register_handler(handler, lambda j: {"ok": True})
    execution_queue.enqueue(f"account:{uuid4().hex}", handler, {}, title="T")
    execution_queue.drain()
    monkeypatch.setattr(delivery_service, "_send",
                        (lambda self, url, body, secret: (False, 500, "HTTP500")).__get__(delivery_service))
    delivery_service.deliver_pending()
    failed = delivery_service.recent_deliveries(status="failed")
    return dest, failed[0]


def test_delivery_history_is_filterable_and_named(op, monkeypatch):
    dest, _ = _make_failed_delivery(monkeypatch)
    # History carries the destination NAME and supports a status filter.
    failed = client.get("/operator/deliveries", params={"status": "failed"}, headers=OP).json()["deliveries"]
    assert failed and any(d["destination_name"] == "hist" for d in failed)
    assert all(d["status"] == "failed" for d in failed)
    # No payloads/secrets in the history rows.
    assert "payload_json" not in str(failed) and "secret" not in str(failed)


def test_delivery_lineage_chains_original_and_redrives(op, monkeypatch):
    dest, failed = _make_failed_delivery(monkeypatch)
    delivery_service.redrive(failed["id"])  # one redrive attempt
    lineage = client.get(f"/operator/deliveries/{failed['id']}/lineage", headers=OP).json()["lineage"]
    assert lineage["root_id"] == failed["id"] and lineage["destination_name"] == "hist"
    assert len(lineage["attempts"]) == 2  # original + redrive
    assert lineage["attempts"][1]["is_redrive"] is True
    # Looking up lineage from the CHILD resolves back to the same root chain.
    child_id = lineage["attempts"][1]["id"]
    via_child = client.get(f"/operator/deliveries/{child_id}/lineage", headers=OP).json()["lineage"]
    assert via_child["root_id"] == failed["id"]
    assert "payload_json" not in str(lineage)


def test_lineage_requires_operator(op, monkeypatch):
    _, failed = _make_failed_delivery(monkeypatch)
    acct = _account()
    auth = {"Authorization": f"Bearer {make_account_token(acct['id'])}"}
    assert client.get(f"/operator/deliveries/{failed['id']}/lineage", headers=auth).status_code in (401, 403)
    assert client.get("/operator/deliveries/none/lineage", headers=OP).status_code == 404


# ── Destination tuning from the console (PATCH) ──────────────────────────────


def test_destination_tuning_via_patch(op):
    dest = delivery_service.create_destination(name="tune", url="https://h.example.com/t",
                                               subscription="alerts", min_severity="warning", secret="s")
    upd = client.patch(f"/operator/destinations/{dest['id']}", headers=OP, json={
        "min_severity": "critical", "alert_filter": "stuck,retry_exhausted",
        "suppress_seconds": 120, "escalate_after": 3, "enabled": False}).json()["destination"]
    assert upd["min_severity"] == "critical" and upd["alert_filter"] == "stuck,retry_exhausted"
    assert upd["suppress_seconds"] == 120 and upd["escalate_after"] == 3 and upd["enabled"] is False
    # The PATCH never returns the secret.
    assert "secret" not in upd and upd["has_secret"] is True
    # Invalid tuning is rejected, not silently applied.
    assert client.patch(f"/operator/destinations/{dest['id']}", headers=OP,
                        json={"min_severity": "bogus"}).status_code == 404


def test_tuning_is_operator_only(op):
    dest = delivery_service.create_destination(name="t2", url="https://h.example.com/t2", subscription="alerts")
    acct = _account()
    auth = {"Authorization": f"Bearer {make_account_token(acct['id'])}"}
    assert client.patch(f"/operator/destinations/{dest['id']}", headers=auth,
                        json={"enabled": False}).status_code in (401, 403)


# ── No operator fields leak into the user product ────────────────────────────


def test_no_operator_console_fields_leak_into_user_routes():
    owner = _account()
    job = execution_queue.enqueue(f"account:{owner['id']}", "noop", {}, title="T")
    auth = {"Authorization": f"Bearer {make_account_token(owner['id'])}"}
    user_job = client.get(f"/jobs/{job['id']}", headers=auth).json()["job"]
    for operator_only in ("health", "reason", "escalation_eligible", "cooling_down",
                          "destination_id", "dead_letter_state", "has_secret"):
        assert operator_only not in user_job
