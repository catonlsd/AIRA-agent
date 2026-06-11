# File: backend/tests/test_plan_execution.py
"""The plan executor: structured plans, real tool execution, validation,
repair/retry, and evidence-gated completion."""

import pytest

from app.plan_executor import (
    ExecutablePlan,
    PlanStep,
    _parse_manifest,
    build_executable_plan,
    design_file_manifest,
    execute_plan,
    project_slug,
    render_execution_report,
)


@pytest.fixture(autouse=True)
def _sandbox(monkeypatch, tmp_path):
    """All file-tool operations land in a temp workspace."""
    from tools.filesystem.file_tool import FileTool

    monkeypatch.setattr(FileTool, "_workspace_root", staticmethod(lambda: tmp_path))
    return tmp_path


def _plan(steps):
    return ExecutablePlan(
        task_type="execution",
        goal="Build a RAG system using FastAPI + FAISS. Backend implementation.",
        requires_plan_approval=True,
        project_dir="generated/test_project",
        steps=steps,
    )


def _write_step(step_id, path, purpose="test file"):
    return PlanStep(
        id=step_id,
        type="write",
        tool="file_tool",
        action="write_file",
        payload={"path": f"generated/test_project/{path}", "purpose": purpose},
        description=f"Create {path}",
    )


def _validate_step(step_id):
    return PlanStep(
        id=step_id,
        type="validate",
        tool="file_tool",
        action="list_files",
        payload={"path": "generated/test_project"},
        description="Validate files",
    )


# ── Structured plan format ───────────────────────────────────────────────────


def test_build_executable_plan_is_structured():
    def _gen(system, prompt, temperature=0.0):
        return '[{"path": "app/main.py", "purpose": "entrypoint"}, {"path": "README.md", "purpose": "docs"}]'

    plan = build_executable_plan(
        "Build me a RAG system",
        "Build a RAG system using FastAPI + FAISS",
        {"selected_output_format": "Backend implementation"},
        generate=_gen,
    )

    data = plan.to_dict()
    assert data["task_type"] == "execution"
    assert data["requires_plan_approval"] is True
    assert data["project_dir"] == "generated/build_me_a_rag_system"
    # Write steps carry tool/action/payload; the last step validates.
    write_steps = [s for s in data["steps"] if s["type"] == "write"]
    assert len(write_steps) == 2
    for step in write_steps:
        assert step["tool"] == "file_tool"
        assert step["action"] == "write_file"
        assert step["payload"]["path"].startswith("generated/build_me_a_rag_system/")
    assert data["steps"][-1]["type"] == "validate"
    # Round-trips cleanly.
    assert ExecutablePlan.from_dict(data).to_dict() == data


def test_manifest_parses_json_and_rejects_traversal():
    parsed = _parse_manifest('Here you go: [{"path": "a.py", "purpose": "x"}, {"path": "../evil", "purpose": "y"}]')
    assert parsed == [{"path": "a.py", "purpose": "x"}]
    assert _parse_manifest("no json here") is None


def test_manifest_falls_back_when_llm_unusable():
    def _bad_gen(system, prompt, temperature=0.0):
        return "I cannot answer that."

    manifest = design_file_manifest(
        "goal", {"selected_output_format": "Backend implementation"}, _bad_gen
    )
    paths = [entry["path"] for entry in manifest]
    assert "app/main.py" in paths
    assert not any("frontend" in path for path in paths)

    full = design_file_manifest(
        "goal", {"selected_output_format": "Full backend + frontend structure"}, _bad_gen
    )
    assert any("frontend" in entry["path"] for entry in full)


def test_project_slug_is_safe():
    assert project_slug("Build me a RAG system!") == "build_me_a_rag_system"


# ── Real execution with evidence ─────────────────────────────────────────────


def test_execute_plan_writes_real_files(_sandbox):
    plan = _plan([_write_step(1, "main.py"), _write_step(2, "README.md"), _validate_step(3)])

    def _gen(system, prompt, temperature=0.2):
        if "main.py" in prompt:
            return "print('rag service using FAISS')\n"
        return "# README\nSetup instructions.\n"

    report = execute_plan(plan, generate=_gen)

    assert report.status == "completed"
    assert len(report.files_written) == 2
    # The files genuinely exist on disk.
    assert (_sandbox / "generated/test_project/main.py").exists()
    assert (_sandbox / "generated/test_project/README.md").exists()
    assert report.validation["verified_files"] == 2
    assert report.validation["missing_or_invalid"] == []
    # Evidence appears in the rendered report.
    message = render_execution_report(plan, report)
    assert "main.py" in message and "README.md" in message
    assert "Validation: 2/2" in message


def test_repair_loop_fixes_invalid_python(_sandbox):
    plan = _plan([_write_step(1, "main.py"), _validate_step(2)])
    calls = {"n": 0}

    def _gen(system, prompt, temperature=0.2):
        calls["n"] += 1
        if calls["n"] == 1:
            return "def broken(:\n"  # syntax error -> triggers repair
        return "def fixed():\n    return 'ok'\n"

    report = execute_plan(plan, generate=_gen)

    assert report.status == "completed"
    assert len(report.repairs) == 1
    assert "syntax" in report.repairs[0]["error"].lower()
    assert (_sandbox / "generated/test_project/main.py").read_text().startswith("def fixed")
    message = render_execution_report(plan, report)
    assert "Repairs (1)" in message


def test_honest_failure_when_generation_keeps_failing(_sandbox):
    plan = _plan([_write_step(1, "main.py"), _validate_step(2)])

    def _gen(system, prompt, temperature=0.2):
        return "still ( broken python\n"

    report = execute_plan(plan, generate=_gen)

    assert report.status == "failed"
    assert report.error
    assert "syntax" in report.error.lower()
    message = render_execution_report(plan, report)
    assert "Execution failed" in message
    assert "Execution complete" not in message


def test_failure_when_llm_unavailable(_sandbox):
    plan = _plan([_write_step(1, "main.py"), _validate_step(2)])

    def _gen(system, prompt, temperature=0.2):
        raise RuntimeError("no provider configured")

    report = execute_plan(plan, generate=_gen)
    assert report.status == "failed"
    assert "generation failed" in report.error


def test_unsafe_payload_is_blocked(_sandbox):
    step = PlanStep(
        id=1,
        type="write",
        tool="file_tool",
        action="write_file",
        payload={"path": "../outside.py", "purpose": "escape"},
        description="escape attempt",
    )
    report = execute_plan(_plan([step]), generate=lambda **k: "x = 1\n")
    assert report.status == "failed"
    assert "unsafe" in report.error


def test_disallowed_action_is_blocked(_sandbox):
    step = PlanStep(
        id=1,
        type="write",
        tool="file_tool",
        action="delete_everything",
        payload={"path": "generated/test_project/x"},
        description="bogus action",
    )
    report = execute_plan(_plan([step]), generate=lambda **k: "x")
    assert report.status == "failed"
    assert "not allowed" in report.error


def test_no_completion_without_files(_sandbox):
    # A plan with only a validation step has no evidence to complete on.
    report = execute_plan(_plan([_validate_step(1)]), generate=lambda **k: "x")
    assert report.status == "failed"
    assert "no files were written" in (report.error or "")
