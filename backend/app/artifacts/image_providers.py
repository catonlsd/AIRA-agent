# File: backend/app/artifacts/image_providers.py
"""
Safe, optional image sourcing for artifacts.

A real provider for the `resolve_image` hook, backed by Openverse — an aggregator
of openly/CC-licensed images (no API key). It is deliberately conservative:

  * commercial-use, non-mature results only;
  * a short timeout and a capped download size;
  * accepts only real PNG/JPG/GIF bytes (what python-pptx can embed);
  * every step guarded — any failure returns None, so the artifact silently
    falls back to text-only and generation NEVER breaks or hangs;
  * per-query in-process cache so a deck never refetches the same subject.

Network calls (search + download) are injectable, so tests are fully hermetic
and the source can be swapped (Unsplash/Pexels/internal) without touching the
generators. Honest by construction: an image is only ever returned when real
image bytes were actually fetched and saved.
"""

from __future__ import annotations

import json
import os
import tempfile
import urllib.parse
import urllib.request
from typing import Callable, Optional

from app.core.config import settings

_OPENVERSE_API = "https://api.openverse.org/v1/images/"
_USER_AGENT = "AIRA-X/1.0 (artifact image sourcing)"
_MAX_BYTES = 6_000_000
_EXT_BY_TYPE = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif"}


class OpenverseImageProvider:
    """Resolve a query to a local image path, or None (text-only fallback)."""

    def __init__(
        self,
        *,
        search: Optional[Callable[[str], Optional[str]]] = None,
        download: Optional[Callable[[str], Optional[str]]] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self._search = search or self._default_search
        self._download = download or self._default_download
        self._timeout = timeout if timeout is not None else settings.artifact_image_timeout_seconds
        self._cache: dict[str, Optional[str]] = {}

    def __call__(self, query: str) -> Optional[str]:
        if not query:
            return None
        if query in self._cache:
            return self._cache[query]
        path: Optional[str] = None
        try:
            url = self._search(query)
            if url:
                path = self._download(url)
        except Exception:
            path = None  # any failure -> text-only, never break generation
        self._cache[query] = path
        return path

    # ── default network implementations (injectable for tests) ───────────────

    def _default_search(self, query: str) -> Optional[str]:
        params = urllib.parse.urlencode(
            {"q": query, "page_size": 3, "license_type": "commercial", "mature": "false"}
        )
        request = urllib.request.Request(
            f"{_OPENVERSE_API}?{params}", headers={"User-Agent": _USER_AGENT}
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            data = json.loads(response.read().decode("utf-8", "ignore"))
        for item in data.get("results", []) or []:
            # Prefer the Openverse-hosted thumbnail (reliable + slide-sized).
            for key in ("thumbnail", "url"):
                candidate = item.get(key)
                if isinstance(candidate, str) and candidate.startswith("http"):
                    return candidate
        return None

    def _default_download(self, url: str) -> Optional[str]:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            ext = _EXT_BY_TYPE.get(content_type)
            if not ext:
                return None
            data = response.read(_MAX_BYTES + 1)
        if len(data) < 1000 or len(data) > _MAX_BYTES:
            return None
        fd, tmp = tempfile.mkstemp(suffix=ext, prefix="aira_img_")
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        return tmp


def build_default_provider() -> Optional[OpenverseImageProvider]:
    """The configured provider, or None when image sourcing is disabled."""
    if not settings.enable_artifact_images:
        return None
    if settings.artifact_image_provider == "openverse":
        return OpenverseImageProvider()
    return None
