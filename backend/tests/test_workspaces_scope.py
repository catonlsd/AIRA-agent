# File: backend/tests/test_workspaces_scope.py
"""Workspace foundations + explicit scope model: account/session/workspace scopes
resolve correctly, durable owner keys stay backward-compatible, workspace access
is membership-gated (no cross-team leakage), and account-owned behaviour is
unchanged. No collaboration UI — foundations only."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.accounts import account_service
from app.auth import (
    ResourceScope,
    SCOPE_ACCOUNT,
    SCOPE_SESSION,
    SCOPE_WORKSPACE,
    accessible_owner_tokens,
    make_account_token,
    resolve_owner,
    resolve_scope,
)
from app.main import app
from app.workspaces import workspace_service

client = TestClient(app)


def _account():
    return account_service.register(f"u_{uuid4().hex[:10]}@example.com", "password123", "U")


class _Req:
    def __init__(self, token=None, workspace_id=None, ):
        self.headers = {}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        if workspace_id:
            self.headers["X-Workspace-Id"] = workspace_id


# ── Scope model ──────────────────────────────────────────────────────────────


def test_owner_keys_are_stable_distinct_and_backward_compatible():
    # Session keeps its RAW id (backward-compatible durable owner).
    assert ResourceScope(kind=SCOPE_SESSION, subject="sess-1").owner_key == "sess-1"
    assert ResourceScope(kind=SCOPE_ACCOUNT, subject="a1").owner_key == "account:a1"
    assert ResourceScope(kind=SCOPE_WORKSPACE, subject="w1").owner_key == "workspace:w1"
    # Distinct across scopes.
    keys = {
        ResourceScope(kind=SCOPE_SESSION, subject="x").owner_key,
        ResourceScope(kind=SCOPE_ACCOUNT, subject="x").owner_key,
        ResourceScope(kind=SCOPE_WORKSPACE, subject="x").owner_key,
    }
    assert len(keys) == 3


def test_scope_personal_vs_workspace_flags():
    assert ResourceScope(kind=SCOPE_ACCOUNT, subject="a").is_personal
    assert ResourceScope(kind=SCOPE_SESSION, subject="s").is_personal
    ws = ResourceScope(kind=SCOPE_WORKSPACE, subject="w")
    assert ws.is_workspace and not ws.is_personal


def test_resolve_scope_account_session_anonymous():
    account = _account()
    req = _Req(token=make_account_token(account["id"]))
    s = resolve_scope(req, "sess")
    assert s.kind == SCOPE_ACCOUNT and s.owner_key == f"account:{account['id']}"
    assert s.label == "Personal"

    assert resolve_scope(_Req(), "sess").kind == SCOPE_SESSION
    assert resolve_scope(_Req(), "sess").owner_key == "sess"
    assert resolve_scope(None, None).kind == "anonymous"
    assert resolve_owner(None, None) is None  # unchanged anonymous behaviour


# ── Workspace data model ─────────────────────────────────────────────────────


def test_workspace_create_and_membership():
    account = _account()
    ws = workspace_service.create(account["id"], "Team Alpha")
    assert ws["name"] == "Team Alpha"
    assert ws["owner_key"] == f"workspace:{ws['id']}"
    assert ws["owner_account_id"] == account["id"]
    # Creator is a member; reads back; lists for the account.
    assert workspace_service.is_member(ws["id"], account["id"]) is True
    assert workspace_service.get_if_member(ws["id"], account["id"]) is not None
    assert any(w["id"] == ws["id"] for w in workspace_service.list_for_account(account["id"]))


def test_non_member_cannot_resolve_or_see_workspace():
    owner = _account()
    other = _account()
    ws = workspace_service.create(owner["id"], "Private Team")
    # Membership gate: a non-member gets nothing.
    assert workspace_service.is_member(ws["id"], other["id"]) is False
    assert workspace_service.get_if_member(ws["id"], other["id"]) is None
    assert ws["id"] not in [w["id"] for w in workspace_service.list_for_account(other["id"])]


# ── Membership-gated scope resolution (no cross-team leakage) ────────────────


def test_member_gets_workspace_scope():
    account = _account()
    ws = workspace_service.create(account["id"], "Alpha")
    req = _Req(token=make_account_token(account["id"]), workspace_id=ws["id"])
    s = resolve_scope(req, "sess")
    assert s.kind == SCOPE_WORKSPACE and s.owner_key == f"workspace:{ws['id']}"
    assert s.account_id == account["id"] and s.workspace_id == ws["id"]
    assert resolve_owner(req, "sess") == f"workspace:{ws['id']}"


def test_non_member_workspace_header_falls_back_to_personal():
    owner = _account()
    intruder = _account()
    ws = workspace_service.create(owner["id"], "Secret")
    # Intruder presents the workspace header but isn't a member -> personal scope,
    # never the workspace owner key.
    req = _Req(token=make_account_token(intruder["id"]), workspace_id=ws["id"])
    s = resolve_scope(req, "sess")
    assert s.kind == SCOPE_ACCOUNT
    assert s.owner_key == f"account:{intruder['id']}"


def test_accessible_owner_tokens_cover_personal_plus_workspaces():
    from app.auth import owner_token_for

    account = _account()
    ws = workspace_service.create(account["id"], "Alpha")
    tokens = accessible_owner_tokens(account["id"])
    assert owner_token_for(f"account:{account['id']}") in tokens
    assert owner_token_for(f"workspace:{ws['id']}") in tokens
    # A different account's tokens never include this workspace.
    other = _account()
    assert owner_token_for(f"workspace:{ws['id']}") not in accessible_owner_tokens(other["id"])


# ── HTTP endpoints ───────────────────────────────────────────────────────────


def test_workspace_endpoints_require_auth_and_create_lists():
    account = _account()
    token = make_account_token(account["id"])
    auth = {"Authorization": f"Bearer {token}"}

    assert client.get("/workspaces").status_code == 401  # no auth
    assert client.post("/workspaces", json={"name": "Beta"}).status_code == 401

    created = client.post("/workspaces", json={"name": "Beta"}, headers=auth)
    assert created.status_code == 200
    ws = created.json()["workspace"]
    assert ws["name"] == "Beta"

    listed = client.get("/workspaces", headers=auth).json()["workspaces"]
    assert any(w["id"] == ws["id"] for w in listed)


def test_workspace_scoped_preferences_are_isolated_from_personal():
    account = _account()
    token = make_account_token(account["id"])
    ws = workspace_service.create(account["id"], "Alpha")

    # Save a preference in PERSONAL scope.
    client.put("/preferences", json={"key": "answer_length", "value": "concise"},
               headers={"Authorization": f"Bearer {token}"})
    # The same account acting in the WORKSPACE sees a separate (empty) scope.
    ws_view = client.get(
        "/preferences",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": ws["id"]},
    ).json()
    val = next(e["value"] for e in ws_view["preferences"] if e["key"] == "answer_length")
    assert val is None  # workspace scope is distinct from personal — explicit, not blurred
