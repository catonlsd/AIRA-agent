# File: backend/app/artifacts/styles.py
"""
Artifact theme presets — the controlled, named template catalogue.

A small, high-quality set of presets (not endless permutations). Each preset is
a flat dataclass of typography, colour, spacing, and table treatment; generators
read formatting from it, so adding a theme is adding one registry entry and never
touches generation or validation. Themes only change *appearance* — they can
never make a file structurally invalid.

Resolution is intentional and bounded:
  - a theme is chosen per kind (a deck theme can't be applied to a spreadsheet);
  - an explicit cue in the request wins ("make it dark / modern / executive");
  - otherwise a saved artifact-style preference applies;
  - otherwise the kind's default.
Legacy profile names remain as aliases so durable pending specs keep resolving.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ArtifactStyle:
    name: str
    display_name: str = "Professional Clean"
    # Which artifact kinds this theme is valid for (keeps a deck theme off a sheet).
    kinds: tuple[str, ...] = ("pptx", "docx", "xlsx")
    dark: bool = False

    # Shared palette
    accent_rgb: tuple[int, int, int] = (37, 99, 175)     # professional blue
    heading_rgb: tuple[int, int, int] = (17, 24, 39)     # near-black headings
    body_rgb: tuple[int, int, int] = (55, 65, 81)        # slate body
    subtitle_rgb: tuple[int, int, int] = (107, 114, 128) # muted subtitle
    background_rgb: tuple[int, int, int] | None = None   # pptx slide background (dark themes)

    title_font: str = "Calibri"
    body_font: str = "Calibri"

    # PPTX sizing
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
    zebra_fill_hex: str | None = None  # alternating-row fill for readability
    min_col_width: int = 12
    max_col_width: int = 48

    extras: dict = field(default_factory=dict)


# ── The preset catalogue (small + curated) ───────────────────────────────────

THEME_PRESETS: dict[str, ArtifactStyle] = {
    "professional_clean": ArtifactStyle(
        name="professional_clean",
        display_name="Professional Clean",
        kinds=("pptx", "docx"),
        accent_rgb=(37, 99, 175),
        zebra_fill_hex=None,
    ),
    "presentation_dark": ArtifactStyle(
        name="presentation_dark",
        display_name="Presentation Dark",
        kinds=("pptx",),
        dark=True,
        accent_rgb=(0, 212, 255),
        heading_rgb=(240, 249, 255),
        body_rgb=(209, 224, 235),
        subtitle_rgb=(148, 178, 199),
        background_rgb=(15, 23, 42),
    ),
    "modern_report": ArtifactStyle(
        name="modern_report",
        display_name="Modern Report",
        kinds=("pptx", "docx"),
        accent_rgb=(13, 148, 136),  # teal
        heading_rgb=(15, 23, 42),
        body_rgb=(51, 65, 85),
        title_font="Segoe UI",
        body_font="Segoe UI",
    ),
    "executive_brief": ArtifactStyle(
        name="executive_brief",
        display_name="Executive Brief",
        kinds=("docx", "pptx"),
        accent_rgb=(33, 37, 41),  # graphite
        heading_rgb=(17, 24, 39),
        body_rgb=(33, 37, 41),
        subtitle_rgb=(90, 98, 112),
        title_font="Georgia",
        body_font="Calibri",
    ),
    "spreadsheet_clean": ArtifactStyle(
        name="spreadsheet_clean",
        display_name="Spreadsheet Clean",
        kinds=("xlsx",),
        accent_rgb=(31, 157, 85),
        header_fill_hex="FF1F9D55",
        header_font_hex="FFFFFFFF",
        zebra_fill_hex="FFF3F6F4",
    ),
}

_DEFAULT_BY_KIND = {
    "pptx": "professional_clean",
    "docx": "executive_brief",
    "xlsx": "spreadsheet_clean",
}

# Legacy names + the saved-preference value map onto curated presets.
_ALIASES = {
    "presentation_default": "professional_clean",
    "report_default": "executive_brief",
    "spreadsheet_default": "spreadsheet_clean",
    "clean_professional": "professional_clean",
}

# Words in a request that explicitly select a theme (current-turn override).
_THEME_CUES: tuple[tuple[str, str], ...] = (
    (r"\bdark\b", "presentation_dark"),
    (r"\bmodern\b|\bsleek\b|\bvibrant\b", "modern_report"),
    (r"\bexecutive\b|\bbrief\b|\bformal\b|\bboard(?:room)?\b", "executive_brief"),
    (r"\bclean\b|\bprofessional\b|\bminimal\b|\bsimple\b", "professional_clean"),
)


def _default_for(kind: str) -> ArtifactStyle:
    return THEME_PRESETS[_DEFAULT_BY_KIND.get(kind, "professional_clean")]


def get_style(kind: str, name: str | None = None) -> ArtifactStyle:
    """Resolve a theme for a kind. Falls back to the kind default when the name
    is unknown or not valid for that kind — appearance only, never invalid."""
    key = _ALIASES.get(name or "", name) if name else _DEFAULT_BY_KIND.get(kind, "professional_clean")
    style = THEME_PRESETS.get(key)
    if style is None or kind not in style.kinds:
        return _default_for(kind)
    return style


def themes_for_kind(kind: str) -> list[ArtifactStyle]:
    """The curated themes valid for a given artifact kind."""
    return [s for s in THEME_PRESETS.values() if kind in s.kinds]


def match_theme_in_text(text: str, kind: str) -> str | None:
    """An explicit theme cue in the request, valid for this kind (else None)."""
    lowered = (text or "").lower()
    for pattern, theme in _THEME_CUES:
        if re.search(pattern, lowered):
            style = THEME_PRESETS.get(theme)
            if style and kind in style.kinds:
                return theme
    return None


def theme_from_preference(pref_value: str | None, kind: str) -> str | None:
    """Map a saved artifact-style preference to a theme valid for this kind."""
    if not pref_value:
        return None
    key = _ALIASES.get(pref_value, pref_value)
    style = THEME_PRESETS.get(key)
    return key if (style and kind in style.kinds) else None


def resolve_theme(kind: str, goal: str, preference_value: str | None = None) -> ArtifactStyle:
    """Choose a theme: an explicit request cue wins, then a saved preference,
    then the kind default. The current turn always overrides saved preferences."""
    cue = match_theme_in_text(goal, kind)
    if cue:
        return get_style(kind, cue)
    pref = theme_from_preference(preference_value, kind)
    if pref:
        return get_style(kind, pref)
    return _default_for(kind)
