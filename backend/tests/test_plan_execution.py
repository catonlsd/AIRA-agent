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


# ── Runtime self-check (install/run + diagnose + repair) ─────────────────────


def _runtime_plan():
    return _plan([_write_step(1, "main.py"), _validate_step(2)])


def test_runtime_actions_built_from_evidence():
    from app.plan_executor import ExecutionReport, build_runtime_actions

    plan = _runtime_plan()
    report = ExecutionReport(
        files_written=[
            {"path": "generated/test_project/main.py", "bytes": 10},
            {"path": "generated/test_project/requirements.txt", "bytes": 10},
        ]
    )
    actions = build_runtime_actions(plan, report)
    commands = [a["payload"]["command"] for a in actions]
    assert any("pip install -r" in c for c in commands)
    assert any("compileall" in c for c in commands)
    for action in actions:
        assert action["tool"] == "shell_tool"
        assert action["status"] == "pending"


def test_runtime_validation_repairs_failing_file(_sandbox):
    from app.plan_executor import build_runtime_actions, execute_runtime_validation, ExecutionReport

    plan = _runtime_plan()
    report = ExecutionReport(files_written=[{"path": "generated/test_project/main.py", "bytes": 5}])
    actions = build_runtime_actions(plan, report)

    calls = {"n": 0}

    def _runner(tool, action, payload=None):
        if tool == "file_tool":
            return {"success": True, "output": ""}
        calls["n"] += 1
        if calls["n"] == 1:
            return {"success": False, "output": 'File "main.py", line 3\nSyntaxError'}
        return {"success": True, "output": "compiled"}

    evidence = execute_runtime_validation(
        plan, actions, generate=lambda **k: "def fixed():\n    return 1\n", run_tool=_runner
    )

    assert evidence["status"] == "completed"
    assert len(evidence["repairs"]) == 1
    assert evidence["repairs"][0]["path"].endswith("main.py")
    # The failed run and the successful retry are both recorded as evidence.
    statuses = [e["success"] for e in evidence["commands"]]
    assert statuses[0] is False and all(statuses[1:])
    assert evidence["retry_count"] == 1


def test_runtime_validation_fails_honestly(_sandbox):
    from app.plan_executor import build_runtime_actions, execute_runtime_validation, ExecutionReport

    plan = _runtime_plan()
    report = ExecutionReport(files_written=[{"path": "generated/test_project/main.py", "bytes": 5}])
    actions = build_runtime_actions(plan, report)

    def _runner(tool, action, payload=None):
        if tool == "file_tool":
            return {"success": True, "output": ""}
        return {"success": False, "output": 'File "main.py": persistent failure'}

    evidence = execute_runtime_validation(
        plan, actions, generate=lambda **k: "x = 1\n", run_tool=_runner
    )
    assert evidence["status"] == "failed"
    assert evidence["error"]


# ── Top-level mode means routed intent, never prompt shape ───────────────────


def test_single_run_normalizer_uses_routed_mode():
    from app.routes.aira_x import _build_clean_single_run_response

    plain = _build_clean_single_run_response(
        {"final_answer": "done", "status": "completed"}
    )
    assert plain["mode"] == "execution"
    assert plain["meta"]["prompt_shape"] == "single"

    resumed = _build_clean_single_run_response(
        {"final_answer": "done", "approval_resolution": {"status": "approved"}}
    )
    assert resumed["mode"] == "approval_resume"

    explicit = _build_clean_single_run_response(
        {"final_answer": "done", "mode": "web_research"}
    )
    assert explicit["mode"] == "web_research"

    # "single_question" must never appear as a top-level mode.
    for record in (plain, resumed, explicit):
        assert record["mode"] != "single_question"
