# File: backend/app/middleware.py
"""
Production-hardening HTTP middleware.

All middleware read `settings` live at request time so configuration (and tests)
can toggle behavior without rebuilding the app. Order of registration in
main.py: logging (outermost) -> security headers -> user authentication -> rate limit.
"""

from __future__ import annotations

import logging
import threading
import time

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings

logger = logging.getLogger("aira_x.request")

# Per-client fixed-window counters: {client: [window_start, count]}.
_RATE_LIMIT_STATE: dict[str, list] = {}
_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMIT_WINDOW_SECONDS = 60
_LOGIN_FAILURE_STATE: dict[str, list] = {}
_LOGIN_FAILURE_LOCK = threading.Lock()


def reset_rate_limit() -> None:
    """Clear rate-limit counters (used by tests)."""
    with _RATE_LIMIT_LOCK:
        _RATE_LIMIT_STATE.clear()


def reset_login_rate_limit() -> None:
    """Clear login-failure counters (used by deterministic tests)."""
    with _LOGIN_FAILURE_LOCK:
        _LOGIN_FAILURE_STATE.clear()


def _is_public(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in settings.public_paths)


def _client_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def enforce_login_failure_limit(request: Request) -> None:
    """Reject a client whose failed-login window is already exhausted."""
    key = _client_address(request)
    now = time.time()
    window = settings.login_failure_window_seconds
    with _LOGIN_FAILURE_LOCK:
        bucket = _LOGIN_FAILURE_STATE.get(key)
        if bucket is None or now - bucket[0] >= window:
            return
        if bucket[1] >= settings.login_failure_limit:
            retry_after = max(1, int(window - (now - bucket[0])))
            raise HTTPException(
                status_code=429,
                detail="Too many failed login attempts. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )


def record_login_failure(request: Request) -> None:
    key = _client_address(request)
    now = time.time()
    window = settings.login_failure_window_seconds
    with _LOGIN_FAILURE_LOCK:
        bucket = _LOGIN_FAILURE_STATE.get(key)
        if bucket is None or now - bucket[0] >= window:
            _LOGIN_FAILURE_STATE[key] = [now, 1]
        else:
            bucket[1] += 1


def clear_login_failures(request: Request) -> None:
    with _LOGIN_FAILURE_LOCK:
        _LOGIN_FAILURE_STATE.pop(_client_address(request), None)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.request_logging_enabled:
            return await call_next(request)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - start) * 1000
            logger.exception(
                "%s %s -> error after %.1fms", request.method, request.url.path, elapsed
            )
            raise
        elapsed = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s -> %s %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed,
        )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        if settings.security_headers_enabled:
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("Referrer-Policy", "no-referrer")
            response.headers.setdefault("X-XSS-Protection", "0")
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if (
            not settings.rate_limit_enabled
            or request.method == "OPTIONS"
            or _is_public(request.url.path)
        ):
            return await call_next(request)

        # Principal-aware: an authenticated key gets its own bucket; otherwise
        # fall back to the client IP. (Keying on the body's session id would
        # require reading the request body, which breaks streaming.)
        principal = getattr(request.state, "principal", None)
        if principal is not None and getattr(principal, "is_account", False):
            client = f"account:{principal.account_id}"
        else:
            client = _client_address(request)
        limit = settings.rate_limit_per_minute
        now = time.time()

        with _RATE_LIMIT_LOCK:
            bucket = _RATE_LIMIT_STATE.get(client)
            if bucket is None or now - bucket[0] >= _RATE_LIMIT_WINDOW_SECONDS:
                _RATE_LIMIT_STATE[client] = [now, 1]
                over_limit = False
            else:
                bucket[1] += 1
                over_limit = bucket[1] > limit
                window_start = bucket[0]

            # Opportunistic cleanup so the dict doesn't grow unbounded.
            if len(_RATE_LIMIT_STATE) > 10_000:
                for key in [
                    k for k, v in _RATE_LIMIT_STATE.items()
                    if now - v[0] >= _RATE_LIMIT_WINDOW_SECONDS
                ]:
                    _RATE_LIMIT_STATE.pop(key, None)

        if over_limit:
            retry_after = max(1, int(_RATE_LIMIT_WINDOW_SECONDS - (now - window_start)))
            return JSONResponse(
                {"error": "Rate limit exceeded. Please slow down and try again."},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)


class UserAuthenticationMiddleware(BaseHTTPMiddleware):
    """Default-deny user gate; privileged routes authenticate themselves.

    A service key is deliberately not a user credential. Caller-supplied
    session/workspace fields are never considered authenticated identity here.
    """

    async def dispatch(self, request: Request, call_next):
        from app.auth import (
            Principal,
            development_bypass_principal,
            resolve_account_principal,
        )

        path = request.url.path
        if request.method == "OPTIONS" or _is_public(path):
            request.state.principal = Principal(
                kind="anonymous",
                subject="",
                authenticated=False,
                authentication_method="public",
            )
            return await call_next(request)

        # Every operator route performs an explicit, constant-time service-key
        # check. Do not run the user gate first: a user token is not operator auth.
        if path == "/operator" or path.startswith("/operator/"):
            return await call_next(request)

        account = resolve_account_principal(request) if settings.user_auth_enabled else None
        if account is not None:
            request.state.principal = account
            return await call_next(request)

        # An invalid Authorization header never falls back to development mode.
        if request.headers.get("Authorization"):
            return JSONResponse(
                {"error": "User authentication required."},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        # A privileged credential can never impersonate an ordinary user.
        if request.headers.get(settings.api_key_header):
            return JSONResponse(
                {"error": "User authentication required."},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        explicit_local_bypass = (
            settings.environment == "development"
            and settings.allow_anonymous_protected_access
            and settings.development_auth_bypass
        )
        if explicit_local_bypass:
            request.state.principal = development_bypass_principal()
            return await call_next(request)

        return JSONResponse(
            {"error": "User authentication required."},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
