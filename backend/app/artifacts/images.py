# File: backend/app/artifacts/images.py
"""
Optional image resolution for artifacts (safe by default).

Image support is an architecture hook, not a guarantee. `resolve_image` returns
a real local file path ONLY when an image is genuinely available; otherwise it
returns None and generation falls back to text-only. No provider is wired by
default, so artifacts never depend on images and never claim images they don't
have. A real sourcing/generation provider can be registered later via
`set_image_provider` without touching the generators.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

# A provider takes a query and returns a local image path (or None). Kept
# pluggable so a future safe image source can be added without pipeline churn.
ImageProvider = Callable[[str], Optional[str]]

_provider: Optional[ImageProvider] = None


def set_image_provider(provider: Optional[ImageProvider]) -> None:
    global _provider
    _provider = provider


def resolve_image(query: Optional[str]) -> Optional[str]:
    """Return a usable local image path for a query, or None (text-only)."""
    if not query or _provider is None:
        return None
    try:
        path = _provider(query)
    except Exception:
        return None
    if not path:
        return None
    candidate = Path(path)
    # Only accept a real, existing image file — never a broken/fake path.
    if candidate.is_file() and candidate.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif"}:
        return str(candidate)
    return None
