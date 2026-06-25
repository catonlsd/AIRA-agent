# File: backend/tests/test_execution_control.py
"""Execution control — honest cancellation, bounded retry, operator replay.

Cancellation is cooperative (queued cancels outright; running stops at the next
safe checkpoint; terminal jobs are told the truth). Retry of a *failed* job
schedules a real new attempt, idempotently and lineage-linked. Replay is an
operator-only primitive. All scope/role-checked; canceled/retried work records
honest activity."""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.accounts import account_service
from app.activity import RUN_CANCELED, RUN_RETRYING, activity_service
from app.artifacts.service import ArtifactService, _artifact_to_dict
from app.auth import make_account_token
import app.execution_queue as eq
from app.execution_queue import (
    CANCEL_REQUESTED,
    CANCELED,
    COMPLETED,
    FAILED,
    JobCanceled,
    QUEUED,
    execution_queue,
)
from app.job_handlers import JOB_ARTIFACT, register_default_handlers
from app.main import app

register_default_handlers()
client = TestClient(app)


def _account():
    return account_service.register(f"u_{uuid4().hex[:10]}@example.com", "password123", "Alice")


def _auth(account, workspace_id=None):
    h = {"Authorization": f"Bearer {make_account_token(account['id'])}"}
    if workspace_id:
        h["X-Workspace-Id"] = workspace_id
    return h


def _artifact_payload(goal="A deck about Q3", kind="pptx"):
    pending, _ = ArtifactService().plan(goal, kind)
    return _artifact_to_dict(pending)


def _fail_once():
    execution_queue.register_handler("ctl_fail", lambda job: (_ for _ in ()).throw(RuntimeError("boom")))


# ── Cancellation: honest + cooperative ───────────────────────────────────────


def test_queued_job_cancels_outright_and_records_activity():
    owner = f"account:{uuid4().hex}"
    job = execution_queue.enqueue(owner, "noop", {}, title="Big task")
    res = execution_queue.request_cancel(owner, job["id"])
    assert res["ok"] and res["status"] == CANCELED
    assert execution_queue.get(owner, job["id"])["status"] == CANCELED
    assert any(e["type"] == RUN_CANCELED for e in activity_service.recent(owner))


def test_running_job_cancel_is_a_durable_request_not_instant():
    owner = f"account:{uuid4().hex}"
    job = execution_queue.enqueue(owner, "noop", {})
    execution_queue.transition(job["id"], "running")  # now in flight
    res = execution_queue.request_cancel(owner, job["id"])
    # Honest: a running job isn't force-killed — it's marked for cooperative stop.
    assert res["ok"] and res["status"] == CANCEL_REQUESTED
    assert execution_queue.get(owner, job["id"])["status"] == CANCEL_REQUESTED
    # Idempotent: asking again is fine, still cancel_requested.
    assert execution_queue.request_cancel(owner, job["id"])["status"] == CANCEL_REQUESTED


def test_cancel_during_run_discards_result():
    owner = f"account:{uuid4().hex}"
    # Handler completes work, but a cancel arrives mid-run; the honest outcome is
    # canceled and the result is NOT delivered as completed.
    def _slow(job):
        execution_queue.request_cancel(job.owner, job.id)  # cancel arrives during run
        return {"artifact": "should-not-be-delivered"}
    execution_queue.register_handler("slow", _slow)
    job = execution_queue.enqueue(owner, "slow", {})
    execution_queue.drain()
    final = execution_queue.get(owner, job["id"])
    assert final["status"] == CANCELED
    assert final["result"] != {"artifact": "should-not-be-delivered"}


def test_terminal_job_cannot_be_canceled():
    owner = f"account:{uuid4().hex}"
    execution_queue.register_handler("ok", lambda job: {"ok": True})
    job = execution_queue.enqueue(owner, "ok", {})
    execution_queue.drain()
    assert execution_queue.get(owner, job["id"])["status"] == COMPLETED
    res = execution_queue.request_cancel(owner, job["id"])
    assert res["ok"] is False and "finished" in res["message"].lower()
    # The completed job is untouched.
    assert execution_queue.get(owner, job["id"])["status"] == COMPLETED


def test_cancel_is_scope_checked():
    owner = f"account:{uuid4().hex}"
    job = execution_queue.enqueue(owner, "noop", {})
    res = execution_queue.request_cancel(f"account:{uuid4().hex}", job["id"])
    assert res["ok"] is False and res.get("not_found") is True


# ── Retry: honest, bounded, idempotent ───────────────────────────────────────


def test_failed_job_can_be_retried_with_lineage():
    owner = f"account:{uuid4().hex}"
    _fail_once()
    job = execution_queue.enqueue(owner, "ctl_fail", {})
    execution_queue.drain()  # exhausts bounded internal retries -> failed
    assert execution_queue.get(owner, job["id"])["status"] == FAILED
    res = execution_queue.retry(owner, job["id"])
    assert res["ok"] and res["job"]["id"] != job["id"]
    assert res["job"]["origin"] == "retry"  # distinguishable from the original
    assert any(e["type"] == RUN_RETRYING for e in activity_service.recent(owner))


def test_retry_is_idempotent_no_double_execute():
    owner = f"account:{uuid4().hex}"
    _fail_once()
    job = execution_queue.enqueue(owner, "ctl_fail", {})
    execution_queue.drain()
    a = execution_queue.retry(owner, job["id"])
    b = execution_queue.retry(owner, job["id"])  # double click
    assert a["job"]["id"] == b["job"]["id"]  # same in-flight retry, not duplicated

def test_non_failed_job_cannot_be_retried():
    owner = f"account:{uuid4().hex}"
    execution_queue.register_handler("ok2", lambda job: {"ok": True})
    job = execution_queue.enqueue(owner, "ok2", {})
    execution_queue.drain()
    res = execution_queue.retry(owner, job["id"])
    assert res["ok"] is False and "failed" in res["message"].lower()


def test_retry_executes_a_real_new_attempt():
    owner = f"account:{uuid4().hex}"
    # Fail the original, then make the handler succeed and run the retry job.
    calls = {"n": 0}
    def _flaky(job):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("first attempt fails")
        return {"ok": True}
    # job_max_attempts default >1 would re-run internally; force a single attempt.
    import app.execution_queue as _eq
    original = _eq.settings.job_max_attempts
    _eq.settings.job_max_attempts = 1
    try:
        execution_queue.register_handler("flaky", _flaky)
        job = execution_queue.enqueue(owner, "flaky", {})
        execution_queue.drain()
        assert execution_queue.get(owner, job["id"])["status"] == FAILED
        retry = execution_queue.retry(owner, job["id"])
        execution_queue.drain()
        assert execution_queue.get_raw(retry["job"]["id"])["status"] == COMPLETED
    finally:
        _eq.settings.job_max_attempts = original


# ── Operator replay (gated) ──────────────────────────────────────────────────


def test_replay_clones_any_job_as_new_attempt():
    owner = f"account:{uuid4().hex}"
    execution_queue.register_handler("ok3", lambda job: {"ok": True})
    job = execution_queue.enqueue(owner, "ok3", {})
    execution_queue.drain()
    replay = execution_queue.replay(job["id"])
    assert replay["id"] != job["id"] and replay["origin"] == "replay"
    assert replay["status"] == QUEUED


# ── HTTP: cancel/retry are scope + role aware ────────────────────────────────


def test_cancel_endpoint_is_honest_and_scoped():
    owner, outsider = _account(), _account()
    job = execution_queue.enqueue(f"account:{owner['id']}", "noop", {}, title="T")
    # Owner cancels their queued job.
    ok = client.post(f"/jobs/{job['id']}/cancel", headers=_auth(owner)).json()
    assert ok["ok"] is True and ok["status"] == CANCELED
    # Another account can't even see it — 404, no leak.
    assert client.post(f"/jobs/{job['id']}/cancel", headers=_auth(outsider)).status_code == 404


def test_retry_endpoint_returns_new_job():
    owner = _account()
    _fail_once()
    job = execution_queue.enqueue(f"account:{owner['id']}", "ctl_fail", {}, title="T")
    execution_queue.drain()
    res = client.post(f"/jobs/{job['id']}/retry", headers=_auth(owner))
    assert res.status_code == 200 and res.json()["job"]["origin"] == "retry"


def test_retry_completed_job_is_409():
    owner = _account()
    execution_queue.register_handler("ok4", lambda job: {"ok": True})
    job = execution_queue.enqueue(f"account:{owner['id']}", "ok4", {})
    execution_queue.drain()
    assert client.post(f"/jobs/{job['id']}/retry", headers=_auth(owner)).status_code == 409


def test_workspace_viewer_cannot_cancel():
    owner, viewer = _account(), _account()
    ws = client.post("/workspaces", json={"name": "Team"}, headers=_auth(owner)).json()["workspace"]
    from app.workspaces import workspace_service
    workspace_service.add_member(ws["id"], viewer["id"], "viewer")
    job = execution_queue.enqueue(ws["owner_key"], "noop", {}, title="WS")
    # A viewer has view-only — cancel (a mutation) is denied.
    assert client.post(f"/jobs/{job['id']}/cancel", headers=_auth(viewer, ws["id"])).status_code == 403


# ── Worker honors cancel for the real artifact job ───────────────────────────


def test_worker_cancels_artifact_before_generation():
    owner = f"account:{uuid4().hex}"
    job = execution_queue.enqueue(owner, JOB_ARTIFACT, _artifact_payload(), title="PPTX generation")
    # Cancel requested before the worker runs -> the artifact handler's checkpoint
    # bails, the job is canceled, and no artifact_created activity is recorded.
    execution_queue.request_cancel(owner, job["id"])
    execution_queue.drain()
    final = execution_queue.get(owner, job["id"])
    assert final["status"] == CANCELED
    assert all(e["type"] != "artifact_created" for e in activity_service.recent(owner))
