# File: backend/app/routes/workspaces.py
"""
Workspace endpoints — minimal collaboration loop.

  GET    /workspaces                         -> workspaces I belong to (with my role)
  POST   /workspaces                         -> create one (creator is owner)
  GET    /workspaces/{id}/members            -> members (any member can view)
  POST   /workspaces/{id}/members            -> add by email + role (manage only)
  PATCH  /workspaces/{id}/members/{account}  -> change a member's role (manage only)
  DELETE /workspaces/{id}/members/{account}  -> remove a member (manage; or leave self)

Role-aware: viewing members needs membership; managing members needs `manage`
(owner). Owner protections (no last-owner lockout) live in the service. No
invitation email system yet — you add an existing account by email, with an
honest error when no such account exists. All routes require an authenticated
account; internal owner keys never leak into responses.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.accounts import account_service
from app.auth import resolve_account_principal
from app.authz import PERM_MANAGE, ROLE_VIEWER, normalize_role, role_can
from app.workspaces import WorkspaceError, workspace_service

router = APIRouter(prefix="/workspaces", tags=["AIRA-X Workspaces"])


class CreateWorkspaceRequest(BaseModel):
    name: str


class AddMemberRequest(BaseModel):
    email: str
    role: str | None = None


class UpdateMemberRequest(BaseModel):
    role: str


def _require_account(request: Request) -> str:
    principal = resolve_account_principal(request)
    if principal is None or not principal.account_id:
        raise HTTPException(status_code=401, detail="Sign in to use workspaces.")
    return principal.account_id


def _require_member_role(request: Request, workspace_id: str) -> tuple[str, str]:
    """Return (account_id, role) for a member, or raise 401/403/404."""
    account_id = _require_account(request)
    role = workspace_service.get_role(workspace_id, account_id)
    if role is None:
        # Don't reveal whether the workspace exists to non-members.
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return account_id, role


def _require_manage(request: Request, workspace_id: str) -> str:
    account_id, role = _require_member_role(request, workspace_id)
    if not role_can(role, PERM_MANAGE):
        raise HTTPException(status_code=403, detail="Only a workspace owner can manage members.")
    return account_id


# ── workspaces ────────────────────────────────────────────────────────────────


@router.get("")
def list_workspaces(request: Request) -> dict:
    account_id = _require_account(request)
    return {"workspaces": workspace_service.list_for_account(account_id)}


@router.post("")
def create_workspace(body: CreateWorkspaceRequest, request: Request) -> dict:
    account_id = _require_account(request)
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Workspace name is required.")
    return {"workspace": workspace_service.create(account_id, name)}


# ── members ──────────────────────────────────────────────────────────────────


@router.get("/{workspace_id}/members")
def list_members(workspace_id: str, request: Request) -> dict:
    _require_member_role(request, workspace_id)  # any member can view
    return {"members": workspace_service.list_members(workspace_id)}


@router.post("/{workspace_id}/members")
def add_member(workspace_id: str, body: AddMemberRequest, request: Request) -> dict:
    actor_id = _require_manage(request, workspace_id)
    account = account_service.get_by_email(body.email)
    if account is None:
        raise HTTPException(status_code=404, detail="No AIRA-X account uses that email.")
    role = normalize_role(body.role) or ROLE_VIEWER
    workspace_service.add_member(workspace_id, account["id"], role)
    try:
        from app.activity import WORKSPACE_MEMBER_ADDED, activity_service
        from app.workspaces import workspace_owner_key

        activity_service.record(
            workspace_owner_key(workspace_id), WORKSPACE_MEMBER_ADDED,
            f"Added {account['display_name']} as {role}", actor_id=actor_id,
            resource_type="member", resource_id=account["id"],
        )
    except Exception:
        pass
    return {"members": workspace_service.list_members(workspace_id)}


@router.patch("/{workspace_id}/members/{account_id}")
def update_member(workspace_id: str, account_id: str, body: UpdateMemberRequest, request: Request) -> dict:
    _require_manage(request, workspace_id)
    try:
        workspace_service.update_member_role(workspace_id, account_id, body.role)
    except WorkspaceError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return {"members": workspace_service.list_members(workspace_id)}


@router.delete("/{workspace_id}/members/{account_id}")
def remove_member(workspace_id: str, account_id: str, request: Request) -> dict:
    # Managing others needs manage; a member may always remove themselves (leave).
    requester_id, role = _require_member_role(request, workspace_id)
    if account_id != requester_id and not role_can(role, PERM_MANAGE):
        raise HTTPException(status_code=403, detail="Only a workspace owner can remove other members.")
    try:
        workspace_service.remove_member(workspace_id, account_id)
    except WorkspaceError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return {"members": workspace_service.list_members(workspace_id)}
