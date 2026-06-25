# File: backend/tests/test_workspace_membership.py
"""Minimal collaboration loop: invite-by-email membership management (owner-gated,
with owner protections), and scope switching that truly drives backend behavior —
a member acting in a workspace gets workspace scope; a non-member never does."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.accounts import account_service
from app.auth import make_account_token, resolve_scope
from app.main import app
from app.memory.preference_memory import preference_memory
from app.workspaces import workspace_service

client = TestClient(app)


def _account():
    return account_service.register(f"u_{uuid4().hex[:10]}@example.com", "password123", "U")


def _auth(account, workspace_id=None):
    h = {"Authorization": f"Bearer {make_account_token(account['id'])}"}
    if workspace_id:
        h["X-Workspace-Id"] = workspace_id
    return h


def _make_workspace(owner):
    return client.post("/workspaces", json={"name": "Team"}, headers=_auth(owner)).json()["workspace"]


# ── Membership management (owner-gated, invite by email) ─────────────────────


def test_owner_lists_adds_and_removes_members():
    owner, guest = _account(), _account()
    ws = _make_workspace(owner)

    # Only the owner at first.
    members = client.get(f"/workspaces/{ws['id']}/members", headers=_auth(owner)).json()["members"]
    assert [m["role"] for m in members] == ["owner"]
    # No internal owner keys leak.
    assert all("owner_key" not in m for m in members)

    # Add the guest by email as an editor.
    r = client.post(f"/workspaces/{ws['id']}/members", json={"email": guest["email"], "role": "editor"}, headers=_auth(owner))
    assert r.status_code == 200
    roles = {m["email"]: m["role"] for m in r.json()["members"]}
    assert roles[guest["email"]] == "editor"

    # The guest now sees the workspace and its members.
    assert any(w["id"] == ws["id"] for w in client.get("/workspaces", headers=_auth(guest)).json()["workspaces"])
    assert client.get(f"/workspaces/{ws['id']}/members", headers=_auth(guest)).status_code == 200

    # Owner removes the guest.
    after = client.delete(f"/workspaces/{ws['id']}/members/{guest['id']}", headers=_auth(owner)).json()["members"]
    assert guest["email"] not in {m["email"] for m in after}


def test_member_management_is_owner_gated():
    owner, editor, outsider = _account(), _account(), _account()
    ws = _make_workspace(owner)
    workspace_service.add_member(ws["id"], editor["id"], "editor")

    # An editor cannot add members.
    assert client.post(f"/workspaces/{ws['id']}/members", json={"email": outsider["email"]}, headers=_auth(editor)).status_code == 403
    # An editor cannot change roles.
    assert client.patch(f"/workspaces/{ws['id']}/members/{owner['id']}", json={"role": "viewer"}, headers=_auth(editor)).status_code == 403
    # A non-member can't even see the workspace exists.
    assert client.get(f"/workspaces/{ws['id']}/members", headers=_auth(outsider)).status_code == 404


def test_invalid_target_account_is_handled_cleanly():
    owner = _account()
    ws = _make_workspace(owner)
    r = client.post(f"/workspaces/{ws['id']}/members", json={"email": "nobody@nowhere.test"}, headers=_auth(owner))
    assert r.status_code == 404 and "account" in r.json()["detail"].lower()


def test_role_updates_obey_permissions_and_default_is_safe():
    owner, member = _account(), _account()
    ws = _make_workspace(owner)
    # Default role when added without one is viewer (conservative).
    client.post(f"/workspaces/{ws['id']}/members", json={"email": member["email"]}, headers=_auth(owner))
    assert workspace_service.get_role(ws["id"], member["id"]) == "viewer"
    # Owner promotes to editor.
    client.patch(f"/workspaces/{ws['id']}/members/{member['id']}", json={"role": "editor"}, headers=_auth(owner))
    assert workspace_service.get_role(ws["id"], member["id"]) == "editor"


def test_owner_protections_prevent_self_lockout():
    owner = _account()
    ws = _make_workspace(owner)
    # The sole owner cannot remove themselves (no lockout).
    assert client.delete(f"/workspaces/{ws['id']}/members/{owner['id']}", headers=_auth(owner)).status_code == 400
    # Nor demote themselves while the only owner.
    assert client.patch(f"/workspaces/{ws['id']}/members/{owner['id']}", json={"role": "editor"}, headers=_auth(owner)).status_code == 400


def test_member_can_leave_workspace():
    owner, guest = _account(), _account()
    ws = _make_workspace(owner)
    workspace_service.add_member(ws["id"], guest["id"], "editor")
    # A non-owner may remove themselves (leave) even without manage rights.
    assert client.delete(f"/workspaces/{ws['id']}/members/{guest['id']}", headers=_auth(guest)).status_code == 200
    assert workspace_service.is_member(ws["id"], guest["id"]) is False


# ── Scope switching truly drives backend behavior ────────────────────────────


def test_member_switching_into_workspace_resolves_workspace_scope():
    owner = _account()
    ws = _make_workspace(owner)

    class _Req:
        headers = _auth(owner, ws["id"])

    scope = resolve_scope(_Req(), "sess")
    assert scope.is_workspace and scope.owner_key == ws["owner_key"] and scope.role == "owner"


def test_non_member_workspace_header_falls_back_to_personal():
    owner, outsider = _account(), _account()
    ws = _make_workspace(owner)

    class _Req:
        headers = _auth(outsider, ws["id"])  # outsider presents the workspace header

    scope = resolve_scope(_Req(), "sess")
    assert scope.is_workspace is False  # never activates a workspace they don't belong to
    assert scope.owner_key == f"account:{outsider['id']}"


def test_workspace_scope_drives_preferences_via_header():
    owner = _account()
    ws = _make_workspace(owner)
    # Editing preferences WITH the workspace header writes the workspace default.
    client.put("/preferences", json={"key": "answer_length", "value": "concise"}, headers=_auth(owner, ws["id"]))
    assert preference_memory.get(ws["owner_key"]) == {"answer_length": "concise"}
    # WITHOUT the header (Personal) it's a separate, empty scope.
    personal = client.get("/preferences", headers=_auth(owner)).json()
    assert next(e["value"] for e in personal["preferences"] if e["key"] == "answer_length") is None
