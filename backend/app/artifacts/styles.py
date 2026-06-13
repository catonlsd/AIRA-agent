# File: backend/app/artifacts/styles.py
"""
Artifact style profiles — the clean seam for templates/formatting.

Each artifact kind has a default style profile (fonts, sizes, accent colour,
spacing, table formatting). Generators read formatting from the profile instead
of hardcoding it, so richer templates or per-request styles can be added later
without touching generation logic. Intentionally a small dataclass registry,
not a templating engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ArtifactStyle:
    name: str
    accent_rgb: tuple[int, int, int] = (37, 99, 175)  # professional blue
    # PPTX
    title_size_pt: int = 40
    slide_title_size_pt: int = 30
    body_size_pt: int = 18
    section_size_pt: int = 40
    max_bullets_per_slide: int = 6
    # DOCX
    heading_levels: tuple[int, ...] = (1, 2)
    # XLSX
    header_fill_hex: str = "FF2563AF"
    header_font_hex: str = "FFFFFFFF"
    min_col_width: int = 12
    max_col_width: int = 48
    extras: dict = field(default_factory=dict)


_PROFILES: dict[str, ArtifactStyle] = {
    "presentation_default": ArtifactStyle(name="presentation_default"),
    "report_default": ArtifactStyle(name="report_default", accent_rgb=(33, 37, 41)),
    "spreadsheet_default": ArtifactStyle(name="spreadsheet_default"),
}

_DEFAULT_BY_KIND = {
    "pptx": "presentation_default",
    "docx": "report_default",
    "xlsx": "spreadsheet_default",
}


def get_style(kind: str, name: str | None = None) -> ArtifactStyle:
    """Resolve a style profile for an artifact kind (default unless overridden)."""
    profile = name or _DEFAULT_BY_KIND.get(kind, "presentation_default")
    return _PROFILES.get(profile, _PROFILES["presentation_default"])
