# File: backend/tests/test_accounts_auth.py
"""Account/auth identity: real account records, signed session tokens, the
account-vs-session owner distinction, and account-scoped durable ownership with
strict cross-account isolation. Session/anonymous mode stays unchanged."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.accounts import AccountError, account_service
from app.auth import (
    Principal,
    make_account_token,
    resolve_account_principal,
    resolve_owner,
    verify_account_token,
)
from app.main import app
from app.memory.preference_memory import preference_memory

client = TestClient(app)


def _email() -> str:
    return f"user_{uuid4().hex[:10]}@example.com"


class _Req:
    """Minimal stand-in for a Starlette request carrying headers."""

    def __init__(self, headers):
        self.headers = headers


# ── Account service ──────────────────────────────────────────────────────────


def test_register_authenticate_and_reject_bad_password():
    email = _email()
    account = account_service.register(email, "password123", "Ada")
    assert account["email"] == email
    assert account["display_name"] == "Ada"
    assert account["owner_key"] == f"account:{account['id']}"
    assert "password" not in account and "password_hash" not in account  # never leaked

    assert account_service.authenticate(email, "password123") is not None
    assert account_service.authenticate(email, "wrong") is None
    assert account_service.authenticate("nobody@example.com", "password123") is None


def test_registration_validates_input():
    with pytest.raises(AccountError):
        account_service.register("not-an-email", "password123")
    with pytest.raises(AccountError):
        account_service.register(_email(), "short")  # < 8 chars


def test_duplicate_email_is_rejected():
    email = _email()
    account_service.register(email, "password123")
    with pytest.raises(AccountError):
        account_service.register(email, "password123")


# ── Tokens ───────────────────────────────────────────────────────────────────


def test_token_round_trips_and_rejects_tampering():
    account = account_service.register(_email(), "password123")
    token = make_account_token(account["id"])
    assert verify_account_token(token) == account["id"]
    assert verify_account_token(token[:-2] + "xx") is None  # bad signature
    assert verify_account_token("garbage") is None
    assert verify_account_token(None) is None


def test_expired_token_is_rejected():
    account = account_service.register(_email(), "password123")
    token = make_account_token(account["id"], ttl_seconds=-1)  # already expired
    assert verify_account_token(token) is None


# ── Principal + owner resolution (account vs session) ────────────────────────


def test_account_principal_resolves_from_bearer_token():
    account = account_service.register(_email(), "password123")
    req = _Req({"Authorization": f"Bearer {make_account_token(account['id'])}"})
    principal = resolve_account_principal(req)
    assert isinstance(principal, Principal)
    assert principal.is_account and principal.account_id == account["id"]
    assert principal.owner_key == f"account:{account['id']}"


def test_owner_is_account_when_authenticated_else_session():
    account = account_service.register(_email(), "password123")
    req = _Req({"Authorization": f"Bearer {make_account_token(account['id'])}"})
    # Authenticated -> durable account scope (cross-device), regardless of session.
    assert resolve_owner(req, "browser-session-1") == f"account:{account['id']}"
    # Unauthenticated -> the session is the owner (unchanged local behaviour).
    assert resolve_owner(_Req({}), "browser-session-1") == "browser-session-1"
    assert resolve_owner(None, "browser-session-1") == "browser-session-1"


# ── HTTP endpoints ───────────────────────────────────────────────────────────


def test_register_login_me_endpoints():
    email = _email()
    reg = client.post("/auth/register", json={"email": email, "password": "password123", "display_name": "Grace"})
    assert reg.status_code == 200
    token = reg.json()["token"]
    assert reg.json()["account"]["email"] == email

    login = client.post("/auth/login", json={"email": email, "password": "password123"})
    assert login.status_code == 200 and login.json()["token"]

    bad = client.post("/auth/login", json={"email": email, "password": "nope"})
    assert bad.status_code == 401

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["account"]["email"] == email
    assert client.get("/auth/me").status_code == 401  # no token


# ── Account-scoped durable ownership + isolation ─────────────────────────────


def test_preferences_are_account_scoped_and_isolated():
    alice = account_service.register(_email(), "password123")
    bob = account_service.register(_email(), "password123")
    a_tok = make_account_token(alice["id"])
    b_tok = make_account_token(bob["id"])

    # Alice saves a preference while authenticated -> stored under her account.
    client.put("/preferences", json={"key": "answer_length", "value": "concise"},
               headers={"Authorization": f"Bearer {a_tok}"})
    assert preference_memory.get(f"account:{alice['id']}") == {"answer_length": "concise"}

    # Bob (different account) never sees Alice's preference.
    bob_view = client.get("/preferences", headers={"Authorization": f"Bearer {b_tok}"}).json()
    val = next(e["value"] for e in bob_view["preferences"] if e["key"] == "answer_length")
    assert val is None

    # A plain session (no token) is a separate scope and is also isolated.
    session_view = client.get("/preferences", params={"session_id": "anon-1"}).json()
    val2 = next(e["value"] for e in session_view["preferences"] if e["key"] == "answer_length")
    assert val2 is None


def test_account_preference_persists_across_sessions():
    # The point of accounts: durable across browser sessions/devices.
    account = account_service.register(_email(), "password123")
    tok = make_account_token(account["id"])
    client.put("/preferences", json={"key": "answer_style", "value": "code_first"},
               headers={"Authorization": f"Bearer {tok}"})
    # A brand-new token (a "different device") for the same account sees it.
    tok2 = make_account_token(account["id"])
    view = client.get("/preferences", headers={"Authorization": f"Bearer {tok2}"}).json()
    val = next(e["value"] for e in view["preferences"] if e["key"] == "answer_style")
    assert val == "code_first"
