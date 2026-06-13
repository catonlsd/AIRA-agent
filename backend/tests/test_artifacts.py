# File: backend/tests/test_artifacts.py
"""Artifact pipeline: real PPTX/DOCX/XLSX generation, validation, save-location
approval, and supervisor integration (plan -> approve -> generate -> validate)."""

import pytest

import app.assistant_supervisor as sup_module
from app.artifacts.service import ArtifactService, artifact_store
from app.artifacts.spec import ArtifactPlanBuilder
from app.artifacts.validator import ArtifactValidator
from app.assistant_supervisor import AssistantSupervisor
from app.context_builder import build_turn_context
from app.turn_classifier import RESEARCH_THEN_EXECUTION_MODE, classify_turn

_SESSION = "artifact-session"


@pytest.fixture(autouse=True)
def _artifacts_dir(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "artifacts_dir", str(tmp_path / "artifacts"))
    artifact_store.clear(_SESSION)
    artifact_store.clear(None)
    yield
    artifact_store.clear(_SESSION)
    artifact_store.clear(None)


# ── Routing ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "prompt,kind",
    [
        ("Make me a PPT on renewable energy", "pptx"),
        ("Create a DOCX report on AI in healthcare", "docx"),
        ("Generate an XLSX sales tracker", "xlsx"),
        ("Build a presentation from the uploaded files", "pptx"),
    ],
)
def test_artifact_requests_route_with_type(prompt, kind):
    c = classify_turn(prompt)
    assert c.mode == RESEARCH_THEN_EXECUTION_MODE
    assert c.artifact_type == kind


def test_non_artifact_requests_have_no_artifact_type():
    assert classify_turn("what is python?").artifact_type is None
    assert classify_turn("git push").artifact_type is None
    assert classify_turn("summarize this document").artifact_type is None


# ── Real generation + validation ─────────────────────────────────────────────


def _build_and_generate(kind, goal):
    service = ArtifactService()
    pending, _msg = service.plan(goal, kind)  # no LLM -> deterministic fallback
    return service.generate(pending)


def test_pptx_generation_creates_valid_file():
    out = _build_and_generate("pptx", "Make a PPT on renewable energy")
    assert out["status"] == "completed"
    art = out["artifact"]
    assert art["type"] == "pptx"
    from pathlib import Path

    path = Path(art["path"])
    assert path.exists() and path.suffix == ".pptx"
    assert art["validation"]["valid"] is True
    assert art["validation"]["details"]["slides"] >= 1
    # Independently re-open it to prove it's a real presentation.
    from pptx import Presentation

    assert len(Presentation(str(path)).slides) >= 1


def test_docx_generation_creates_valid_file():
    out = _build_and_generate("docx", "Create a report on AI in healthcare")
    assert out["status"] == "completed"
    from pathlib import Path

    from docx import Document

    path = Path(out["artifact"]["path"])
    assert path.exists() and path.suffix == ".docx"
    assert out["artifact"]["validation"]["details"]["paragraphs"] >= 1
    assert len(Document(str(path)).paragraphs) >= 1


def test_xlsx_generation_creates_valid_file():
    out = _build_and_generate("xlsx", "Generate an XLSX sales tracker")
    assert out["status"] == "completed"
    from pathlib import Path

    from openpyxl import load_workbook

    path = Path(out["artifact"]["path"])
    assert path.exists() and path.suffix == ".xlsx"
    wb = load_workbook(str(path))
    assert wb.active.max_row >= 1


def test_metadata_carries_download_url_and_validation():
    out = _build_and_generate("pptx", "Make a PPT on space")
    art = out["artifact"]
    assert art["download_url"] == f"/artifacts/{art['filename']}"
    assert art["location"] == "workspace"
    assert art["validation"]["type_matches"] is True


# ── Validation honesty ───────────────────────────────────────────────────────


def test_validator_rejects_missing_file(tmp_path):
    res = ArtifactValidator().validate("pptx", tmp_path / "nope.pptx")
    assert res["valid"] is False
    assert "not written" in res["error"]


def test_validator_rejects_wrong_extension(tmp_path):
    bad = tmp_path / "thing.txt"
    bad.write_text("not a pptx")
    res = ArtifactValidator().validate("pptx", bad)
    assert res["valid"] is False
    assert "extension" in res["error"]


# ── Save-location approval ───────────────────────────────────────────────────


def test_default_save_location_needs_no_approval():
    service = ArtifactService()
    pending, _ = service.plan("Make a PPT on energy", "pptx")
    assert pending.delivery["location"] == "workspace"
    assert pending.delivery["requires_approval"] is False


def test_external_save_path_is_flagged_for_approval():
    service = ArtifactService()
    pending, message = service.plan(
        "Make a PPT on energy and save it to C:/Users/me/Desktop", "pptx"
    )
    assert pending.delivery["location"] == "external"
    assert pending.delivery["requires_approval"] is True
    assert "C:/Users/me/Desktop" in message


# ── Supervisor integration: plan -> approve -> validated completion ──────────


@pytest.mark.asyncio
async def test_supervisor_plans_then_generates_on_approval(monkeypatch):
    monkeypatch.setattr(
        sup_module.LLMClient, "generate", lambda self, system, prompt, temperature=0.2: ""
    )
    supervisor = AssistantSupervisor()

    # 1. Artifact request -> plan_ready (NOT completed, no fake artifact).
    ctx = build_turn_context("Make me a PPT on renewable energy", session_id=_SESSION, run_id="a1")
    plan = await supervisor._dispatch("Make me a PPT on renewable energy", ctx)
    assert plan["status"] == "plan_ready"
    assert plan["mode"] == RESEARCH_THEN_EXECUTION_MODE
    assert plan["artifacts"] == []
    assert plan["meta"]["approval_required"] is True
    assert artifact_store.get(_SESSION) is not None

    # 2. Approve -> real file generated, validated, completed with metadata.
    ctx2 = build_turn_context("approve", session_id=_SESSION, run_id="a2")
    done = await supervisor._dispatch("approve", ctx2)
    assert done["status"] == "completed"
    assert done["decision"] == "artifact_generated"
    assert len(done["artifacts"]) == 1
    from pathlib import Path

    assert Path(done["artifacts"][0]["path"]).exists()
    assert done["meta"]["artifact"]["validation"]["valid"] is True
    assert "Download:" in done["message"]
    assert artifact_store.get(_SESSION) is None  # consumed


@pytest.mark.asyncio
async def test_supervisor_reject_does_not_pretend_delivery():
    supervisor = AssistantSupervisor()
    ctx = build_turn_context("Create a DOCX report on climate", session_id=_SESSION, run_id="r1")
    await supervisor._dispatch("Create a DOCX report on climate", ctx)

    ctx2 = build_turn_context("reject", session_id=_SESSION, run_id="r2")
    res = await supervisor._dispatch("reject", ctx2)
    assert res["decision"] == "artifact_rejected"
    assert res["artifacts"] == []
    assert "didn't generate" in res["message"]
    assert artifact_store.get(_SESSION) is None


@pytest.mark.asyncio
async def test_generation_failure_is_honest(monkeypatch):
    """A generator that produces an empty file must fail, not fake success."""
    supervisor = AssistantSupervisor()
    ctx = build_turn_context("Make a PPT on energy", session_id=_SESSION, run_id="f1")
    await supervisor._dispatch("Make a PPT on energy", ctx)

    # Force the validator to see no slides (corrupt/empty generation).
    monkeypatch.setattr(
        ArtifactValidator,
        "validate",
        lambda self, kind, path: {"valid": False, "error": "presentation has no slides"},
    )
    ctx2 = build_turn_context("approve", session_id=_SESSION, run_id="f2")
    res = await supervisor._dispatch("approve", ctx2)
    assert res["status"] == "failed"
    assert res["decision"] == "artifact_generation_failed"
    assert res["artifacts"] == []
    assert "couldn't produce a valid" in res["message"]


# ── LLM content preparation feeds the generator ──────────────────────────────


def test_plan_builder_uses_llm_content_when_available():
    def _gen(system, prompt, temperature=0.4):
        return '{"slides": [{"title": "Solar", "bullets": ["Cheap", "Clean"]}, {"title": "Wind", "bullets": ["Scalable"]}]}'

    spec = ArtifactPlanBuilder().build("PPT on renewables", "pptx", generate=_gen)
    titles = [s.title for s in spec.slides]
    assert "Solar" in titles and "Wind" in titles
