# File: backend/tests/test_startup_validation.py
"""Startup / health validation: boot-target detection, bounded probe with
guaranteed teardown, failure classification, evidence-driven repair, and honest
reporting. No real processes are spawned — launcher/prober are injected."""

import pytest

from app.plan_executor import (
    ExecutablePlan,
    ExecutionReport,
    PlanStep,
    build_runtime_actions,
    execute_runtime_validation,
    render_runtime_report,
)
from app.startup_validator import (
    BootTarget,
    detect_boot_target,
    run_startup_probe,
)

_FASTAPI = (
    "from fastapi import FastAPI\n"
    "app = FastAPI()\n"
    "@app.get('/health')\n"
    "def health():\n    return {'ok': True}\n"
)


def _plan(paths):
    return ExecutablePlan(
        task_type="execution",
        goal="Build a FastAPI service",
        requires_plan_approval=True,
        project_dir="generated/svc",
        steps=[
            PlanStep(i + 1, "write", "file_tool", "write_file", {"path": f"generated/svc/{p}"})
            for i, p in enumerate(paths)
        ],
    )


# ── Detection ────────────────────────────────────────────────────────────────


def test_detects_fastapi_boot_target():
    files = ["generated/svc/app/main.py", "generated/svc/requirements.txt"]
    target = detect_boot_target(
        "generated/svc", files, read_file=lambda p: {"success": True, "content": _FASTAPI}
    )
    assert target is not None
    assert target.framework == "fastapi"
    assert target.entry_module == "app.main:app"
    assert target.health_path == "/health"
    assert "uvicorn" in " ".join(target.command)


def test_non_runnable_output_is_not_boot_tested():
    files = ["generated/svc/config.json", "generated/svc/README.md"]
    assert detect_boot_target("generated/svc", files, read_file=lambda p: {"success": True, "content": "{}"}) is None
    # A plain script with no app instance is not a service.
    files2 = ["generated/svc/main.py"]
    assert detect_boot_target(
        "generated/svc", files2, read_file=lambda p: {"success": True, "content": "print('hi')\n"}
    ) is None


def test_health_route_defaults_to_root_when_absent():
    target = detect_boot_target(
        "generated/svc",
        ["generated/svc/main.py"],
        read_file=lambda p: {"success": True, "content": "from fastapi import FastAPI\napp = FastAPI()\n"},
    )
    assert target is not None
    assert target.health_path == "/"


# ── Bounded probe + guaranteed teardown ──────────────────────────────────────


class _FakeProc:
    def __init__(self, alive=True, exit_code=None, output=""):
        self._alive = alive
        self._exit = exit_code
        self.returncode = exit_code
        self.stdout = type("S", (), {"read": lambda self: output})()
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self._alive else self._exit

    def terminate(self):
        self.terminated = True
        self._alive = False

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


def _target():
    return BootTarget(
        framework="fastapi",
        project_dir="generated/svc",
        entry_file="generated/svc/main.py",
        entry_module="main:app",
        app_attr="app",
        health_path="/health",
        command=["python", "-m", "uvicorn", "main:app", "--port", "{port}"],
    )


def test_successful_startup_is_recorded_and_torn_down():
    proc = _FakeProc(alive=True)
    ev = run_startup_probe(
        _target(),
        launcher=lambda cmd, cwd, port: proc,
        prober=lambda url, timeout=1.0: (True, 200),
    )
    assert ev["attempted"] is True
    assert ev["success"] is True
    assert ev["probe_status"] == 200
    assert ev["teardown"] in ("terminated", "killed")  # always cleaned up
    assert proc.terminated is True


def test_startup_timeout_is_classified():
    proc = _FakeProc(alive=True)
    ev = run_startup_probe(
        _target(),
        ready_timeout=0.3,
        poll_interval=0.05,
        launcher=lambda cmd, cwd, port: proc,
        prober=lambda url, timeout=1.0: (False, None),  # never ready
    )
    assert ev["success"] is False
    assert ev["classification"] == "startup_timeout"
    assert ev["teardown"] in ("terminated", "killed")


def test_process_crash_is_classified():
    proc = _FakeProc(alive=False, exit_code=1, output="Traceback...\nRuntimeError: boom")
    ev = run_startup_probe(
        _target(),
        launcher=lambda cmd, cwd, port: proc,
        prober=lambda url, timeout=1.0: (False, None),
    )
    assert ev["success"] is False
    assert ev["classification"] == "process_crashed"
    assert ev["exit_code"] == 1


def test_missing_dependency_crash_is_classified():
    proc = _FakeProc(alive=False, exit_code=1, output="ModuleNotFoundError: No module named 'faiss'")
    ev = run_startup_probe(
        _target(),
        launcher=lambda cmd, cwd, port: proc,
        prober=lambda url, timeout=1.0: (False, None),
    )
    assert ev["classification"] == "missing_runtime_dependency"


def test_launch_failure_is_classified_and_safe():
    def _boom(cmd, cwd, port):
        raise FileNotFoundError("python not found")

    ev = run_startup_probe(_target(), launcher=_boom, prober=lambda u, timeout=1.0: (False, None))
    assert ev["classification"] == "startup_command_failed"
    assert ev["teardown"] == "no_process"  # nothing to tear down


def test_disabled_boot_validation_is_honest(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "enable_boot_validation", False)
    ev = run_startup_probe(_target(), launcher=lambda *a: None, prober=lambda *a, **k: (True, 200))
    assert ev["attempted"] is False
    assert "disabled" in ev["reason"]


# ── Integration: startup probe inside runtime validation ─────────────────────


def _startup_action():
    return {
        "id": 1,
        "type": "startup_probe",
        "tool": "startup_validator",
        "action": "boot_and_probe",
        "payload": {"boot": _target().to_dict()},
        "status": "pending",
    }


def test_runtime_validation_records_startup_success():
    plan = _plan(["main.py"])
    evidence = execute_runtime_validation(
        plan,
        [_startup_action()],
        generate=lambda **k: "x",
        startup_runner=lambda target, on_event=None: {"attempted": True, "success": True, "probe_status": 200, "framework": "fastapi", "health_url": "http://x/health", "teardown": "terminated"},
    )
    assert evidence["status"] == "completed"
    assert evidence["startup"]["success"] is True
    report = render_runtime_report(evidence)
    assert "Startup check passed" in report
    assert "responded 200" in report


def test_runtime_validation_repairs_then_succeeds_on_startup():
    plan = _plan(["main.py"])
    calls = {"n": 0}

    def _runner(target, on_event=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"attempted": True, "success": False, "classification": "process_crashed",
                    "output": 'File "generated/svc/main.py"\nRuntimeError', "teardown": "terminated"}
        return {"attempted": True, "success": True, "probe_status": 200, "teardown": "terminated"}

    evidence = execute_runtime_validation(
        plan, [_startup_action()], generate=lambda **k: "fixed\n",
        run_tool=lambda t, a, p=None: {"success": True, "output": ""},
        startup_runner=_runner,
    )
    assert evidence["status"] == "completed"
    assert evidence["startup"]["success"] is True
    assert len(evidence["repairs"]) == 1
    assert calls["n"] == 2  # initial + exactly one retry (bounded)


def test_runtime_validation_startup_failure_is_honest():
    plan = _plan(["main.py"])

    def _runner(target, on_event=None):
        return {"attempted": True, "success": False, "classification": "startup_timeout",
                "output": "never became ready", "framework": "fastapi",
                "health_url": "http://x/health", "teardown": "killed"}

    evidence = execute_runtime_validation(
        plan, [_startup_action()], generate=lambda **k: "x",
        run_tool=lambda t, a, p=None: {"success": True, "output": ""},
        startup_runner=_runner,
    )
    assert evidence["status"] == "failed"
    assert evidence["failure_class"] == "startup_timeout"
    report = render_runtime_report(evidence)
    assert "startup_timeout" in report
    assert "teardown: killed" in report
    assert "Startup check passed" not in report  # no fake success


def test_build_runtime_actions_appends_startup_for_real_service(monkeypatch, tmp_path):
    from tools.filesystem.file_tool import FileTool

    monkeypatch.setattr(FileTool, "_workspace_root", staticmethod(lambda: tmp_path))
    # Write a real FastAPI app so detection (which reads the file) fires.
    app_dir = tmp_path / "generated" / "svc"
    app_dir.mkdir(parents=True)
    (app_dir / "main.py").write_text(_FASTAPI, encoding="utf-8")

    plan = _plan(["main.py"])
    report = ExecutionReport(files_written=[{"path": "generated/svc/main.py", "bytes": 10}])
    actions = build_runtime_actions(plan, report)
    types = [a["type"] for a in actions]
    assert "startup_probe" in types
    startup = next(a for a in actions if a["type"] == "startup_probe")
    assert startup["payload"]["boot"]["framework"] == "fastapi"


def test_non_service_skips_startup_in_report():
    # No startup key at all -> report says startup was skipped honestly.
    evidence = {"status": "completed", "commands": [{"command": "x", "type": "install", "success": True, "output": ""}], "repairs": [], "retry_count": 0}
    report = render_runtime_report(evidence)
    assert "Startup check skipped" in report
    assert "Startup check passed" not in report
