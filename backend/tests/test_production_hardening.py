# File: backend/tests/test_production_hardening.py

import pytest
from fastapi.testclient import TestClient

import app.middleware as mw
from app.core.config import settings
from app.main import app, unhandled_exception_handler


@pytest.fixture
def client():
    mw.reset_rate_limit()
    with TestClient(app) as test_client:
        yield test_client
    mw.reset_rate_limit()


# ── Security headers ──────────────────────────────────────────────────────────

def test_security_headers_present(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Referrer-Policy") == "no-referrer"


# ── Readiness / liveness ──────────────────────────────────────────────────────

def test_liveness_and_readiness(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert "status" in health.json()

    ready = client.get("/ready")
    assert ready.status_code in (200, 503)
    body = ready.json()
    assert "ready" in body
    assert "database" in body["checks"]
    assert "llm" in body["checks"]


# ── API-key auth ──────────────────────────────────────────────────────────────

def test_no_auth_required_when_key_unset(client):
    # Default: settings.api_key is None -> auth disabled (local dev).
    assert client.get("/aira-x/agents").status_code == 200


def test_api_key_required_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret-key")

    # Missing/invalid key on a protected endpoint -> 401.
    assert client.get("/aira-x/agents").status_code == 401
    assert client.get("/aira-x/agents", headers={"X-API-Key": "wrong"}).status_code == 401

    # Correct key -> allowed.
    assert client.get("/aira-x/agents", headers={"X-API-Key": "secret-key"}).status_code == 200


def test_public_paths_skip_auth(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret-key")
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code in (200, 503)


# ── Rate limiting ─────────────────────────────────────────────────────────────

def test_rate_limit_returns_429_after_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 3)
    mw.reset_rate_limit()

    codes = [client.get("/aira-x/agents").status_code for _ in range(4)]
    assert codes[:3] == [200, 200, 200]
    assert codes[3] == 429
    # 429 responses still carry a Retry-After hint and security headers.
    last = client.get("/aira-x/agents")
    assert last.status_code == 429
    assert last.headers.get("Retry-After")
    assert last.headers.get("X-Content-Type-Options") == "nosniff"


def test_rate_limit_exempts_public_paths(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 1)
    mw.reset_rate_limit()
    for _ in range(5):
        assert client.get("/health").status_code == 200


def test_rate_limit_can_be_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "rate_limit_per_minute", 1)
    mw.reset_rate_limit()
    for _ in range(5):
        assert client.get("/aira-x/agents").status_code == 200


# ── Global error handler ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unhandled_exception_handler_returns_clean_500():
    class _Url:
        path = "/boom"

    class _Req:
        method = "GET"
        url = _Url()

    response = await unhandled_exception_handler(_Req(), RuntimeError("kaboom"))
    assert response.status_code == 500
    assert b"Internal server error" in response.body
    assert b"kaboom" not in response.body  # no stack/detail leak
