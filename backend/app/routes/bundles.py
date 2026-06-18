# File: backend/app/routes/bundles.py
"""
Context bundles ("handoff packs") — save and reload a useful combination of work.

  POST   /bundles            -> { scope, bundle }   save the current attached items
  GET    /bundles            -> { scope, bundles }   bundles in the active scope
  POST   /bundles/{id}/load  -> { scope, items, loaded, skipped }  load into chat
  PATCH  /bundles/{id}       -> { ok }               rename
  DELETE /bundles/{id}       -> { ok }               delete

Every route resolves the active scope like a turn (account-first; workspace header
member-only). Reading / loading needs `view`, so a workspace viewer can reopen a
shared pack while a non-member silently falls back to personal scope (and a
workspace bundle they can't see is a plain 404). Creating / renaming / deleting a
bundle mutates shared state, so it needs `edit` — a personal user (full
self-access) always can. Loading RE-RESOLVES each reference against the current
scope, so an item that's no longer accessible is skipped, never smuggled in.
Bundles store references only — never payloads, owner keys, or internals.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import resolve_scope
from app.authz import PERM_EDIT, PERM_VIEW, can
from app.bundles import bundle_service
from app.chat_context import chat_context_service
from app.db.database import get_db

router = APIRouter(prefix="/bundles", tags=["AIRA-X Context Bundles"])


class CreateBundleRequest(BaseModel):
    name: str = Field(..., max_length=120)
    session_id: str | None = None


class RenameBundleRequest(BaseModel):
    name: str = Field(..., max_length=120)


class LoadBundleRequest(BaseModel):
    session_id: str | None = None


def _scope_dict(scope) -> dict:
    return {"kind": scope.kind, "label": scope.label or scope.kind, "is_workspace": scope.is_workspace}


def _scope_or_403(request: Request, session_id: str | None, perm: str):
    scope = resolve_scope(request, session_id)
    if not can(scope, perm):
        raise HTTPException(status_code=403, detail="You don't have access in this scope.")
    return scope


@router.post("")
def create_bundle(
    body: CreateBundleRequest,
    request: Request,
) -> dict:
    scope = _scope_or_403(request, body.session_id, PERM_EDIT)
    owner = scope.owner_key or "default"
    # Save the references currently attached to this chat session.
    items = chat_context_service.items(owner, body.session_id)
    bundle = bundle_service.create(owner, body.name, items)
    if bundle is None:
        raise HTTPException(status_code=400, detail="Attach some work first, then save it as a bundle.")
    return {"scope": _scope_dict(scope), "bundle": bundle}


@router.get("")
def list_bundles(
    request: Request,
    session_id: str | None = None,
) -> dict:
    scope = _scope_or_403(request, session_id, PERM_VIEW)
    owner = scope.owner_key or "default"
    return {"scope": _scope_dict(scope), "bundles": bundle_service.list(owner)}


@router.post("/{bundle_id}/load")
def load_bundle(
    bundle_id: str,
    body: LoadBundleRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    scope = _scope_or_403(request, body.session_id, PERM_VIEW)
    owner = scope.owner_key or "default"
    refs = bundle_service.item_refs(owner, bundle_id)
    if refs is None:
        raise HTTPException(status_code=404, detail="Bundle not found in this scope.")
    # Re-resolve each reference against the CURRENT scope — inaccessible items are
    # skipped, never smuggled in.
    result = chat_context_service.attach_many(owner, body.session_id, refs, db=db)
    return {"scope": _scope_dict(scope), **result}


@router.patch("/{bundle_id}")
def rename_bundle(
    bundle_id: str,
    body: RenameBundleRequest,
    request: Request,
    session_id: str | None = None,
) -> dict:
    scope = _scope_or_403(request, session_id, PERM_EDIT)
    owner = scope.owner_key or "default"
    return {"ok": bundle_service.rename(owner, bundle_id, body.name)}


@router.delete("/{bundle_id}")
def delete_bundle(
    bundle_id: str,
    request: Request,
    session_id: str | None = None,
) -> dict:
    scope = _scope_or_403(request, session_id, PERM_EDIT)
    owner = scope.owner_key or "default"
    return {"ok": bundle_service.delete(owner, bundle_id)}
