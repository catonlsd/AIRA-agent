# File: backend/app/middleware.py
"""
Production-hardening HTTP middleware.

All middleware read `settings` live at request time so configuration (and tests)
can toggle behavior without rebuilding the app. Order of registration in
main.py: logging (outermost) -> security headers -> rate limit -> api key.
"""

from __future__ import annotations

import logging
import threading
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings

logger = logging.getLogger("aira_x.request")

# Per-client fixed-window counters: {client: [window_start, count]}.
_RATE_LIMIT_STATE: dict[str, list] = {}
_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMIT_WINDOW_SECONDS = 60


def reset_rate_limit() -> None:
    """Clear rate-limit counters (used by tests)."""
    with _RATE_LIMIT_LOCK:
        _RATE_LIMIT_STATE.clear()


def _is_public(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in settings.public_paths)


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
        api_key = request.headers.get(settings.api_key_header) if settings.api_key else None
        client = f"key:{api_key[:16]}" if api_key else (request.client.host if request.client else "unknown")
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


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        api_key = settings.api_key
        # Auth disabled when no key configured (local development).
        if not api_key or request.method == "OPTIONS" or _is_public(request.url.path):
            return await call_next(request)

        provided = request.headers.get(settings.api_key_header)
        if not provided or provided != api_key:
            return JSONResponse({"error": "Unauthorized: invalid or missing API key."}, status_code=401)
        return await call_next(request)
