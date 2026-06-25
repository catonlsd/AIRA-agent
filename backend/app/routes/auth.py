# File: backend/app/routes/auth.py
"""
Account auth endpoints — a minimal, production-minded foundation.

  POST /auth/register  -> create an account, return a session token + profile
  POST /auth/login     -> authenticate, return a session token + profile
  GET  /auth/me        -> the current account (from the bearer token), or 401
  POST /auth/logout    -> stateless; the client drops the token

Tokens are stateless HMAC-signed (see app.auth); there is no server session
table to scale. Real but minimal: email/password with bcrypt hashing, clean
error handling, and the same durable `account:<id>` owner scope the rest of the
product already understands.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.accounts import AccountError, account_service
from app.auth import make_account_token, resolve_account_principal

router = APIRouter(prefix="/auth", tags=["AIRA-X Auth"])


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


def _session(account: dict) -> dict:
    """The login payload: a token plus the public account profile."""
    return {"token": make_account_token(account["id"]), "account": account}


@router.post("/register")
def register(body: RegisterRequest) -> dict:
    try:
        account = account_service.register(body.email, body.password, body.display_name or "")
    except AccountError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return _session(account)


@router.post("/login")
def login(body: LoginRequest) -> dict:
    account = account_service.authenticate(body.email, body.password)
    if account is None:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    return _session(account)


@router.get("/me")
def me(request: Request) -> dict:
    principal = resolve_account_principal(request)
    if principal is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    account = account_service.get(principal.account_id or "")
    if account is None:
        raise HTTPException(status_code=401, detail="Account no longer exists.")
    return {"account": account}


@router.post("/logout")
def logout() -> dict:
    # Tokens are stateless; logout is the client discarding its token. Endpoint
    # exists so the client has a clear, honest action (and a seam for future
    # server-side revocation lists).
    return {"ok": True}
