# File: backend/app/accounts.py
"""
Account service — durable human identity for AIRA-X.

Register / authenticate / fetch accounts, backed by the existing SQLAlchemy
engine. Passwords are bcrypt-hashed; only the public view (id, email, display
name, timestamps) ever leaves this module. The interface is small and swappable
so a hosted identity provider (or SSO) can replace it later without touching the
owner-scoped call sites — they only ever ask for an account's `owner_key`.

Ownership note: an account's durable owner scope is `account:<id>`, distinct
from a session's raw id, so authenticated data is account-owned (cross-device)
while anonymous/local use stays session-scoped.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from uuid import uuid4

import bcrypt

from app.db.database import Base, SessionLocal, engine
from app.db.models import Account

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LEN = 8


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def account_owner_key(account_id: str) -> str:
    """The durable owner scope for an account (distinct from a session id)."""
    return f"account:{account_id}"


class AccountError(ValueError):
    """A clean, user-safe account error (bad input / duplicate / auth fail)."""


class AccountService:
    def __init__(self, session_factory: Callable[[], Any] = SessionLocal) -> None:
        self._session_factory = session_factory
        self._ensure_table()

    def _ensure_table(self) -> None:
        try:
            Account.__table__.create(bind=engine, checkfirst=True)
        except Exception:
            Base.metadata.create_all(bind=engine)

    # ── registration / login ─────────────────────────────────────────────────

    def register(self, email: str, password: str, display_name: str = "") -> dict:
        email = (email or "").strip().lower()
        if not _EMAIL_RE.match(email):
            raise AccountError("Enter a valid email address.")
        if len(password or "") < MIN_PASSWORD_LEN:
            raise AccountError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
        display = (display_name or "").strip() or email.split("@", 1)[0]

        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        with self._session_factory() as session:
            if session.query(Account).filter(Account.email == email).first():
                raise AccountError("An account with that email already exists.")
            account = Account(
                id=uuid4().hex,
                email=email,
                display_name=display,
                password_hash=password_hash,
                created_at=_now(),
                updated_at=_now(),
            )
            session.add(account)
            session.commit()
            return self._public(account)

    def authenticate(self, email: str, password: str) -> Optional[dict]:
        email = (email or "").strip().lower()
        with self._session_factory() as session:
            account = session.query(Account).filter(Account.email == email).first()
            if account is None:
                return None
            try:
                ok = bcrypt.checkpw(
                    (password or "").encode("utf-8"), account.password_hash.encode("utf-8")
                )
            except (ValueError, TypeError):
                return None
            return self._public(account) if ok else None

    def get(self, account_id: str) -> Optional[dict]:
        if not account_id:
            return None
        with self._session_factory() as session:
            account = session.query(Account).filter(Account.id == account_id).first()
            return self._public(account) if account else None

    def get_by_email(self, email: str) -> Optional[dict]:
        """Public view of an account by email (used to invite by identifier)."""
        email = (email or "").strip().lower()
        if not email:
            return None
        with self._session_factory() as session:
            account = session.query(Account).filter(Account.email == email).first()
            return self._public(account) if account else None

    # ── public view (never leaks the password hash) ──────────────────────────

    @staticmethod
    def _public(account: Account) -> dict:
        return {
            "id": account.id,
            "email": account.email,
            "display_name": account.display_name,
            "workspace_id": account.workspace_id,
            "owner_key": account_owner_key(account.id),
            "created_at": account.created_at.isoformat() if account.created_at else None,
        }


account_service = AccountService()
