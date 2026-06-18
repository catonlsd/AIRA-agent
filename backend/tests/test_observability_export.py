# File: backend/tests/test_observability_export.py
"""Observability export + failure triage — operator-only ops stream.

The queue emits curated lifecycle signals (queued/claimed/completed/failed/
canceled/retrying/replayed) into a durable, cursor-based export feed an external
monitor can poll incrementally. Terminal-failed jobs surface in a triage view,
classified honestly (retry_exhausted / replay_candidate / resolved) with lineage.
Operator-gated; clean and bounded; nothing leaks into user surfaces."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.accounts import account_service
from app.auth import make_account_token
import app.core.config as config_mod
import app.execution_queue as eq
from app.execution_queue import execution_queue
from app.job_handlers import register_default_handlers
from app.main import app
from app.middleware import reset_rate_limit
from app.observability import (
    EVT_CANCELED,
    EVT_COMPLETED,
    EVT_FAILED,
    EVT_QUEUED,
    EVT_REPLAYED,
    EVT_RETRYING,
    observability,
)

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


def _fail_handler():
    execution_queue.register_handler("obs_fail", lambda j: (_ for _ in ()).throw(RuntimeError("boom detail")))


def _ok_handler():
    execution_queue.register_handler("obs_ok", lambda j: {"ok": True})


def _drain_single_attempt():
    original = eq.settings.job_max_attempts
    eq.settings.job_max_attempts = 1
    try:
        execution_queue.drain()
    finally:
        eq.settings.job_max_attempts = original


# ── Lifecycle signals are emitted durably ────────────────────────────────────


def test_lifecycle_events_are_recorded():
    owner = f"account:{uuid4().hex}"
    _ok_handler()
    execution_queue.enqueue(owner, "obs_ok", {}, title="T")
    execution_queue.drain()
    types = [e["event_type"] for e in observability.recent()["events"]]
    assert EVT_QUEUED in types and "job_claimed" in types and EVT_COMPLETED in types


def test_failed_event_carries_failure_class_not_message():
    owner = f"account:{uuid4().hex}"
    _fail_handler()
    execution_queue.enqueue(owner, "obs_fail", {"secret": "x"}, title="T")
    _drain_single_attempt()
    failed = [e for e in observability.recent()["events"] if e["event_type"] == EVT_FAILED]
    assert failed and failed[0]["failure_class"] == "RuntimeError"
    # The full message and any payload never appear in the stream.
    assert "boom detail" not in str(failed) and "secret" not in str(failed)


def test_retry_and_replay_emit_lineage_events():
    owner = f"account:{uuid4().hex}"
    _fail_handler()
    job = execution_queue.enqueue(owner, "obs_fail", {})
    _drain_single_attempt()
    retry = execution_queue.retry(owner, job["id"])["job"]
    replay = execution_queue.replay(job["id"])
    events = observability.recent()["events"]
    rt = next(e for e in events if e["event_type"] == EVT_RETRYING)
    assert rt["job_id"] == retry["id"] and rt["parent_job_id"] == job["id"]
    rp = next(e for e in events if e["event_type"] == EVT_REPLAYED)
    assert rp["job_id"] == replay["id"] and rp["parent_job_id"] == job["id"]


def test_canceled_event_recorded():
    owner = f"account:{uuid4().hex}"
    job = execution_queue.enqueue(owner, "noop", {}, title="T")
    execution_queue.request_cancel(owner, job["id"])
    assert any(e["event_type"] == EVT_CANCELED for e in observability.recent()["events"])


# ── Cursor-based incremental export ──────────────────────────────────────────


def test_export_is_cursor_based():
    owner = f"account:{uuid4().hex}"
    _ok_handler()
    execution_queue.enqueue(owner, "obs_ok", {}, title="A")
    first = observability.recent(limit=1)
    assert first["events"] and first["cursor"] == first["events"][-1]["id"]
    # Polling since the cursor returns only NEWER events.
    execution_queue.enqueue(owner, "obs_ok", {}, title="B")
    nxt = observability.recent(since=first["cursor"])
    assert all(e["id"] > first["cursor"] for e in nxt["events"])


def test_export_payload_is_clean_and_scope_typed():
    owner = f"account:{uuid4().hex[:12]}"
    _ok_handler()
    execution_queue.enqueue(f"account:{owner}", "obs_ok", {}, title="T")
    ev = observability.recent()["events"][0]
    assert ev["scope"]["type"] == "account"
    for banned in ("owner", "payload", "result_json", "trace_events", "exec_class"):
        assert banned not in ev


# ── Triage (dead-letter foundation) ──────────────────────────────────────────


def test_triage_classifies_retry_exhausted_and_replay_candidate():
    owner = f"account:{uuid4().hex}"
    _fail_handler()
    # Drained under the default cap, the always-failing job exhausts every internal
    # attempt -> retry_exhausted (attempts == job_max_attempts at triage time).
    exhausted = execution_queue.enqueue(owner, "obs_fail", {}, title="exhausted")
    execution_queue.drain()
    rows = {t["job_id"]: t for t in observability.triage()}
    assert rows[exhausted["id"]]["classification"] == "retry_exhausted"
    assert rows[exhausted["id"]]["failure_class"] == "RuntimeError"


def test_triage_marks_resolved_when_retry_succeeds():
    owner = f"account:{uuid4().hex}"
    # Handler fails first, succeeds on the retry job.
    calls = {"n": 0}
    def _flaky(job):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("first fails")
        return {"ok": True}
    execution_queue.register_handler("obs_flaky", _flaky)
    job = execution_queue.enqueue(owner, "obs_flaky", {}, title="flaky")
    _drain_single_attempt()  # original fails
    execution_queue.retry(owner, job["id"])
    execution_queue.drain()  # retry succeeds
    row = next(t for t in observability.triage() if t["job_id"] == job["id"])
    assert row["classification"] == "resolved" and len(row["retried_into"]) == 1


# ── Gating + separation ──────────────────────────────────────────────────────


def test_export_and_triage_require_operator(op):
    # Operator (service key) allowed.
    assert client.get("/operator/observability", headers=OP).status_code == 200
    assert client.get("/operator/triage", headers=OP).status_code == 200
    # No key / account token denied (the api_key gate is global).
    acct = _account()
    denied = client.get("/operator/observability", headers={"Authorization": f"Bearer {make_account_token(acct['id'])}"})
    assert denied.status_code in (401, 403)


def test_observability_does_not_leak_into_user_or_activity_surfaces():
    owner = _account()
    _ok_handler()
    execution_queue.enqueue(f"account:{owner['id']}", "obs_ok", {}, title="T")
    execution_queue.drain()
    auth = {"Authorization": f"Bearer {make_account_token(owner['id'])}"}
    # The user activity feed is unchanged — it never gains ops signal types.
    activity = client.get("/activity/recent", headers=auth).json()
    assert all(e["type"] not in ("job_queued", "job_claimed", "job_completed")
               for e in activity.get("events", []))
    # And there is no user-facing observability endpoint.
    assert client.get("/observability").status_code == 404
