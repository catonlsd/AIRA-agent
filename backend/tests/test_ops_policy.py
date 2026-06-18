# File: backend/tests/test_ops_policy.py
"""Operational policy — SLOs, stuck-job detection, alert-ready classification.

Durable job state + timestamps drive a small set of health classifications
(healthy / stuck / retry_exhausted / triage_needed / resolved / backlog_pressure),
each with a severity and a human reason. Honours lineage/resolution; operator-only;
never leaks into user surfaces."""

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.accounts import account_service
from app.auth import make_account_token
import app.core.config as config_mod
from app.core.config import Settings
from app.db.database import SessionLocal
from app.db.models import ExecutionJob
import app.execution_queue as eq
from app.execution_queue import execution_queue
from app.job_handlers import register_default_handlers
from app.main import app
from app.middleware import reset_rate_limit
from app.ops_policy import (
    BACKLOG_PRESSURE,
    HEALTHY,
    RESOLVED,
    RETRY_EXHAUSTED,
    SEV_CRITICAL,
    SEV_WARNING,
    SLOPolicy,
    STUCK,
    ops_policy,
)

register_default_handlers()
client = TestClient(app)
OP = {"X-API-Key": "service-secret"}

# A tight policy for deterministic tests (thresholds in seconds).
TIGHT = SLOPolicy(enabled=True, queued_seconds=300,
                  running_seconds={"default": 120, "artifact": 600, "validation": 300, "maintenance": 600},
                  cancel_seconds=60, backlog_threshold=2)


@pytest.fixture
def op(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "api_key", "service-secret")
    reset_rate_limit()
    yield


def _account():
    return account_service.register(f"u_{uuid4().hex[:10]}@example.com", "password123", "Alice")


def _age(job_id: str, *, status=None, seconds_ago_created=None, seconds_ago_started=None,
         seconds_ago_updated=None, exec_class=None):
    """Push a job's durable timestamps into the past to simulate elapsed time."""
    from app.ops_policy import _now
    now = _now()
    with SessionLocal() as s:
        row = s.get(ExecutionJob, job_id)
        if status:
            row.status = status
        if exec_class:
            row.exec_class = exec_class
        if seconds_ago_created is not None:
            row.created_at = now - timedelta(seconds=seconds_ago_created)
        if seconds_ago_started is not None:
            row.started_at = now - timedelta(seconds=seconds_ago_started)
        if seconds_ago_updated is not None:
            row.updated_at = now - timedelta(seconds=seconds_ago_updated)
        s.commit()


def _classify(job_id: str, policy=TIGHT):
    with SessionLocal() as s:
        row = s.get(ExecutionJob, job_id)
        children = s.query(ExecutionJob).filter(ExecutionJob.parent_job_id == job_id).all()
        from app.ops_policy import _now
        return ops_policy.classify_job(row, now=_now(), children=children, policy=policy)


def _drain_default():
    execution_queue.drain()


# ── Per-job classification ───────────────────────────────────────────────────


def test_fresh_queued_job_is_healthy():
    owner = f"account:{uuid4().hex}"
    job = execution_queue.enqueue(owner, "noop", {}, title="T")
    assert _classify(job["id"])["classification"] == HEALTHY


def test_queued_too_long_is_stuck():
    owner = f"account:{uuid4().hex}"
    job = execution_queue.enqueue(owner, "noop", {}, title="T")
    _age(job["id"], seconds_ago_created=900)  # > 300s queued budget
    c = _classify(job["id"])
    assert c["classification"] == STUCK and c["severity"] == SEV_WARNING and "Queued" in c["reason"]


def test_running_too_long_is_stuck_critical():
    owner = f"account:{uuid4().hex}"
    job = execution_queue.enqueue(owner, "noop", {}, title="T")
    _age(job["id"], status="running", exec_class="artifact", seconds_ago_started=900)  # > 600s artifact budget
    c = _classify(job["id"])
    assert c["classification"] == STUCK and c["severity"] == SEV_CRITICAL


def test_running_within_class_budget_is_healthy():
    owner = f"account:{uuid4().hex}"
    job = execution_queue.enqueue(owner, "noop", {}, title="T")
    # 300s running is fine for the artifact class (600s budget).
    _age(job["id"], status="running", exec_class="artifact", seconds_ago_started=300)
    assert _classify(job["id"])["classification"] == HEALTHY


def test_cancel_requested_too_long_is_stuck():
    owner = f"account:{uuid4().hex}"
    job = execution_queue.enqueue(owner, "noop", {}, title="T")
    _age(job["id"], status="cancel_requested", seconds_ago_updated=120)  # > 60s cancel budget
    c = _classify(job["id"])
    assert c["classification"] == STUCK and c["severity"] == SEV_CRITICAL


def test_retry_exhausted_failure_is_classified():
    owner = f"account:{uuid4().hex}"
    execution_queue.register_handler("pol_fail", lambda j: (_ for _ in ()).throw(RuntimeError("boom")))
    job = execution_queue.enqueue(owner, "pol_fail", {})
    _drain_default()  # exhausts the default 2 internal attempts
    c = _classify(job["id"])
    assert c["classification"] == RETRY_EXHAUSTED and c["severity"] == SEV_CRITICAL
    assert c["failure_class"] == "RuntimeError"


def test_failed_then_retried_to_completion_is_resolved():
    owner = f"account:{uuid4().hex}"
    calls = {"n": 0}
    def _flaky(job):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("first fails")
        return {"ok": True}
    execution_queue.register_handler("pol_flaky", _flaky)
    original = eq.settings.job_max_attempts
    eq.settings.job_max_attempts = 1
    try:
        job = execution_queue.enqueue(owner, "pol_flaky", {})
        execution_queue.drain()          # original fails
    finally:
        eq.settings.job_max_attempts = original
    execution_queue.retry(owner, job["id"])
    execution_queue.drain()              # retry completes
    assert _classify(job["id"])["classification"] == RESOLVED


def test_canceled_job_is_healthy_not_alertable():
    owner = f"account:{uuid4().hex}"
    job = execution_queue.enqueue(owner, "noop", {}, title="T")
    execution_queue.request_cancel(owner, job["id"])  # queued -> canceled
    assert _classify(job["id"])["classification"] == HEALTHY


# ── Aggregate health + alerts + backlog ──────────────────────────────────────


def test_backlog_pressure_detected_by_policy():
    owner = f"account:{uuid4().hex}"
    for _ in range(3):
        execution_queue.enqueue(owner, "noop", {})  # interactive class, > threshold 2
    snap = ops_policy.health(policy=TIGHT)
    backlog = snap["backlog"]
    assert any(b["exec_class"] == "interactive" and b["queued"] >= 3 for b in backlog)
    assert snap["summary"].get(BACKLOG_PRESSURE, 0) >= 1


def test_alerts_filter_to_warning_and_critical_only():
    owner = f"account:{uuid4().hex}"
    healthy = execution_queue.enqueue(owner, "noop", {}, title="ok")
    stuck = execution_queue.enqueue(owner, "noop", {}, title="stuck")
    _age(stuck["id"], seconds_ago_created=900)
    alerts = ops_policy.alerts(policy=TIGHT)
    ids = {a["job_id"] for a in alerts}
    assert stuck["id"] in ids and healthy["id"] not in ids  # healthy excluded


# ── Config validation ────────────────────────────────────────────────────────


def test_invalid_slo_config_is_rejected():
    with pytest.raises(ValueError):
        Settings(slo_queued_seconds=-1)
    with pytest.raises(ValueError):
        Settings(slo_backlog_threshold=0)


# ── HTTP: operator-gated + clean + separated ─────────────────────────────────


def test_health_and_alerts_require_operator(op):
    assert client.get("/operator/health", headers=OP).status_code == 200
    assert client.get("/operator/alerts", headers=OP).status_code == 200
    acct = _account()
    denied = client.get("/operator/health", headers={"Authorization": f"Bearer {make_account_token(acct['id'])}"})
    assert denied.status_code in (401, 403)


def test_health_payload_is_clean(op):
    owner = f"account:{uuid4().hex}"
    execution_queue.register_handler("pol_fail2", lambda j: (_ for _ in ()).throw(RuntimeError("boom detail")))
    execution_queue.enqueue(owner, "pol_fail2", {"secret": "x"}, title="T")
    _drain_default()
    body = client.get("/operator/health", headers=OP).json()
    assert "classifications" in body and "summary" in body
    blob = str(body)
    for banned in ("payload_json", "trace_events", "boom detail", "secret"):
        assert banned not in blob


def test_policy_does_not_leak_into_user_surfaces():
    # No user-facing health/alerts routes exist.
    assert client.get("/health/policy").status_code == 404
    assert client.get("/alerts").status_code == 404
    owner = _account()
    job = execution_queue.enqueue(f"account:{owner['id']}", "noop", {}, title="T")
    auth = {"Authorization": f"Bearer {make_account_token(owner['id'])}"}
    user_job = client.get(f"/jobs/{job['id']}", headers=auth).json()["job"]
    for operator_only in ("classification", "severity", "exec_class", "reason"):
        assert operator_only not in user_job
