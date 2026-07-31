"""Phase 3D authentication-gate separation and fail-closed behavior."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.auth as auth_module
from app.accounts import account_service
from app.auth import make_account_token, resolve_account_principal, resolve_operator_principal
from app.core.config import Settings, settings
from app.main import app
from app.middleware import reset_login_rate_limit


client = TestClient(app)


def _email() -> str:
    return f"phase3d-{uuid4().hex}@example.com"


def _account() -> dict:
    return account_service.register(_email(), "password123")


def _bearer(account: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_account_token(account['id'])}"}


def _close_local_bypass(monkeypatch) -> None:
    monkeypatch.setattr(settings, "allow_anonymous_protected_access", False)
    monkeypatch.setattr(settings, "development_auth_bypass", False)


def _safe_settings(environment: str) -> Settings:
    return Settings(
        _env_file=None,
        environment=environment,
        llm_provider="local",
        web_search_provider="none",
        api_key="operator-secret-with-at-least-24-characters",
        auth_secret="account-secret-with-at-least-24-characters",
        cors_origins=["https://preview.aira.example.com"],
        cors_origin_regex=None,
    )


def test_public_health_and_readiness_need_no_credentials(monkeypatch):
    _close_local_bypass(monkeypatch)
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code in (200, 503)


def test_user_route_accepts_account_bearer_and_sets_canonical_principal(monkeypatch):
    _close_local_bypass(monkeypatch)
    account = _account()
    response = client.get("/preferences", headers=_bearer(account))
    assert response.status_code == 200

    class Request:
        headers = _bearer(account)

    principal = resolve_account_principal(Request())
    assert principal is not None
    assert principal.account_id == account["id"]
    assert principal.authentication_method == "account_bearer"
    assert principal.account_status == "active"
    assert principal.roles == ("user",)


def test_user_route_rejects_missing_invalid_and_service_only_auth(monkeypatch):
    _close_local_bypass(monkeypatch)
    monkeypatch.setattr(settings, "api_key", "operator-secret")

    missing = client.get("/preferences")
    invalid = client.get("/preferences", headers={"Authorization": "Bearer invalid"})
    service_only = client.get("/preferences", headers={"X-API-Key": "operator-secret"})

    assert missing.status_code == invalid.status_code == service_only.status_code == 401
    assert "operator-secret" not in missing.text + invalid.text + service_only.text


def test_signed_token_for_unknown_account_is_not_a_principal(monkeypatch):
    _close_local_bypass(monkeypatch)
    token = make_account_token("nonexistent-account")
    response = client.get(
        "/preferences", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


def test_service_secret_cannot_verify_account_tokens(monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "separate-account-secret")
    token = make_account_token(_account()["id"])
    monkeypatch.setattr(settings, "auth_secret", "operator-secret")
    monkeypatch.setattr(settings, "api_key", "operator-secret")
    assert auth_module.verify_account_token(token) is None


def test_service_endpoint_accepts_only_service_auth(monkeypatch):
    _close_local_bypass(monkeypatch)
    monkeypatch.setattr(settings, "api_key", "operator-secret")
    account = _account()

    assert client.get("/operator/overview").status_code == 401
    assert client.get("/operator/overview", headers=_bearer(account)).status_code == 401
    assert client.get("/operator/overview", headers={"X-API-Key": "wrong"}).status_code == 401
    assert (
        client.get("/operator/overview", headers={"X-API-Key": "operator-secret"}).status_code
        == 200
    )


def test_service_auth_uses_constant_time_comparison(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "operator-secret")
    comparisons: list[tuple[str, str]] = []

    def compared(left: str, right: str) -> bool:
        comparisons.append((left, right))
        return left == right

    monkeypatch.setattr(auth_module.hmac, "compare_digest", compared)

    class Request:
        headers = {"X-API-Key": "operator-secret"}

    principal = resolve_operator_principal(Request())
    assert principal is not None and principal.is_operator
    assert comparisons
    assert all(pair == ("operator-secret", "operator-secret") for pair in comparisons)


def test_service_key_cannot_select_or_impersonate_user(monkeypatch):
    _close_local_bypass(monkeypatch)
    monkeypatch.setattr(settings, "api_key", "operator-secret")
    response = client.get(
        "/preferences?session_id=victim",
        headers={"X-API-Key": "operator-secret", "X-User-Id": "victim"},
    )
    assert response.status_code == 401


def test_authenticated_but_underprivileged_workspace_user_gets_403(monkeypatch):
    _close_local_bypass(monkeypatch)
    owner, viewer, invitee = _account(), _account(), _account()
    workspace = client.post(
        "/workspaces", json={"name": "Phase 3D"}, headers=_bearer(owner)
    ).json()["workspace"]
    client.post(
        f"/workspaces/{workspace['id']}/members",
        json={"email": viewer["email"], "role": "viewer"},
        headers=_bearer(owner),
    )
    response = client.post(
        f"/workspaces/{workspace['id']}/members",
        json={"email": invitee["email"], "role": "viewer"},
        headers=_bearer(viewer),
    )
    assert response.status_code == 403


def test_explicit_local_development_bypass(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "allow_anonymous_protected_access", True)
    monkeypatch.setattr(settings, "development_auth_bypass", True)
    assert client.get("/aira-x/agents").status_code == 200


@pytest.mark.parametrize("environment", ["preview", "production"])
def test_non_development_rejects_anonymous_mode(environment):
    config = _safe_settings(environment)
    config.allow_anonymous_protected_access = True
    with pytest.raises(RuntimeError, match="ALLOW_ANONYMOUS_PROTECTED_ACCESS"):
        config.validate_runtime_config()


@pytest.mark.parametrize("environment", ["preview", "production"])
def test_non_development_rejects_development_bypass(environment):
    config = _safe_settings(environment)
    config.development_auth_bypass = True
    with pytest.raises(RuntimeError, match="DEVELOPMENT_AUTH_BYPASS"):
        config.validate_runtime_config()


@pytest.mark.parametrize("environment", ["preview", "production"])
def test_non_development_rejects_disabled_user_auth(environment):
    config = _safe_settings(environment)
    config.user_auth_enabled = False
    with pytest.raises(RuntimeError, match="USER_AUTH_ENABLED"):
        config.validate_runtime_config()


@pytest.mark.parametrize("field", ["api_key", "auth_secret"])
def test_non_development_rejects_placeholder_secrets_without_echo(field):
    config = _safe_settings("preview")
    marker = "change-me"
    setattr(config, field, marker)
    with pytest.raises(RuntimeError) as error:
        config.validate_runtime_config()
    assert field.upper() in str(error.value)
    assert marker not in str(error.value)


def test_non_development_rejects_public_frontend_service_secret(monkeypatch):
    marker = "browser-visible-secret"
    monkeypatch.setenv("NEXT_PUBLIC_API_KEY", marker)
    config = _safe_settings("preview")
    with pytest.raises(RuntimeError) as error:
        config.validate_runtime_config()
    assert "NEXT_PUBLIC_API_KEY" in str(error.value)
    assert marker not in str(error.value)


def test_failed_logins_are_limited_without_account_enumeration(monkeypatch):
    reset_login_rate_limit()
    monkeypatch.setattr(settings, "login_failure_limit", 2)
    monkeypatch.setattr(settings, "login_failure_window_seconds", 300)
    account = _account()

    known = client.post(
        "/auth/login", json={"email": account["email"], "password": "wrong-password"}
    )
    unknown = client.post(
        "/auth/login", json={"email": _email(), "password": "wrong-password"}
    )
    limited = client.post(
        "/auth/login", json={"email": account["email"], "password": "wrong-password"}
    )

    assert known.status_code == unknown.status_code == 401
    assert known.json() == unknown.json() == {"detail": "Invalid email or password."}
    assert limited.status_code == 429
    assert limited.headers.get("Retry-After")

    reset_login_rate_limit()
    success = client.post(
        "/auth/login", json={"email": account["email"], "password": "password123"}
    )
    assert success.status_code == 200
    assert success.json()["token"]
