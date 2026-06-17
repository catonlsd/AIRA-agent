# File: backend/app/routes/search.py
"""
Scoped search + pinned work — find and keep important work in the active scope.

  GET    /search?q=&type=     -> { scope, results }   search the active scope
  GET    /pins                -> { scope, pins }       saved work, enriched
  POST   /pins                -> { scope, pin }        pin a resource (idempotent)
  DELETE /pins/{pin_id}       -> { ok }                unpin

Every route resolves the active scope exactly like a turn (account-first; a
workspace header is honoured only for members). Reading needs `view` (granted in
every real scope, so a non-member silently gets their own personal scope — never
another team's work). Mutating pins needs `edit`, so a workspace viewer can search
and see pins but only editors/owners change shared pins, while a personal user
(full self-access) always can. Results carry only clean, UI-ready fields and a
continue/download affordance — never owner keys or internals.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import owner_token_for, resolve_scope
from app.authz import PERM_EDIT, PERM_VIEW, can
from app.db.database import get_db
from app.pins import REF_ARTIFACT, REF_RUN, pin_service
from app.run_history import run_history_service
from app.search import search_service

router = APIRouter(prefix="", tags=["AIRA-X Search & Pins"])


def _scope_dict(scope) -> dict:
    return {"kind": scope.kind, "label": scope.label or scope.kind, "is_workspace": scope.is_workspace}


def _scope_or_403(request: Request, session_id: str | None, perm: str):
    scope = resolve_scope(request, session_id)
    if not can(scope, perm):
        raise HTTPException(status_code=403, detail="You don't have access in this scope.")
    return scope


@router.get("/search")
def search(
    request: Request,
    q: str = "",
    type: str | None = None,
    session_id: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    scope = _scope_or_403(request, session_id, PERM_VIEW)
    owner = scope.owner_key or "default"
    kinds = [k.strip() for k in type.split(",") if k.strip()] if type else None
    return {
        "scope": _scope_dict(scope),
        "results": search_service.search(owner, q, db=db, kinds=kinds),
    }


# ── Pins ──────────────────────────────────────────────────────────────────────


class PinRequest(BaseModel):
    ref_type: str = Field(..., max_length=24)
    ref_id: str = Field(..., max_length=255)
    title: str = Field(..., max_length=255)
    subtitle: str | None = Field(default=None, max_length=255)


def _enrich_pin(pin: dict, owner: str, db) -> dict:
    """Attach a live, access-controlled action to a stored pin without copying any
    payload: an artifact gets its download URL, a run gets its current status and
    continue/resume affordance. The pin row stays a thin durable reference."""
    out = dict(pin)
    if pin["ref_type"] == REF_ARTIFACT:
        out["download_url"] = f"/artifacts/{owner_token_for(owner)}/{pin['ref_id']}"
    elif pin["ref_type"] == REF_RUN:
        run = run_history_service.get(owner, pin["ref_id"], db=db)
        if run is not None:
            out["status"] = run["status"]
            out["run_kind"] = run["kind"]
            out["action"] = run["action"]
            out["resumable"] = run["resumable"]
            out["download_url"] = run["download_url"]
        else:
            out["status"] = "archived"  # no longer in recent history — honest
    return out


@router.get("/pins")
def list_pins(
    request: Request,
    session_id: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    scope = _scope_or_403(request, session_id, PERM_VIEW)
    owner = scope.owner_key or "default"
    pins = [_enrich_pin(p, owner, db) for p in pin_service.list(owner)]
    return {"scope": _scope_dict(scope), "pins": pins}


@router.post("/pins")
def create_pin(
    body: PinRequest,
    request: Request,
    session_id: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    scope = _scope_or_403(request, session_id, PERM_EDIT)
    owner = scope.owner_key or "default"
    pin = pin_service.pin(owner, body.ref_type, body.ref_id, body.title, subtitle=body.subtitle)
    if pin is None:
        raise HTTPException(status_code=400, detail="That can't be pinned.")
    return {"scope": _scope_dict(scope), "pin": _enrich_pin(pin, owner, db)}


@router.delete("/pins/{pin_id}")
def delete_pin(
    pin_id: str,
    request: Request,
    session_id: str | None = None,
) -> dict:
    scope = _scope_or_403(request, session_id, PERM_EDIT)
    owner = scope.owner_key or "default"
    return {"ok": pin_service.unpin(owner, pin_id)}
