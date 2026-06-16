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

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Optional

from app.core.config import settings

# Owner directories / capability tokens are HMACs of the owner key with this
# secret, so they are opaque and not guessable from a session id alone.
_OWNER_SECRET = (settings.api_key or "aira-x-local-owner-secret").encode("utf-8")

ANONYMOUS_OWNER = "anonymous"


def _auth_secret() -> bytes:
    return (settings.auth_secret or settings.api_key or "aira-x-local-auth-secret").encode("utf-8")


@dataclass(frozen=True)
class Principal:
    """The current actor and its ownership scope.

    Identity has three layers, kept distinct on purpose:
      * an authenticated **account** (durable, cross-device) — kind "account";
      * a **session** (transport/local continuity) — kind "session";
      * a service **api_key** gate or **anonymous** — neither a durable identity.

    `owner_key` is the durable scope used to tag resources. An account owns
    "account:<id>"; a session owns "session:<id>". This makes the session-vs-
    account distinction explicit and keeps the door open for a future
    `workspace:<id>` scope without changing the call sites.
    """

    kind: str           # "account" | "api_key" | "session" | "anonymous"
    subject: str        # account id | key fingerprint | session id
    authenticated: bool
    account_id: Optional[str] = None  # set only for authenticated accounts

    @property
    def is_account(self) -> bool:
        return self.kind == "account" and bool(self.account_id)

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
    """FastAPI-friendly resolver from a Starlette/FastAPI request.

    Precedence: a valid account token (durable identity) wins; then the service
    api-key gate; then the session; then anonymous.
    """
    account = resolve_account_principal(request)
    if account is not None:
        return account
    api_key = None
    try:
        api_key = request.headers.get(settings.api_key_header)
    except Exception:
        api_key = None
    return resolve_principal(api_key=api_key, session_id=session_id)


# ── Account session tokens (stateless, HMAC-signed) ──────────────────────────


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def make_account_token(account_id: str, *, ttl_seconds: Optional[int] = None) -> str:
    """Sign a compact, expiring token that resolves to an account.

    Stateless and dependency-free: `payload.signature`, HMAC-SHA256 over the
    payload. No DB round-trip to verify; rotation/expiry is handled by `exp`.
    """
    ttl = ttl_seconds if ttl_seconds is not None else settings.auth_token_ttl_seconds
    payload = {"sub": account_id, "iat": int(time.time()), "exp": int(time.time()) + int(ttl)}
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64url(hmac.new(_auth_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_account_token(token: Optional[str]) -> Optional[str]:
    """Return the account id for a valid, unexpired token, else None."""
    if not token or "." not in token:
        return None
    body, _, sig = token.partition(".")
    expected = _b64url(hmac.new(_auth_secret(), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_b64url_decode(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) and sub else None


def _bearer_token(request) -> Optional[str]:
    try:
        header = request.headers.get("Authorization") or ""
    except Exception:
        return None
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def resolve_account_principal(request) -> Optional[Principal]:
    """Resolve an authenticated account from the request's bearer token, or None."""
    account_id = verify_account_token(_bearer_token(request))
    if not account_id:
        return None
    return Principal(kind="account", subject=account_id, authenticated=True, account_id=account_id)


# ── Resource scope (session / account / workspace) ───────────────────────────

WORKSPACE_HEADER = "X-Workspace-Id"

SCOPE_SESSION = "session"
SCOPE_ACCOUNT = "account"
SCOPE_WORKSPACE = "workspace"
SCOPE_ANONYMOUS = "anonymous"


@dataclass(frozen=True)
class ResourceScope:
    """The explicit scope that owns the resources of a request.

    One object answers every ownership question the system needs: which durable
    key to store/retrieve under (`owner_key`), whether the resource is personal
    or workspace-shared, and which account is acting. The owner key strings are
    backward-compatible — a session still owns its raw id, an account owns
    `account:<id>` — and a workspace owns `workspace:<id>`. Nothing downstream
    changes shape; scope just becomes explicit and extensible.
    """

    kind: str                          # session | account | workspace | anonymous
    subject: str                       # session id | account id | workspace id
    account_id: Optional[str] = None   # the acting account (account/workspace scope)
    workspace_id: Optional[str] = None  # set only for workspace scope
    label: str = ""                    # human label ("Personal", workspace name)

    @property
    def owner_key(self) -> str:
        # Session keeps its RAW id (backward-compatible durable owner); account
        # and workspace are namespaced and distinct.
        if self.kind == SCOPE_SESSION:
            return self.subject or ANONYMOUS_OWNER
        return f"{self.kind}:{self.subject}" if self.subject else ANONYMOUS_OWNER

    @property
    def owner_token(self) -> str:
        return owner_token_for(self.owner_key)

    @property
    def is_account(self) -> bool:
        return self.kind == SCOPE_ACCOUNT

    @property
    def is_workspace(self) -> bool:
        return self.kind == SCOPE_WORKSPACE

    @property
    def is_personal(self) -> bool:
        """Personal scope = anything not shared across a workspace."""
        return self.kind != SCOPE_WORKSPACE


def _workspace_header(request) -> Optional[str]:
    try:
        value = request.headers.get(WORKSPACE_HEADER)
    except Exception:
        return None
    return value.strip() if value and value.strip() else None


def resolve_scope(request, session_id: Optional[str] = None) -> ResourceScope:
    """Resolve the active resource scope for a request.

    Precedence: an authenticated account acting in a workspace it belongs to ->
    workspace scope; otherwise the account's personal scope; otherwise the
    session; otherwise anonymous. A workspace header is honoured ONLY when the
    account is a member — an unknown/forbidden workspace silently falls back to
    personal scope, never leaking another team's data.
    """
    account = resolve_account_principal(request) if request is not None else None
    if account is not None:
        workspace_id = _workspace_header(request)
        if workspace_id:
            from app.workspaces import workspace_service

            ws = workspace_service.get_if_member(workspace_id, account.account_id or "")
            if ws is not None:
                return ResourceScope(
                    kind=SCOPE_WORKSPACE,
                    subject=workspace_id,
                    account_id=account.account_id,
                    workspace_id=workspace_id,
                    label=ws.get("name", "Workspace"),
                )
        return ResourceScope(
            kind=SCOPE_ACCOUNT, subject=account.account_id or "",
            account_id=account.account_id, label="Personal",
        )
    sid = (session_id or "").strip()
    if sid:
        return ResourceScope(kind=SCOPE_SESSION, subject=sid, label="This device")
    return ResourceScope(kind=SCOPE_ANONYMOUS, subject="", label="Anonymous")


def resolve_owner(request, session_id: Optional[str] = None) -> Optional[str]:
    """The durable owner key for a request (scope-aware).

    Thin wrapper over `resolve_scope` for the many call sites that just need the
    storage key. Behaviour is unchanged for personal/session use; a workspace
    header (for a member) returns the workspace owner key instead.
    """
    scope = resolve_scope(request, session_id)
    if scope.kind == SCOPE_ANONYMOUS:
        return None
    return scope.owner_key


def accessible_owner_tokens(account_id: Optional[str]) -> set[str]:
    """Owner tokens an account may access: its own personal scope plus every
    workspace it belongs to. Used to authorize capability URLs (artifact
    downloads) without reversing the opaque token."""
    if not account_id:
        return set()
    tokens = {owner_token_for(f"{SCOPE_ACCOUNT}:{account_id}")}
    try:
        from app.workspaces import workspace_service

        for workspace_id in workspace_service.member_workspace_ids(account_id):
            tokens.add(owner_token_for(f"{SCOPE_WORKSPACE}:{workspace_id}"))
    except Exception:
        pass
    return tokens
