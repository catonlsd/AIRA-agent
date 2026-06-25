# File: backend/tests/test_artifact_quality.py
"""Artifact quality v3: named theme presets, preference-aware theme defaults with
current-turn override, theme-driven PPTX/DOCX/XLSX polish that stays valid, safe
image sourcing, and richer (honest) metadata. Correctness is never traded for
polish — every generated file still validates."""

from pathlib import Path

import pytest

from app.artifacts.service import ArtifactService
from app.artifacts.spec import ArtifactSpec, Slide
from app.artifacts.styles import (
    THEME_PRESETS,
    get_style,
    match_theme_in_text,
    resolve_theme,
    themes_for_kind,
)


def _gen(kind, goal, *, preferences=None):
    service = ArtifactService()
    pending, _ = service.plan(goal, kind, preferences=preferences)  # no LLM -> deterministic
    return service.generate(pending)


# ── Theme catalogue ──────────────────────────────────────────────────────────


def test_presets_are_well_formed_and_kind_scoped():
    assert {"professional_clean", "presentation_dark", "modern_report", "executive_brief", "spreadsheet_clean"} <= set(THEME_PRESETS)
    for style in THEME_PRESETS.values():
        assert style.display_name and style.kinds
        assert len(style.accent_rgb) == 3
    # A deck theme is never offered for a spreadsheet, and vice-versa.
    assert "presentation_dark" not in {s.name for s in themes_for_kind("xlsx")}
    assert "spreadsheet_clean" not in {s.name for s in themes_for_kind("pptx")}


def test_unknown_or_mismatched_theme_falls_back_to_kind_default():
    assert get_style("pptx", "no_such_theme").name == "professional_clean"
    # A spreadsheet theme requested for a deck falls back (appearance only).
    assert get_style("pptx", "spreadsheet_clean").name == "professional_clean"


# ── Preference-aware resolution + current-turn override ──────────────────────


def test_saved_artifact_preference_selects_theme():
    style = resolve_theme("pptx", "Make a deck on solar", "clean_professional")
    assert style.name == "professional_clean"


def test_request_cue_overrides_saved_preference():
    # Saved pref = clean; request says "dark" -> the current turn wins.
    style = resolve_theme("pptx", "Make a DARK deck on solar", "clean_professional")
    assert style.name == "presentation_dark"


def test_match_theme_in_text_is_kind_aware():
    assert match_theme_in_text("a modern report", "docx") == "modern_report"
    # "dark" only maps to a deck theme; for docx it shouldn't pick a pptx-only theme.
    assert match_theme_in_text("a dark spreadsheet", "xlsx") is None


def test_generate_uses_preference_theme_and_records_it():
    out = _gen("pptx", "Make a PPT on energy", preferences={"artifact_style": "clean_professional"})
    assert out["status"] == "completed"
    assert out["artifact"]["style"] == "professional_clean"
    assert out["artifact"]["theme"] == "Professional Clean"


# ── Polish stays valid across themes ─────────────────────────────────────────


@pytest.mark.parametrize("theme", ["professional_clean", "presentation_dark", "modern_report", "executive_brief"])
def test_pptx_polish_valid_for_each_theme(theme, tmp_path):
    from app.artifacts.generators import PptxArtifactGenerator
    from app.artifacts.validator import ArtifactValidator

    spec = ArtifactSpec(
        kind="pptx",
        title="Quarterly Review",
        subtitle="FY25",
        slides=[
            Slide(title="Quarterly Review", bullets=["FY25"], layout="title"),
            Slide(title="Agenda", bullets=["A", "B"], layout="agenda"),
            Slide(title="Theme", layout="section"),
            Slide(title="Detail", bullets=["one", "two", "three"], layout="content"),
            Slide(title="Summary", bullets=["wrap up"], layout="summary"),
        ],
    )
    out = tmp_path / "deck.pptx"
    PptxArtifactGenerator().write(spec, out, get_style("pptx", theme))
    assert ArtifactValidator().validate("pptx", out)["valid"] is True


def test_docx_polish_has_title_block_and_validates():
    out = _gen("docx", "Create a report on AI in healthcare")
    assert out["status"] == "completed"
    doc_path = Path(out["artifact"]["path"])
    from docx import Document

    text = "\n".join(p.text for p in Document(str(doc_path)).paragraphs)
    assert "Prepared by AIRA-X" in text  # title-block metadata line present
    assert out["artifact"]["validation"]["valid"] is True


def test_xlsx_zebra_and_autofilter_stay_valid():
    from app.artifacts.generators import XlsxArtifactGenerator
    from app.artifacts.validator import ArtifactValidator

    spec = ArtifactSpec(
        kind="xlsx",
        title="Sales",
        sheet_name="Sales",
        headers=["Region", "Revenue"],
        rows=[["EU", 10], ["US", 20], ["APAC", 30]],
    )
    out = Path(_tmp()) / "s.xlsx"
    XlsxArtifactGenerator().write(spec, out, get_style("xlsx"))
    from openpyxl import load_workbook

    wb = load_workbook(str(out))
    ws = wb.active
    assert ws.auto_filter.ref is not None         # autofilter applied
    assert ws["A1"].font.bold is True             # themed header
    assert ArtifactValidator().validate("xlsx", out)["valid"] is True


def _tmp() -> str:
    import tempfile

    return tempfile.mkdtemp()


# ── Safe image sourcing + honest metadata ────────────────────────────────────


def test_image_count_is_zero_without_a_provider():
    out = _gen("pptx", "Make a PPT on the ocean")
    assert out["artifact"]["image_count"] == 0  # no fake "rich visuals"


def test_image_count_reflects_real_insertion(monkeypatch, tmp_path):
    png = tmp_path / "pic.png"
    png.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
        )
    )
    import app.artifacts.images as images

    monkeypatch.setattr(images, "_provider", lambda q: str(png))

    service = ArtifactService()
    pending, _ = service.plan("Make a PPT on the ocean with images", "pptx")
    # Force a slide that requests an image so the provider is exercised.
    pending.spec["slides"][-1]["image_query"] = "ocean"
    out = service.generate(pending)
    assert out["status"] == "completed"
    assert out["artifact"]["image_count"] >= 1
    assert out["artifact"]["validation"]["valid"] is True


def test_metadata_includes_counts_and_theme():
    out = _gen("pptx", "Make a PPT on space")
    art = out["artifact"]
    assert art["counts"]["slides"] >= 1
    assert art["theme"] == "Professional Clean"
    # Internals never surface as user-facing prose fields.
    assert "validation" in art and "details" in art["validation"]


def test_plan_message_names_the_theme():
    service = ArtifactService()
    _, message = service.plan("Make a clean PPT on solar", "pptx")
    assert "Professional Clean theme" in message


# ── Clean titles + image-query fallback ──────────────────────────────────────


def test_derive_title_prefers_a_quoted_topic():
    from app.artifacts.spec import derive_title

    title = derive_title("Topic “Semiconductors”. Sure to include main points, growth, etc.", "pptx")
    assert title == "Semiconductors"


def test_image_query_falls_back_to_slide_title(monkeypatch):
    # The model omits image_query; the builder derives one from the slide title.
    import json as _json

    import app.core.llm as llm_module

    payload = _json.dumps({
        "subtitle": "x",
        "slides": [{"title": "Clay Soil", "bullets": ["Clay holds water well across seasons."], "notes": "n"}],
    })
    monkeypatch.setattr(llm_module.LLMClient, "generate", lambda self, system, prompt, temperature=0.2: payload)

    service = ArtifactService()
    pending, _ = service.plan(
        "Make a PPT on soil", "pptx",
        generate=lambda **kw: llm_module.LLMClient().generate(**kw),
    )
    clay = next(s for s in pending.spec["slides"] if s["title"] == "Clay Soil")
    assert clay["image_query"]  # derived even though the model gave none


def test_revision_keeps_clean_title_via_override():
    service = ArtifactService()
    # A messy revision goal, but an explicit clean title override wins.
    pending, message = service.plan(
        "A pptx about Semiconductors. add more detail and images. richer content.",
        "pptx", title="Semiconductors",
    )
    assert pending.spec["title"] == "Semiconductors"
    assert "Semiconductors" in message
