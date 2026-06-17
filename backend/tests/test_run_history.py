# File: backend/tests/test_run_history.py
"""Scoped run history + chat-native continuation — "pick up where we left off".

Resumable pending flows, continuable completed artifacts, and honestly-surfaced
failures, listed permission-aware with clean minimal metadata. Resume vs continue
vs retry stay distinct; continuation re-checks scope so an inaccessible run is
simply not found (its existence never leaks)."""

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.accounts import account_service
from app.activity import RUN_FAILED, activity_service
from app.artifacts.service import PendingArtifact, artifact_store
from app.auth import make_account_token, owner_token_for
from app.core.config import settings
from app.db.database import ensure_runtime_columns
from app.main import app
from app.run_history import run_history_service
from app.workspaces import workspace_service

ensure_runtime_columns()
client = TestClient(app)


def _account():
    return account_service.register(f"u_{uuid4().hex[:10]}@example.com", "password123", "Alice")


def _auth(account, workspace_id=None):
    h = {"Authorization": f"Bearer {make_account_token(account['id'])}"}
    if workspace_id:
        h["X-Workspace-Id"] = workspace_id
    return h


def _seed_artifact(owner_key: str, name: str = "quarterly_review.pptx") -> None:
    token = owner_token_for(owner_key)
    owner_dir = Path(settings.artifacts_dir).resolve() / token
    owner_dir.mkdir(parents=True, exist_ok=True)
    (owner_dir / name).write_bytes(b"PK fake artifact bytes " * 60)


def _seed_pending_artifact(owner_key: str, goal: str = "A deck about Q3 sales") -> None:
    artifact_store.set(owner_key, PendingArtifact(goal=goal, kind="pptx", spec={}, delivery={}))


# ── Service-level: composition, statuses, resumable flag, clean metadata ──────


def test_recent_lists_pending_completed_and_failed_honestly():
    owner = f"account:{uuid4().hex}"
    _seed_pending_artifact(owner)
    _seed_artifact(owner, "team_strategy.pptx")
    activity_service.record(owner, RUN_FAILED, "Workflow run didn't finish", status="failed")

    runs = run_history_service.recent(owner)
    by_status = {r["status"] for r in runs}
    assert {"requires_approval", "completed", "failed"} <= by_status
    # The resumable (pending) run is surfaced first — most actionable.
    assert runs[0]["kind"] == "resume" and runs[0]["resumable"] is True


def test_resumable_flag_is_correct():
    owner = f"account:{uuid4().hex}"
    _seed_pending_artifact(owner)
    _seed_artifact(owner, "finished.pptx")
    runs = run_history_service.recent(owner)
    resume = next(r for r in runs if r["kind"] == "resume")
    cont = next(r for r in runs if r["kind"] == "continue")
    assert resume["resumable"] is True and resume["action"] == "Resume"
    assert cont["resumable"] is False and cont["action"] == "Continue"


def test_run_summaries_are_clean_and_minimal():
    owner = f"account:{uuid4().hex}"
    _seed_pending_artifact(owner, goal="secret internal goal text")
    _seed_artifact(owner, "deck.pptx")
    for run in run_history_service.recent(owner):
        # Only UI-ready fields — never internals.
        for banned in ("owner", "owner_key", "path", "token", "payload", "executable",
                       "spec", "delivery", "trace_events"):
            assert banned not in run
        assert set(run) == {"id", "kind", "title", "status", "summary",
                            "resumable", "action", "download_url", "created_at"}


def test_runs_are_scope_isolated():
    a, b = f"account:{uuid4().hex}", f"workspace:{uuid4().hex}"
    _seed_artifact(a, "personal.pptx")
    _seed_artifact(b, "shared.pptx")
    assert any(r["title"] == "Personal" for r in run_history_service.recent(a))
    assert all(r["title"] != "Shared" for r in run_history_service.recent(a))


# ── Continuation: honest resume vs continue vs retry, scope-safe ──────────────


def test_continuation_for_pending_is_a_real_resume():
    owner = f"account:{uuid4().hex}"
    _seed_pending_artifact(owner)
    prepared = run_history_service.continuation_for(owner, "pending:artifact")
    assert prepared["mode"] == "resume"
    # The exact phrase the supervisor's approval parser accepts.
    from app.clarification import parse_plan_decision
    assert parse_plan_decision(prepared["prompt"]) == "approve"


def test_continuation_for_completed_seeds_fresh_build_without_fabricating_state():
    owner = f"account:{uuid4().hex}"
    _seed_artifact(owner, "growth_plan.pptx")
    prepared = run_history_service.continuation_for(owner, "artifact:growth_plan.pptx")
    assert prepared["mode"] == "continue"
    # Honest: a fresh on-topic build, not a claim that internal state persists.
    assert "Growth plan" in prepared["prompt"] and "presentation" in prepared["prompt"]
    assert "resume" not in prepared["prompt"].lower()


def test_continuation_for_inaccessible_run_is_none_no_leak():
    owner = f"account:{uuid4().hex}"
    other = f"workspace:{uuid4().hex}"
    _seed_artifact(other, "confidential.pptx")
    assert run_history_service.continuation_for(owner, "artifact:confidential.pptx") is None
    assert run_history_service.get(owner, "artifact:confidential.pptx") is None


def test_duplicate_continuation_stays_safe_and_stable():
    owner = f"account:{uuid4().hex}"
    _seed_pending_artifact(owner)
    first = run_history_service.continuation_for(owner, "pending:artifact")
    second = run_history_service.continuation_for(owner, "pending:artifact")
    # Idempotent prompt; the real one-shot claim lives in guided_flow consume.
    assert first == second and first["mode"] == "resume"


# ── HTTP: permission + scope aware ───────────────────────────────────────────


def test_recent_runs_lists_personal_scope():
    owner = _account()
    _seed_artifact(f"account:{owner['id']}", "my_report.pptx")
    body = client.get("/runs/recent", headers=_auth(owner)).json()
    assert body["scope"]["is_workspace"] is False
    assert any(r["title"] == "My report" for r in body["runs"])


def test_recent_runs_lists_workspace_scope_for_members():
    owner, viewer = _account(), _account()
    ws = client.post("/workspaces", json={"name": "Team"}, headers=_auth(owner)).json()["workspace"]
    workspace_service.add_member(ws["id"], viewer["id"], "viewer")
    _seed_artifact(ws["owner_key"], "roadmap.pptx")
    body = client.get("/runs/recent", headers=_auth(viewer, ws["id"])).json()
    assert body["scope"]["is_workspace"] is True
    assert any(r["title"] == "Roadmap" for r in body["runs"])


def test_non_member_cannot_access_workspace_run_history():
    owner, outsider = _account(), _account()
    ws = client.post("/workspaces", json={"name": "Secret"}, headers=_auth(owner)).json()["workspace"]
    _seed_artifact(ws["owner_key"], "secret_deck.pptx")
    body = client.get("/runs/recent", headers=_auth(outsider, ws["id"])).json()
    # Outsider falls back to personal scope — never the team's runs.
    assert body["scope"]["is_workspace"] is False
    assert all(r["title"] != "Secret deck" for r in body["runs"])


def test_continue_inaccessible_run_is_404_not_a_leak():
    owner, outsider = _account(), _account()
    ws = client.post("/workspaces", json={"name": "Team"}, headers=_auth(owner)).json()["workspace"]
    _seed_artifact(ws["owner_key"], "private.pptx")
    # Outsider (personal scope) tries to continue a workspace run -> not found.
    res = client.post("/runs/artifact:private.pptx/continue", headers=_auth(outsider, ws["id"]))
    assert res.status_code == 404


def test_continue_completed_run_returns_chat_prompt():
    owner = _account()
    _seed_artifact(f"account:{owner['id']}", "launch_plan.pptx")
    res = client.post("/runs/artifact:launch_plan.pptx/continue", headers=_auth(owner)).json()
    assert res["mode"] == "continue"
    assert "Launch plan" in res["prompt"]
