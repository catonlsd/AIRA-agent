# File: backend/tests/test_chat_context.py
"""Chat context handoff — explicit, scope-safe "use this in chat".

A document/artifact/run from the active scope resolves to ONE clean context
object with an honest action (use_as_context / revise / resume / continue_from /
retry), parked on the session and consumed single-use by the next turn. Reuse
rides existing rails (artifact seeds the revision path; run carries its
continuation prompt). Inaccessible / cross-scope references never attach."""

import io
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.accounts import account_service
from app.activity import RUN_FAILED, activity_service
from app.artifacts.service import PendingArtifact, artifact_store
from app.auth import make_account_token, owner_token_for
from app.chat_context import (
    ACTION_CONTINUE_FROM,
    ACTION_RESUME,
    ACTION_RETRY,
    ACTION_REVISE,
    ACTION_USE_AS_CONTEXT,
    chat_context_service,
)
from app.core.config import settings
from app.db.database import ensure_runtime_columns
from app.main import app
from app.memory.session_memory import session_memory
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


def _seed_artifact(owner_key: str, name: str) -> None:
    token = owner_token_for(owner_key)
    owner_dir = Path(settings.artifacts_dir).resolve() / token
    owner_dir.mkdir(parents=True, exist_ok=True)
    (owner_dir / name).write_bytes(b"PK fake artifact bytes " * 60)


# ── Service-level: honest action per resource type ───────────────────────────


def test_artifact_handoff_is_revise_and_seeds_revision_rail():
    owner, session = f"account:{uuid4().hex}", "s1"
    _seed_artifact(owner, "growth_plan.pptx")
    ctx = chat_context_service.attach(owner, session, "artifact", "growth_plan.pptx")
    assert ctx["action"] == ACTION_REVISE and ctx["ref_type"] == "artifact"
    assert "Growth plan" in ctx["prompt"] and ctx["download_url"].startswith("/artifacts/")
    # Real reuse: the existing revision rail is now seeded for this session.
    last = session_memory.value(owner, session, "last_artifact")
    assert last and last["kind"] == "pptx" and last["title"] == "Growth plan"


def test_pending_run_handoff_uses_true_resume():
    owner, session = f"account:{uuid4().hex}", "s1"
    artifact_store.set(owner, PendingArtifact(goal="A deck on Q3", kind="pptx", spec={}, delivery={}))
    ctx = chat_context_service.attach(owner, session, "run", "pending:artifact")
    assert ctx["action"] == ACTION_RESUME
    from app.clarification import parse_plan_decision
    assert parse_plan_decision(ctx["prompt"]) == "approve"  # a genuine resume


def test_completed_run_handoff_uses_continue_from():
    owner, session = f"account:{uuid4().hex}", "s1"
    _seed_artifact(owner, "launch.pptx")
    ctx = chat_context_service.attach(owner, session, "run", "artifact:launch.pptx")
    assert ctx["action"] == ACTION_CONTINUE_FROM and "Launch" in ctx["title"]


def test_failed_run_handoff_uses_retry():
    owner, session = f"account:{uuid4().hex}", "s1"
    activity_service.record(owner, RUN_FAILED, "Workflow run didn't finish", status="failed")
    ctx = chat_context_service.attach(owner, session, "run", "failed:0")
    assert ctx["action"] == ACTION_RETRY


def test_context_payload_is_clean_and_minimal():
    owner, session = f"account:{uuid4().hex}", "s1"
    _seed_artifact(owner, "secret.pptx")
    ctx = chat_context_service.attach(owner, session, "artifact", "secret.pptx")
    for banned in ("owner", "owner_key", "path", "token", "spec", "delivery", "payload", "filename"):
        assert banned not in ctx


def test_inaccessible_reference_does_not_attach():
    owner, other, session = f"account:{uuid4().hex}", f"workspace:{uuid4().hex}", "s1"
    _seed_artifact(other, "confidential.pptx")
    # Owner can't see another scope's artifact -> no attach, nothing parked.
    assert chat_context_service.attach(owner, session, "artifact", "confidential.pptx") is None
    assert chat_context_service.current(owner, session) is None


def test_context_is_single_use_and_clearable():
    owner, session = f"account:{uuid4().hex}", "s1"
    _seed_artifact(owner, "deck.pptx")
    chat_context_service.attach(owner, session, "artifact", "deck.pptx")
    assert chat_context_service.current(owner, session) is not None
    # consume() applies it to one turn, then it's gone (never lingering context).
    assert chat_context_service.consume(owner, session) is not None
    assert chat_context_service.current(owner, session) is None


# ── HTTP: permission + scope aware ───────────────────────────────────────────


def test_document_handoff_over_http_is_use_as_context():
    owner = _account()
    client.post("/upload", files={"files": ("q3_strategy.txt", io.BytesIO(b"the q3 strategy body content here"), "text/plain")},
                data={"session_id": "s"}, headers=_auth(owner))
    res = client.post("/chat/context", json={"ref_type": "document", "ref_id": "q3_strategy.txt", "session_id": "s"},
                      headers=_auth(owner)).json()
    assert res["context"]["action"] == ACTION_USE_AS_CONTEXT
    assert res["context"]["title"] == "q3_strategy.txt"


def test_get_and_delete_context_roundtrip():
    owner = _account()
    _seed_artifact(f"account:{owner['id']}", "keep.pptx")
    client.post("/chat/context", json={"ref_type": "artifact", "ref_id": "keep.pptx", "session_id": "s"},
                headers=_auth(owner))
    got = client.get("/chat/context", params={"session_id": "s"}, headers=_auth(owner)).json()
    assert got["context"]["ref_type"] == "artifact"
    assert client.delete("/chat/context", params={"session_id": "s"}, headers=_auth(owner)).json()["ok"] is True
    assert client.get("/chat/context", params={"session_id": "s"}, headers=_auth(owner)).json()["context"] is None


def test_workspace_member_can_attach_non_member_cannot():
    owner, viewer, outsider = _account(), _account(), _account()
    ws = client.post("/workspaces", json={"name": "Team"}, headers=_auth(owner)).json()["workspace"]
    workspace_service.add_member(ws["id"], viewer["id"], "viewer")
    _seed_artifact(ws["owner_key"], "roadmap.pptx")

    # A viewer can reuse what they can already see.
    member = client.post("/chat/context", json={"ref_type": "artifact", "ref_id": "roadmap.pptx", "session_id": "s"},
                         headers=_auth(viewer, ws["id"]))
    assert member.status_code == 200 and member.json()["context"]["action"] == ACTION_REVISE

    # An outsider presents the header but isn't a member -> personal scope, 404.
    out = client.post("/chat/context", json={"ref_type": "artifact", "ref_id": "roadmap.pptx", "session_id": "s"},
                      headers=_auth(outsider, ws["id"]))
    assert out.status_code == 404
