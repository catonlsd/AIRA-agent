# File: backend/app/routes/chat_context.py
"""
Chat context handoff — explicit, scope-safe "use these in chat" (multi-item).

  POST   /chat/context         -> { scope, context, items }  attach one item
  POST   /chat/context/items   -> { scope, items, attached, skipped }  attach many
  GET    /chat/context         -> { scope, items, context, prompt }    what's attached
  DELETE /chat/context/item    -> { ok, items }              remove one item
  DELETE /chat/context         -> { ok }                     clear all

Every route resolves the active scope exactly like a turn (account-first; a
workspace header is honoured only for members). Attaching needs `view` — it only
parks references on the caller's own chat session, never mutates shared state — so
a workspace viewer can reuse what they can already see, while a non-member
silently falls back to their personal scope and an inaccessible / cross-scope
reference resolves to 404 (its existence never leaks). Items are deduped and
ordered; each is a clean reference + honest action + role — never file contents,
owner keys, or internals. `context` mirrors the first item for single-item callers.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import resolve_scope
from app.authz import PERM_VIEW, can
from app.chat_context import chat_context_service
from app.db.database import get_db

router = APIRouter(prefix="/chat", tags=["AIRA-X Chat Context"])


class ContextRequest(BaseModel):
    ref_type: str = Field(..., max_length=24)
    ref_id: str = Field(..., max_length=255)
    session_id: str | None = None


class ContextRef(BaseModel):
    ref_type: str = Field(..., max_length=24)
    ref_id: str = Field(..., max_length=255)


class ContextItemsRequest(BaseModel):
    items: list[ContextRef] = Field(default_factory=list)
    session_id: str | None = None


def _scope_dict(scope) -> dict:
    return {"kind": scope.kind, "label": scope.label or scope.kind, "is_workspace": scope.is_workspace}


def _scope_or_403(request: Request, session_id: str | None):
    scope = resolve_scope(request, session_id)
    if not can(scope, PERM_VIEW):
        raise HTTPException(status_code=403, detail="You don't have access in this scope.")
    return scope


@router.post("/context")
def attach_context(
    body: ContextRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    scope = _scope_or_403(request, body.session_id)
    owner = scope.owner_key or "default"
    context = chat_context_service.attach(owner, body.session_id, body.ref_type, body.ref_id, db=db)
    if context is None:
        raise HTTPException(status_code=404, detail="That can't be used in this scope.")
    return {
        "scope": _scope_dict(scope),
        "context": context,
        "items": chat_context_service.items(owner, body.session_id),
    }


@router.post("/context/items")
def attach_context_items(
    body: ContextItemsRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    scope = _scope_or_403(request, body.session_id)
    owner = scope.owner_key or "default"
    refs = [{"ref_type": r.ref_type, "ref_id": r.ref_id} for r in body.items]
    result = chat_context_service.attach_many(owner, body.session_id, refs, db=db)
    return {"scope": _scope_dict(scope), **result}


@router.get("/context")
def get_context(
    request: Request,
    session_id: str | None = None,
) -> dict:
    scope = _scope_or_403(request, session_id)
    owner = scope.owner_key or "default"
    items = chat_context_service.items(owner, session_id)
    return {
        "scope": _scope_dict(scope),
        "items": items,
        "context": items[0] if items else None,  # single-item callers
        "prompt": chat_context_service.primary_prompt(items),
    }


@router.delete("/context/item")
def remove_context_item(
    request: Request,
    ref_type: str,
    ref_id: str,
    session_id: str | None = None,
) -> dict:
    scope = _scope_or_403(request, session_id)
    owner = scope.owner_key or "default"
    ok = chat_context_service.remove(owner, session_id, ref_type, ref_id)
    return {"ok": ok, "items": chat_context_service.items(owner, session_id)}


@router.delete("/context")
def clear_context(
    request: Request,
    session_id: str | None = None,
) -> dict:
    scope = _scope_or_403(request, session_id)
    owner = scope.owner_key or "default"
    chat_context_service.clear(owner, session_id)
    return {"ok": True}
