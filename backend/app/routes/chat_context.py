# File: backend/app/routes/chat_context.py
"""
Chat context handoff — explicit, scope-safe "use this in chat".

  POST   /chat/context   -> { scope, context }   attach a doc/artifact/run
  GET    /chat/context   -> { scope, context }    what's attached (or null)
  DELETE /chat/context   -> { ok }                detach

Every route resolves the active scope exactly like a turn (account-first; a
workspace header is honoured only for members). Attaching needs `view` — it only
parks a reference on the caller's own chat session, never mutates shared state —
so a workspace viewer can reuse what they can already see, while a non-member
silently falls back to their personal scope and an inaccessible / cross-scope
reference resolves to 404 (its existence never leaks). The returned context is a
clean reference + honest action + a composer prefill — never file contents, owner
keys, or internals.
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
    return {"scope": _scope_dict(scope), "context": context}


@router.get("/context")
def get_context(
    request: Request,
    session_id: str | None = None,
) -> dict:
    scope = _scope_or_403(request, session_id)
    owner = scope.owner_key or "default"
    return {"scope": _scope_dict(scope), "context": chat_context_service.current(owner, session_id)}


@router.delete("/context")
def clear_context(
    request: Request,
    session_id: str | None = None,
) -> dict:
    scope = _scope_or_403(request, session_id)
    owner = scope.owner_key or "default"
    chat_context_service.clear(owner, session_id)
    return {"ok": True}
