# File: backend/tests/test_webhook_redrive.py
"""Delivery redrive, dead-letter controls, and destination adapters (F-9).

Terminal-failed deliveries can be redriven safely (a real new attempt, bounded,
idempotent, lineage-preserving), are inspectable as classified dead-letters, and
flow through a per-kind adapter (webhook today, slack stub). Operator-only;
secrets stay hidden; the clean export contract and user separation hold."""

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
from app.webhooks import (
    DL_EXHAUSTED,
    DL_REDRIVE_CANDIDATE,
    DL_REDRIVEN,
    DL_RESOLVED,
    KIND_SLACK,
    STATUS_DELIVERED,
    STATUS_FAILED,
    STATUS_PENDING,
    adapter_for,
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


def _send_to(monkeypatch, ok):
    """Pin the transport outcome (ok -> 200, else -> 500)."""
    result = (True, 200, None) if ok else (False, 500, "HTTP500")
    monkeypatch.setattr(delivery_service, "_send",
                        (lambda self, url, body, secret: result).__get__(delivery_service))


def _make_failed_delivery(monkeypatch, *, kind="webhook"):
    """Produce one terminal-FAILED delivery (events destination, send always fails)."""
    monkeypatch.setattr(config_mod.settings, "webhook_max_attempts", 1)
    dest = delivery_service.create_destination(name="d", url="https://h.example.com/x",
                                               kind=kind, subscription="events")
    handler = f"rd_{uuid4().hex[:6]}"
    execution_queue.register_handler(handler, lambda j: {"ok": True})
    execution_queue.enqueue(f"account:{uuid4().hex}", handler, {}, title="T")
    execution_queue.drain()
    _send_to(monkeypatch, ok=False)
    delivery_service.deliver_pending()
    failed = delivery_service.recent_deliveries(status=STATUS_FAILED)
    return dest, failed[0]


# ── Redrive ──────────────────────────────────────────────────────────────────


def test_redrive_creates_new_attempt_with_preserved_correlation(monkeypatch):
    _, failed = _make_failed_delivery(monkeypatch)
    res = delivery_service.redrive(failed["id"])
    assert res["ok"] is True
    child = res["delivery"]
    assert child["id"] != failed["id"] and child["status"] == STATUS_PENDING
    assert child["redrive_of"] == failed["id"] and child["is_redrive"] is True
    # Source/destination correlation preserved.
    assert child["source_type"] == failed["source_type"] and child["event_type"] == failed["event_type"]
    assert child["destination_id"] == failed["destination_id"]


def test_redrive_then_success_resolves_dead_letter(monkeypatch):
    _, failed = _make_failed_delivery(monkeypatch)
    delivery_service.redrive(failed["id"])
    _send_to(monkeypatch, ok=True)             # the redrive attempt succeeds
    delivery_service.deliver_pending()
    dl = {d["id"]: d for d in delivery_service.dead_letters()}
    assert dl[failed["id"]]["dead_letter_state"] == DL_RESOLVED
    assert dl[failed["id"]]["redrive_count"] == 1


def test_duplicate_redrive_is_idempotent(monkeypatch):
    _, failed = _make_failed_delivery(monkeypatch)
    a = delivery_service.redrive(failed["id"])
    b = delivery_service.redrive(failed["id"])  # one already in flight
    assert a["delivery"]["id"] == b["delivery"]["id"]
    # Exactly one redrive child was created for this failed delivery (no duplicate).
    children = [d for d in delivery_service.recent_deliveries(limit=200) if d.get("redrive_of") == failed["id"]]
    assert len(children) == 1


def test_non_failed_delivery_cannot_be_redriven(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "webhook_max_attempts", 4)
    delivery_service.create_destination(name="d", url="https://h.example.com/x", subscription="events")
    execution_queue.register_handler("rd_ok", lambda j: {"ok": True})
    execution_queue.enqueue(f"account:{uuid4().hex}", "rd_ok", {}, title="T")
    execution_queue.drain()
    pending = delivery_service.recent_deliveries(status=STATUS_PENDING)[0]
    res = delivery_service.redrive(pending["id"])
    assert res["ok"] is False and "failed" in res["message"].lower()


def test_redrive_is_bounded(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "webhook_max_redrives", 2)
    _, failed = _make_failed_delivery(monkeypatch)
    _send_to(monkeypatch, ok=False)
    # Each redrive attempt fails terminally; after the cap, redrive is refused.
    for _ in range(2):
        r = delivery_service.redrive(failed["id"])
        assert r["ok"] is True
        delivery_service.deliver_pending()  # child fails
    refused = delivery_service.redrive(failed["id"])
    assert refused["ok"] is False and "limit" in refused["message"].lower()
    dl = {d["id"]: d for d in delivery_service.dead_letters()}
    assert dl[failed["id"]]["dead_letter_state"] == DL_EXHAUSTED


# ── Dead-letter classification ───────────────────────────────────────────────


def test_dead_letter_states(monkeypatch):
    _, failed = _make_failed_delivery(monkeypatch)
    dl = {d["id"]: d for d in delivery_service.dead_letters()}
    assert dl[failed["id"]]["dead_letter_state"] == DL_REDRIVE_CANDIDATE
    delivery_service.redrive(failed["id"])  # now in flight
    dl = {d["id"]: d for d in delivery_service.dead_letters()}
    assert dl[failed["id"]]["dead_letter_state"] == DL_REDRIVEN


def test_dead_letters_only_lists_original_failures(monkeypatch):
    _, failed = _make_failed_delivery(monkeypatch)
    delivery_service.redrive(failed["id"])
    _send_to(monkeypatch, ok=False)
    delivery_service.deliver_pending()  # the redrive child also fails
    # The redrive CHILD (which has redrive_of set) is not itself a dead-letter row.
    listed = delivery_service.dead_letters()
    assert all(d["id"] == failed["id"] for d in listed) or all(d["redrive_of"] is None for d in listed)


# ── Adapters ─────────────────────────────────────────────────────────────────


def test_adapter_registry_resolves_by_kind():
    assert adapter_for("webhook").kind == "webhook"
    assert adapter_for("slack").kind == "slack"
    assert adapter_for("unknown").kind == "webhook"  # safe fallback


def test_slack_adapter_reshapes_payload():
    dest = type("D", (), {"url": "https://hooks.slack.com/x", "secret": None, "kind": "slack"})()
    url, body, secret = adapter_for("slack").prepare(dest, {"classification": "stuck", "severity": "warning", "job_id": "J1"})
    import json
    shaped = json.loads(body)
    assert "text" in shaped and "stuck" in shaped["text"] and secret is None


def test_slack_destination_delivers_through_slack_adapter(monkeypatch, op):
    captured = {}
    def _fake(self, url, body, secret):
        captured["body"] = body
        return (True, 200, None)
    monkeypatch.setattr(delivery_service, "_send", _fake.__get__(delivery_service))
    delivery_service.create_destination(name="slack", url="https://hooks.slack.com/x",
                                        kind=KIND_SLACK, subscription="events")
    execution_queue.register_handler("rd_slack", lambda j: {"ok": True})
    execution_queue.enqueue(f"account:{uuid4().hex}", "rd_slack", {}, title="T")
    execution_queue.drain()
    delivery_service.deliver_pending()
    assert '"text"' in captured.get("body", "")  # Slack-shaped, not the raw event


# ── HTTP gating + separation ─────────────────────────────────────────────────


def test_redrive_and_dead_letters_require_operator(op, monkeypatch):
    _, failed = _make_failed_delivery(monkeypatch)
    # Operator allowed.
    assert client.post(f"/operator/deliveries/{failed['id']}/redrive", headers=OP).status_code == 200
    assert client.get("/operator/deliveries/dead-letters", headers=OP).status_code == 200
    # Account token denied.
    acct = _account()
    denied = client.post(f"/operator/deliveries/{failed['id']}/redrive",
                         headers={"Authorization": f"Bearer {make_account_token(acct['id'])}"})
    assert denied.status_code in (401, 403)


def test_redrive_completed_delivery_is_409(op, monkeypatch):
    monkeypatch.setattr(config_mod.settings, "webhook_max_attempts", 4)
    _send_to(monkeypatch, ok=True)
    delivery_service.create_destination(name="d", url="https://h.example.com/x", subscription="events")
    execution_queue.register_handler("rd_ok2", lambda j: {"ok": True})
    execution_queue.enqueue(f"account:{uuid4().hex}", "rd_ok2", {}, title="T")
    execution_queue.drain()
    delivery_service.deliver_pending()
    delivered = delivery_service.recent_deliveries(status=STATUS_DELIVERED)[0]
    assert client.post(f"/operator/deliveries/{delivered['id']}/redrive", headers=OP).status_code == 409


def test_no_redrive_or_dead_letter_leak_to_users():
    # No user-facing routes; user job API unchanged.
    assert client.post("/deliveries/x/redrive").status_code == 404
    assert client.get("/deliveries/dead-letters").status_code == 404
    owner = _account()
    job = execution_queue.enqueue(f"account:{owner['id']}", "noop", {}, title="T")
    auth = {"Authorization": f"Bearer {make_account_token(owner['id'])}"}
    user_job = client.get(f"/jobs/{job['id']}", headers=auth).json()["job"]
    for operator_only in ("redrive_of", "dead_letter_state", "destination_id", "secret"):
        assert operator_only not in user_job
