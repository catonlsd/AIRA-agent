# File: backend/app/auth.py
"""
Identity / ownership layer for AIRA-X.

A single, swappable place to answer "who is the current principal, and what do
they own?" Today the product has no login, so a principal is derived from the
request: an authenticated API key when one is configured, otherwise the
client's session id. Every owned resource — runs, guided-flow pending state,
artifacts, uploaded documents — is scoped to a stable `owner_key`.

This keeps cross-user access from being ambiguous now, and makes adding real
accounts / OAuth / team workspaces later a matter of extending `resolve_principal`
and `Principal` — not rewriting the call sites that ask `principal.owner_key`.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Optional

from app.core.config import settings

# Owner directories / capability tokens are HMACs of the owner key with this
# secret, so they are opaque and not guessable from a session id alone.
_OWNER_SECRET = (settings.api_key or "aira-x-local-owner-secret").encode("utf-8")

ANONYMOUS_OWNER = "anonymous"


@dataclass(frozen=True)
class Principal:
    """The current actor and its ownership scope."""

    kind: str           # "api_key" | "session" | "anonymous"
    subject: str        # the raw identifier (key fingerprint or session id)
    authenticated: bool

    @property
    def owner_key(self) -> str:
        """Stable ownership scope for this principal (used to tag resources)."""
        return f"{self.kind}:{self.subject}" if self.subject else ANONYMOUS_OWNER

    @property
    def owner_token(self) -> str:
        """Opaque, unguessable token for this owner (capability URLs / dirs)."""
        return owner_token_for(self.owner_key)


def owner_token_for(owner_key: str) -> str:
    """Deterministic, opaque token for an owner key (filesystem/URL safe)."""
    return hmac.new(_OWNER_SECRET, owner_key.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def _key_fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


def resolve_principal(
    *,
    api_key: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Principal:
    """Resolve the principal for a request.

    Precedence: a valid configured API key authenticates a principal; otherwise
    the session id is the owner; otherwise anonymous. Wrong API keys never
    silently fall back to a session (the middleware already rejects them).
    """
    configured = settings.api_key
    if configured and api_key and hmac.compare_digest(api_key, configured):
        return Principal(kind="api_key", subject=_key_fingerprint(api_key), authenticated=True)
    if session_id and session_id.strip():
        return Principal(kind="session", subject=session_id.strip(), authenticated=False)
    return Principal(kind="anonymous", subject="", authenticated=False)


def principal_from_request(request, *, session_id: Optional[str] = None) -> Principal:
    """FastAPI-friendly resolver from a Starlette/FastAPI request."""
    api_key = None
    try:
        api_key = request.headers.get(settings.api_key_header)
    except Exception:
        api_key = None
    return resolve_principal(api_key=api_key, session_id=session_id)
