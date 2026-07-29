# File: backend/tests/test_production_hardening.py

import pytest
from fastapi.testclient import TestClient

import app.middleware as mw
from app.core.config import Settings, settings
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
    assert "storage" in body["checks"]


def test_readiness_fails_when_llm_is_unconfigured(client, monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", None)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["ready"] is False
    assert response.json()["checks"]["llm"] == "unconfigured"


def test_readiness_fails_when_storage_is_unwritable(client, monkeypatch, tmp_path):
    missing = tmp_path / "missing"
    monkeypatch.setattr(settings, "upload_dir", str(missing))

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["storage"] == "error"


def test_supported_groq_model_is_the_default():
    config = Settings(
        _env_file=None,
        llm_provider="local",
        web_search_provider="none",
    )

    assert config.groq_model == "openai/gpt-oss-120b"


def test_production_requires_operator_and_auth_secrets():
    config = Settings(
        _env_file=None,
        environment="production",
        llm_provider="local",
        web_search_provider="none",
        api_key=None,
        auth_secret=None,
    )

    with pytest.raises(RuntimeError, match="API_KEY"):
        config.validate_runtime_config()

    config.api_key = "operator-key"
    with pytest.raises(RuntimeError, match="AUTH_SECRET"):
        config.validate_runtime_config()


def test_production_requires_exact_non_local_cors_origins():
    config = Settings(
        _env_file=None,
        environment="production",
        llm_provider="local",
        web_search_provider="none",
        api_key="x",
        auth_secret="y",
        cors_origins=["https://aira.example.com"],
        cors_origin_regex=r"https://.*\.vercel\.app",
    )

    with pytest.raises(RuntimeError, match="CORS_ORIGIN_REGEX"):
        config.validate_runtime_config()

    config.cors_origin_regex = None
    config.cors_origins = []
    with pytest.raises(RuntimeError, match="exact CORS_ORIGINS"):
        config.validate_runtime_config()

    config.cors_origins = ["http://localhost:3000"]
    with pytest.raises(RuntimeError, match="Localhost CORS_ORIGINS"):
        config.validate_runtime_config()

    config.cors_origins = ["https://aira.example.com"]
    config.validate_runtime_config()


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
