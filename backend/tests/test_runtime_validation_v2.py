# File: backend/tests/test_runtime_validation_v2.py
"""Runtime validation v2: typed/ordered action planning, failure
classification, evidence-driven repair targeting, bounded retries, rich
evidence, and honest reporting."""

import pytest

from app.plan_executor import (
    ExecutablePlan,
    ExecutionReport,
    PlanStep,
    _repair_target,
    build_runtime_actions,
    classify_runtime_failure,
    execute_runtime_validation,
    render_runtime_report,
)


def _plan(paths):
    return ExecutablePlan(
        task_type="execution",
        goal="Build a service using FastAPI + FAISS",
        requires_plan_approval=True,
        project_dir="generated/p",
        steps=[
            PlanStep(i + 1, "write", "file_tool", "write_file", {"path": f"generated/p/{p}"})
            for i, p in enumerate(paths)
        ],
    )


def _report(paths):
    return ExecutionReport(
        files_written=[{"path": f"generated/p/{p}", "bytes": 10} for p in paths]
    )


# ── Action planning: typed, ordered, no duplicates ───────────────────────────


def test_python_project_actions_ordered_install_compile_import():
    paths = ["requirements.txt", "app/main.py", "app/service.py"]
    actions = build_runtime_actions(_plan(paths), _report(paths))
    types = [a["type"] for a in actions]
    assert types == ["install", "smoke_test", "import_smoke"]
    assert "pip install" in actions[0]["payload"]["command"]
    assert "compileall" in actions[1]["payload"]["command"]
    # Import smoke targets the entry module with the project on sys.path.
    assert "app.main" in actions[2]["payload"]["command"]
    assert "generated/p" in actions[2]["payload"]["command"]
    # ids are sequential, no duplicate commands.
    assert [a["id"] for a in actions] == [1, 2, 3]
    commands = [a["payload"]["command"] for a in actions]
    assert len(commands) == len(set(commands))


def test_js_project_actions_install_then_build():
    paths = ["package.json", "src/index.ts"]
    actions = build_runtime_actions(_plan(paths), _report(paths))
    types = [a["type"] for a in actions]
    assert types == ["install", "build"]
    assert "npm install" in actions[0]["payload"]["command"]
    assert "npm run build" in actions[1]["payload"]["command"]


def test_config_only_project_emits_no_nonsensical_actions():
    paths = ["config.json", "README.md"]
    actions = build_runtime_actions(_plan(paths), _report(paths))
    assert actions == []  # nothing runnable -> nothing to pretend to validate


# ── Failure classification ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "action_type,output,expected",
    [
        ("install", "ERROR: No matching distribution", "dependency_install_failed"),
        ("smoke_test", 'File "x.py"\nSyntaxError: invalid', "compile_failed"),
        ("import_smoke", "ModuleNotFoundError: No module named 'faiss'", "import_failed"),
        ("import_smoke", "RuntimeError: boom", "startup_failed"),
        ("build", "error TS2304: Cannot find name", "build_failed"),
        ("healthcheck", "connection refused", "healthcheck_failed"),
    ],
)
def test_failure_classification(action_type, output, expected):
    assert classify_runtime_failure(action_type, output) == expected


# ── Repair targeting ─────────────────────────────────────────────────────────

_FILES = ["generated/p/app/main.py", "generated/p/app/service.py", "generated/p/requirements.txt"]


def test_traceback_path_targets_the_failing_file():
    out = 'Traceback...\n  File "generated/p/app/service.py", line 3\nSyntaxError'
    assert _repair_target(out, _FILES) == "generated/p/app/service.py"


def test_missing_local_module_targets_its_generated_file():
    out = "ModuleNotFoundError: No module named 'service'"
    assert _repair_target(out, _FILES) == "generated/p/app/service.py"


def test_missing_external_module_targets_requirements():
    out = "ModuleNotFoundError: No module named 'faiss'"
    assert _repair_target(out, _FILES) == "generated/p/requirements.txt"


def test_install_failure_repairs_requirements_not_code():
    paths = ["requirements.txt", "app/main.py"]
    plan, report = _plan(paths), _report(paths)
    actions = [a for a in build_runtime_actions(plan, report) if a["type"] == "install"]
    calls = {"n": 0}
    writes = []

    def _runner(tool, action, payload=None):
        if tool == "file_tool":
            writes.append(payload["path"])
            return {"success": True, "output": ""}
        calls["n"] += 1
        if calls["n"] == 1:
            return {"success": False, "output": "ERROR: No matching distribution for fastapy"}
        return {"success": True, "output": "installed"}

    evidence = execute_runtime_validation(
        plan, actions, generate=lambda **k: "fastapi\nfaiss-cpu\n", run_tool=_runner
    )
    assert evidence["status"] == "completed"
    assert writes == ["generated/p/requirements.txt"]  # never blind code regen
    assert evidence["repairs"][0]["classification"] == "dependency_install_failed"


# ── Evidence richness + honest reporting ─────────────────────────────────────


def test_evidence_carries_classification_summary_and_retry_count():
    paths = ["app/main.py"]
    plan, report = _plan(paths), _report(paths)
    actions = build_runtime_actions(plan, report)

    def _runner(tool, action, payload=None):
        if tool == "file_tool":
            return {"success": True, "output": ""}
        return {"success": False, "output": 'File "main.py"\nSyntaxError: bad'}

    evidence = execute_runtime_validation(
        plan, actions, generate=lambda **k: "x = 1\n", run_tool=_runner
    )
    assert evidence["status"] == "failed"
    assert evidence["failure_class"] == "compile_failed"
    assert evidence["retry_count"] == 1  # bounded
    failed_entries = [e for e in evidence["commands"] if not e["success"]]
    assert all(e["classification"] == "compile_failed" for e in failed_entries)
    summary = evidence["validation_summary"]
    assert summary["planned"] == len(actions)
    assert summary["failed"] >= 1


def test_success_report_is_clean_and_specific():
    evidence = {
        "status": "completed",
        "commands": [
            {"command": "pip install -r r.txt", "type": "install", "success": True, "output": "long noisy pip output " * 50},
            {"command": "python -m compileall", "type": "smoke_test", "success": True, "output": ""},
        ],
        "repairs": [],
        "retry_count": 0,
    }
    report = render_runtime_report(evidence)
    assert "dependency install" in report
    assert "compile check" in report
    assert "Next" in report
    # No raw log dumps in the main answer.
    assert "noisy pip output" not in report


def test_failure_report_is_honest_about_repair_and_followup():
    evidence = {
        "status": "failed",
        "failure_class": "import_failed",
        "commands": [
            {"command": "python -c import", "type": "import_smoke", "success": False,
             "output": "ModuleNotFoundError: No module named 'faiss'", "classification": "import_failed"},
        ],
        "repairs": [{"path": "generated/p/requirements.txt", "classification": "import_failed", "error": "..."}],
        "retry_count": 1,
    }
    report = render_runtime_report(evidence)
    assert "import_failed" in report
    assert "repair attempted" in report
    assert "requirements.txt" in report
    assert "Manual follow-up" in report
    # No fake success language.
    assert "passed" not in report.lower().split("failed")[0]


def test_failure_without_repair_target_says_no_blind_retry():
    evidence = {
        "status": "failed",
        "failure_class": "unrecoverable_runtime_failure",
        "commands": [{"command": "x", "type": "smoke_test", "success": False, "output": "???",
                      "classification": "unrecoverable_runtime_failure"}],
        "repairs": [],
        "retry_count": 0,
    }
    report = render_runtime_report(evidence)
    assert "no safe repair target" in report
