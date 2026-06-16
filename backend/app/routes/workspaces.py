# File: backend/app/routes/workspaces.py
"""
Workspace endpoints — foundation only.

  GET  /workspaces       -> the workspaces the current account belongs to
  POST /workspaces       -> create a workspace (the creator is its owner)

Deliberately minimal: no invitations, no admin console, no role management UI.
This exists so the scope model has real, durable workspaces to point at; sharing
and roles layer on later without changing these shapes. All routes require an
authenticated account.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.auth import resolve_account_principal
from app.workspaces import workspace_service

router = APIRouter(prefix="/workspaces", tags=["AIRA-X Workspaces"])


class CreateWorkspaceRequest(BaseModel):
    name: str


def _require_account(request: Request) -> str:
    principal = resolve_account_principal(request)
    if principal is None or not principal.account_id:
        raise HTTPException(status_code=401, detail="Sign in to use workspaces.")
    return principal.account_id


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
