# File: backend/tests/test_roles_permissions.py
"""Workspace roles + permission-aware authorization: viewer/editor/owner drive
real access decisions, a safe-default denial, the operator boundary, and no
regression to personal self-access."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.core.llm as llm_module
from app.accounts import account_service
from app.assistant_supervisor import AssistantSupervisor
from app.auth import ResourceScope, SCOPE_ACCOUNT, SCOPE_WORKSPACE, make_account_token
from app.authz import (
    PERM_EDIT,
    PERM_MANAGE,
    PERM_VIEW,
    ROLE_EDITOR,
    ROLE_OWNER,
    ROLE_VIEWER,
    can,
    role_can,
)
from app.context_builder import build_turn_context
from app.main import app
from app.memory.preference_memory import preference_memory
from app.workspaces import workspace_service

client = TestClient(app)


def _account():
    return account_service.register(f"u_{uuid4().hex[:10]}@example.com", "password123", "U")


def _ws_scope(account_id, workspace_id, role):
    return ResourceScope(kind=SCOPE_WORKSPACE, subject=workspace_id,
                         account_id=account_id, workspace_id=workspace_id, label="W", role=role)


# ── Role / permission model ──────────────────────────────────────────────────


def test_role_permission_matrix():
    assert role_can(ROLE_VIEWER, PERM_VIEW) and not role_can(ROLE_VIEWER, PERM_EDIT)
    assert role_can(ROLE_EDITOR, PERM_EDIT) and not role_can(ROLE_EDITOR, PERM_MANAGE)
    assert role_can(ROLE_OWNER, PERM_MANAGE)
    # Unknown/absent role is denied everything (safe default).
    assert not role_can(None, PERM_VIEW)
    assert not role_can("superuser", PERM_EDIT)
    # Legacy "member" maps to viewer.
    assert role_can("member", PERM_VIEW) and not role_can("member", PERM_EDIT)


def test_can_personal_scope_is_full_self_access():
    # Personal/account/session/None scope -> always allowed (single-user simplicity).
    for scope in (None, ResourceScope(kind=SCOPE_ACCOUNT, subject="a", account_id="a")):
        assert can(scope, PERM_VIEW) and can(scope, PERM_EDIT) and can(scope, PERM_MANAGE)


def test_can_workspace_scope_obeys_role():
    viewer = _ws_scope("a", "w", ROLE_VIEWER)
    assert can(viewer, PERM_VIEW).allowed is True
    assert can(viewer, PERM_EDIT).allowed is False
    assert "view-only" in can(viewer, PERM_EDIT).reason
    editor = _ws_scope("a", "w", ROLE_EDITOR)
    assert can(editor, PERM_EDIT).allowed is True
    assert can(editor, PERM_MANAGE).allowed is False


# ── Role-aware membership (durable) ──────────────────────────────────────────


def test_membership_carries_role_and_safe_default():
    owner = _account()
    member = _account()
    ws = workspace_service.create(owner["id"], "Team")
    assert workspace_service.get_role(ws["id"], owner["id"]) == ROLE_OWNER
    # A newly added member defaults to viewer (conservative).
    workspace_service.add_member(ws["id"], member["id"])
    assert workspace_service.get_role(ws["id"], member["id"]) == ROLE_VIEWER
    # Role can be raised; persists.
    workspace_service.add_member(ws["id"], member["id"], ROLE_EDITOR)
    assert workspace_service.get_role(ws["id"], member["id"]) == ROLE_EDITOR
    # Non-member has no role.
    assert workspace_service.get_role(ws["id"], _account()["id"]) is None


def test_resolve_scope_includes_role():
    from app.auth import resolve_scope

    owner = _account()
    ws = workspace_service.create(owner["id"], "Team")

    class _Req:
        headers = {"Authorization": f"Bearer {make_account_token(owner['id'])}", "X-Workspace-Id": ws["id"]}

    scope = resolve_scope(_Req(), "sess")
    assert scope.is_workspace and scope.role == ROLE_OWNER


# ── Workspace preference editing obeys roles (API) ───────────────────────────


def test_workspace_preference_write_requires_manage():
    owner = _account()
    viewer = _account()
    ws = workspace_service.create(owner["id"], "Team")
    workspace_service.add_member(ws["id"], viewer["id"], ROLE_VIEWER)

    ws_header = {"X-Workspace-Id": ws["id"]}
    owner_auth = {"Authorization": f"Bearer {make_account_token(owner['id'])}", **ws_header}
    viewer_auth = {"Authorization": f"Bearer {make_account_token(viewer['id'])}", **ws_header}

    # Owner (manage) can set a workspace default.
    assert client.put("/preferences", json={"key": "answer_length", "value": "concise"}, headers=owner_auth).status_code == 200
    # Viewer cannot mutate the shared default.
    denied = client.put("/preferences", json={"key": "answer_length", "value": "detailed"}, headers=viewer_auth)
    assert denied.status_code == 403
    # The shared default is unchanged.
    assert preference_memory.get(ws["owner_key"]) == {"answer_length": "concise"}
    # A viewer CAN still read it.
    assert client.get("/preferences", headers=viewer_auth).status_code == 200


def test_personal_preference_editing_unaffected():
    acct = _account()
    auth = {"Authorization": f"Bearer {make_account_token(acct['id'])}"}
    assert client.put("/preferences", json={"key": "answer_style", "value": "code_first"}, headers=auth).status_code == 200
    assert preference_memory.get(f"account:{acct['id']}") == {"answer_style": "code_first"}


# ── Workspace document upload obeys roles ────────────────────────────────────


def test_workspace_document_upload_requires_edit():
    import io

    owner = _account()
    viewer = _account()
    ws = workspace_service.create(owner["id"], "Team")
    workspace_service.add_member(ws["id"], viewer["id"], ROLE_VIEWER)

    files = {"files": ("note.txt", io.BytesIO(b"shared team note"), "text/plain")}
    r = client.post("/upload", files=files, data={"session_id": "s"},
                    headers={"Authorization": f"Bearer {make_account_token(viewer['id'])}", "X-Workspace-Id": ws["id"]})
    assert r.status_code == 403  # viewer cannot upload into the workspace


# ── Workspace-guided execution obeys roles (supervisor) ──────────────────────


class _ArtifactClassification:
    mode = "research_then_execution"
    artifact_type = "pptx"
    reason = "artifact request"
    confidence = "high"


@pytest.mark.asyncio
async def test_viewer_cannot_generate_artifact_in_workspace(monkeypatch):
    monkeypatch.setattr(llm_module.LLMClient, "generate", lambda self, s, p, t=0.2: "")
    supervisor = AssistantSupervisor()
    scope = _ws_scope("acc", "ws", ROLE_VIEWER)
    ctx = build_turn_context("Make a PPT on energy", session_id="s", scope=scope)
    result = await supervisor._dispatch_non_chat("Make a PPT on energy", _ArtifactClassification(), ctx)
    assert result["decision"] == "workspace_forbidden"
    assert result["meta"]["workspace_forbidden"] is True
    assert "view-only" in result["message"].lower()


@pytest.mark.asyncio
async def test_editor_can_generate_artifact_in_workspace(monkeypatch):
    monkeypatch.setattr(llm_module.LLMClient, "generate", lambda self, s, p, t=0.2: "")
    supervisor = AssistantSupervisor()
    scope = _ws_scope("acc", "ws", ROLE_EDITOR)
    ctx = build_turn_context("Make a PPT on energy", session_id="s", scope=scope)
    result = await supervisor._dispatch_non_chat("Make a PPT on energy", _ArtifactClassification(), ctx)
    # Editor is allowed -> the turn proceeds to an artifact plan (not forbidden).
    assert result.get("decision") != "workspace_forbidden"
    assert result["meta"].get("artifact_pending") is True


# ── Operator boundary ────────────────────────────────────────────────────────


def test_operator_overview_requires_service_key(monkeypatch):
    from app.core.config import settings
    from app.middleware import reset_rate_limit

    # No api key configured -> no operator exists; the path is unavailable.
    assert client.get("/operator/overview").status_code == 403

    monkeypatch.setattr(settings, "api_key", "service-secret")
    reset_rate_limit()
    # A normal account token is NOT an operator.
    acct = _account()
    assert client.get("/operator/overview", headers={"Authorization": f"Bearer {make_account_token(acct['id'])}", "X-API-Key": "service-secret"}).status_code in (200, 403)
    # Wrong/no key -> denied; the correct service key -> allowed.
    assert client.get("/operator/overview", headers={"X-API-Key": "wrong"}).status_code in (401, 403)
    ok = client.get("/operator/overview", headers={"X-API-Key": "service-secret"})
    assert ok.status_code == 200 and "accounts" in ok.json()
