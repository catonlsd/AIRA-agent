# File: backend/tests/test_operator_inspect.py
"""Operator-safe observability — curated run/job inspection + correlated timelines.

A service-key operator can inspect a job/run, see retry/replay/cancel lineage, and
read an ordered timeline — without raw DB spelunking. Strictly gated: normal
account tokens get 403, missing ids get 404, and the curated payload never carries
raw payloads/stack traces/trace blobs. The user-facing job API gains no operator
fields (clean separation)."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.accounts import account_service
from app.auth import make_account_token
import app.core.config as config_mod
from app.execution_queue import RUNNING, execution_queue
from app.job_handlers import register_default_handlers
from app.main import app
from app.middleware import reset_rate_limit
from app.services.trace_service import TraceService

register_default_handlers()
client = TestClient(app)

OP = {"X-API-Key": "service-secret"}


@pytest.fixture
def op(monkeypatch):
    """Configure a service key so an operator principal exists. Opt-in (NOT
    autouse): a configured api_key globally gates every route, so tests that
    exercise the *user* surface must run without it."""
    monkeypatch.setattr(config_mod.settings, "api_key", "service-secret")
    reset_rate_limit()
    yield


def _account():
    return account_service.register(f"u_{uuid4().hex[:10]}@example.com", "password123", "Alice")


def _fail_handler():
    execution_queue.register_handler("op_fail", lambda j: (_ for _ in ()).throw(RuntimeError("boom detail")))


# ── Gating ───────────────────────────────────────────────────────────────────


def test_inspection_requires_operator_key(op):
    owner = f"account:{uuid4().hex}"
    job = execution_queue.enqueue(owner, "noop", {}, title="T")
    # No key, and a normal account token, are both denied.
    assert client.get(f"/operator/jobs/{job['id']}").status_code in (401, 403)
    acct = _account()
    denied = client.get(f"/operator/jobs/{job['id']}", headers={"Authorization": f"Bearer {make_account_token(acct['id'])}"})
    assert denied.status_code in (401, 403)


def test_missing_job_and_run_are_404(op):
    assert client.get("/operator/jobs/nope", headers=OP).status_code == 404
    assert client.get("/operator/runs/nope", headers=OP).status_code == 404


# ── Curated job view ─────────────────────────────────────────────────────────


def test_operator_job_view_is_curated_and_clean(op):
    owner = _account()
    _fail_handler()
    job = execution_queue.enqueue(f"account:{owner['id']}", "op_fail", {"secret": "raw-payload"}, title="T", actor_account_id=owner["id"])
    import app.execution_queue as eq
    original = eq.settings.job_max_attempts
    eq.settings.job_max_attempts = 1
    try:
        execution_queue.drain()
    finally:
        eq.settings.job_max_attempts = original

    view = client.get(f"/operator/jobs/{job['id']}", headers=OP).json()["job"]
    assert view["status"] == "failed"
    assert view["scope"]["type"] == "account" and view["scope"]["id"] == owner["id"]
    assert view["actor"]["display_name"] == "Alice"  # operator may see actor
    assert view["result_summary"]["failure_class"] == "RuntimeError"  # class, not message
    # Never raw payloads / full errors / trace blobs.
    for banned in ("payload_json", "result_json", "payload", "trace_events", "owner"):
        assert banned not in view
    # The full error message is summarized away (only the class is kept).
    assert "boom detail" not in str(view)


# ── Lineage: retry & replay ──────────────────────────────────────────────────


def test_retry_lineage_is_visible_to_operator(op):
    owner = f"account:{uuid4().hex}"
    _fail_handler()
    job = execution_queue.enqueue(owner, "op_fail", {})
    import app.execution_queue as eq
    original = eq.settings.job_max_attempts
    eq.settings.job_max_attempts = 1
    try:
        execution_queue.drain()
    finally:
        eq.settings.job_max_attempts = original
    retry = execution_queue.retry(owner, job["id"])["job"]

    parent_view = client.get(f"/operator/jobs/{job['id']}", headers=OP).json()["job"]
    assert parent_view["lineage"]["retried_into"] == [retry["id"]]
    child_view = client.get(f"/operator/jobs/{retry['id']}", headers=OP).json()["job"]
    assert child_view["lineage"]["origin"] == "retry" and child_view["lineage"]["parent_job_id"] == job["id"]


def test_replay_lineage_is_visible_to_operator(op):
    owner = f"account:{uuid4().hex}"
    execution_queue.register_handler("op_ok", lambda j: {"ok": True})
    job = execution_queue.enqueue(owner, "op_ok", {})
    execution_queue.drain()
    replay = execution_queue.replay(job["id"])

    parent_view = client.get(f"/operator/jobs/{job['id']}", headers=OP).json()["job"]
    assert parent_view["lineage"]["replayed_into"] == [replay["id"]]
    assert client.get(f"/operator/jobs/{replay['id']}", headers=OP).json()["job"]["lineage"]["origin"] == "replay"


# ── Timeline ─────────────────────────────────────────────────────────────────


def test_job_timeline_queued_running_completed(op):
    owner = f"account:{uuid4().hex}"
    execution_queue.register_handler("op_ok2", lambda j: {"ok": True})
    job = execution_queue.enqueue(owner, "op_ok2", {}, title="T")
    execution_queue.drain()
    timeline = client.get(f"/operator/jobs/{job['id']}/timeline", headers=OP).json()["timeline"]
    states = [e["state"] for e in timeline]
    assert states[0] == "queued" and "running" in states and states[-1] == "completed"


def test_canceled_timeline_is_honest(op):
    owner = f"account:{uuid4().hex}"
    job = execution_queue.enqueue(owner, "noop", {}, title="T")
    execution_queue.request_cancel(owner, job["id"])  # queued -> canceled
    view = client.get(f"/operator/jobs/{job['id']}", headers=OP).json()["job"]
    assert view["status"] == "canceled" and view["phase"]["label"] == "Canceled"
    timeline = client.get(f"/operator/jobs/{job['id']}/timeline", headers=OP).json()["timeline"]
    assert any(e["state"] == "canceled" for e in timeline)


# ── Run (trace) inspection ───────────────────────────────────────────────────


def test_operator_run_view_and_timeline_from_trace(op):
    owner = f"account:{uuid4().hex}"
    run_id = uuid4().hex
    tracer = TraceService()
    tracer.persist(tracer.build_record(
        session_id="s", run_id=run_id, mode="research_then_execution", latency_ms=42,
        final_status="completed", owner=owner,
        trace_events=[{"event": "stage", "stage": "planning"}, {"event": "stage", "stage": "executing_workflow"}],
    ))
    view = client.get(f"/operator/runs/{run_id}", headers=OP).json()["run"]
    assert view["label"] == "Research & build" and view["status"] == "completed"
    assert "planning" in view["stages"]
    timeline = client.get(f"/operator/runs/{run_id}/timeline", headers=OP).json()["timeline"]
    labels = [e["label"] for e in timeline]
    assert "Turn started" in labels and "planning" in labels


# ── Listing / locating ───────────────────────────────────────────────────────


def test_list_jobs_filters_by_failures_and_origin(op):
    owner = f"account:{uuid4().hex}"
    _fail_handler()
    failed = execution_queue.enqueue(owner, "op_fail", {}, title="bad")
    import app.execution_queue as eq
    original = eq.settings.job_max_attempts
    eq.settings.job_max_attempts = 1
    try:
        execution_queue.drain()
    finally:
        eq.settings.job_max_attempts = original
    listed = client.get("/operator/jobs", params={"failures": True}, headers=OP).json()["jobs"]
    assert any(j["job_id"] == failed["id"] and j["failure_class"] == "RuntimeError" for j in listed)


# ── Separation: user API never gains operator fields ─────────────────────────


def test_user_job_api_has_no_operator_fields():
    owner = _account()
    job = execution_queue.enqueue(f"account:{owner['id']}", "noop", {}, title="T")
    user_job = client.get(f"/jobs/{job['id']}", headers={"Authorization": f"Bearer {make_account_token(owner['id'])}"}).json()["job"]
    # The user surface stays minimal — no scope/owner/actor/lineage/queue internals.
    for operator_only in ("exec_class", "priority", "owner", "scope", "actor", "lineage", "dedup_key", "result_summary"):
        assert operator_only not in user_job
