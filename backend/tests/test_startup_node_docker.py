# File: backend/tests/test_startup_node_docker.py
"""Broader startup verification: Node/JS/TS + Next.js boot-target detection,
bounded Node/Next startup probes with guaranteed teardown and framework-aware
classification, an honest Docker/compose skip path, evidence-driven repair
targeting, and trustworthy reporting. No real processes/containers are spawned —
launcher/prober are injected and Docker is gated off by default."""

import json

import pytest

from app.plan_executor import (
    ExecutablePlan,
    PlanStep,
    _startup_repair_target,
    build_runtime_actions,
    render_runtime_report,
)
from app.startup_validator import (
    BootTarget,
    detect_boot_target,
    run_startup_probe,
)


def _pkg(*, start=None, deps=None, dev=None, scripts=None):
    body = {"name": "svc", "version": "1.0.0"}
    s = dict(scripts or {})
    if start is not None:
        s["start"] = start
    if s:
        body["scripts"] = s
    if deps:
        body["dependencies"] = deps
    if dev:
        body["devDependencies"] = dev
    return json.dumps(body)


def _reader(mapping):
    """A read_file stub: path-suffix -> content (or missing -> failure)."""

    def _read(path):
        for suffix, content in mapping.items():
            if path.endswith(suffix):
                return {"success": True, "content": content}
        return {"success": False}

    return _read


# ── Detection: Node / Next / Docker ──────────────────────────────────────────


def test_detects_express_node_service():
    files = ["generated/svc/package.json", "generated/svc/server.js"]
    target = detect_boot_target(
        "generated/svc",
        files,
        read_file=_reader(
            {
                "package.json": _pkg(start="node server.js", deps={"express": "^4"}),
                "server.js": "app.get('/health', (req,res)=>res.send('ok'))\n",
            }
        ),
    )
    assert target is not None
    assert target.framework == "node"
    assert target.health_path == "/health"
    assert "npm" in target.command and "start" in target.command


def test_node_service_without_start_uses_server_entry():
    files = ["generated/svc/package.json", "generated/svc/index.js"]
    target = detect_boot_target(
        "generated/svc",
        files,
        read_file=_reader(
            {
                "package.json": _pkg(deps={"fastify": "^4"}),  # server dep, no start script
                "index.js": "const app = require('fastify')()\n",
            }
        ),
    )
    assert target is not None
    assert target.framework == "node"
    assert target.command[:1] == ["node"]


def test_detects_next_app():
    files = ["generated/web/package.json", "generated/web/next.config.js"]
    target = detect_boot_target(
        "generated/web",
        files,
        read_file=_reader({"package.json": _pkg(start="next start", deps={"next": "^14", "react": "^18"})}),
    )
    assert target is not None
    assert target.framework == "next"
    assert target.command == ["npm", "run", "start", "--prefix", "generated/web"]


def test_ambiguous_js_library_skips_honestly():
    # A package.json with no start script and no server dependency is a library
    # / tooling package, not a runnable service → skip honestly (None).
    files = ["generated/lib/package.json", "generated/lib/index.js"]
    target = detect_boot_target(
        "generated/lib",
        files,
        read_file=_reader({"package.json": _pkg(deps={"lodash": "^4"}, scripts={"build": "tsc"})}),
    )
    assert target is None


def test_next_without_start_script_skips_honestly():
    files = ["generated/web/package.json"]
    target = detect_boot_target(
        "generated/web",
        files,
        read_file=_reader({"package.json": _pkg(deps={"next": "^14"}, scripts={"dev": "next dev"})}),
    )
    assert target is None  # no bounded production-start path


def test_unparsable_package_json_skips_honestly():
    files = ["generated/svc/package.json"]
    target = detect_boot_target(
        "generated/svc", files, read_file=_reader({"package.json": "{not valid json"})
    )
    assert target is None


def test_detects_docker_compose_target():
    files = ["generated/svc/docker-compose.yml", "generated/svc/Dockerfile"]
    target = detect_boot_target("generated/svc", files, read_file=lambda p: {"success": True, "content": ""})
    assert target is not None
    assert target.framework == "docker"
    assert target.entry_file.endswith("docker-compose.yml")
    assert target.command == []


def test_python_takes_precedence_over_node():
    # A polyglot output with both a Python web app and a package.json prefers the
    # cheaper Python boot target.
    files = ["generated/svc/app/main.py", "generated/svc/package.json"]
    target = detect_boot_target(
        "generated/svc",
        files,
        read_file=_reader(
            {
                "main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
                "package.json": _pkg(start="node x.js", deps={"express": "^4"}),
            }
        ),
    )
    assert target.framework == "fastapi"


# ── Planning: build + startup_probe actions ──────────────────────────────────


def test_node_project_on_disk_gets_build_and_startup_probe(tmp_path, monkeypatch):
    from tools.filesystem.file_tool import FileTool

    monkeypatch.setattr(FileTool, "_workspace_root", staticmethod(lambda: tmp_path))
    (tmp_path / "package.json").write_text(_pkg(start="node server.js", deps={"express": "^4"}))
    (tmp_path / "server.js").write_text("app.get('/health',()=>{})\n")
    paths = [str(tmp_path / "package.json"), str(tmp_path / "server.js")]
    plan = ExecutablePlan(
        task_type="execution",
        goal="Build an Express API",
        requires_plan_approval=True,
        project_dir=str(tmp_path),
        steps=[PlanStep(1, "write", "file_tool", "write_file", {"path": p}) for p in paths],
    )
    report = type("R", (), {"files_written": [{"path": p} for p in paths]})()
    actions = build_runtime_actions(plan, report)
    types = [a["type"] for a in actions]
    assert "install" in types and "build" in types
    assert types[-1] == "startup_probe"
    assert actions[-1]["payload"]["boot"]["framework"] == "node"


# ── Node/Next bounded probe + classification ─────────────────────────────────


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


def _node_target(framework="node"):
    return BootTarget(
        framework=framework,
        project_dir="generated/svc",
        entry_file="generated/svc/server.js",
        entry_module="",
        app_attr="",
        health_path="/health",
        command=["npm", "run", "start", "--prefix", "generated/svc"],
    )


def test_node_startup_success_recorded_and_torn_down():
    proc = _FakeProc(alive=True)
    ev = run_startup_probe(
        _node_target(),
        launcher=lambda cmd, cwd, port: proc,
        prober=lambda url, timeout=1.0: (True, 200),
    )
    assert ev["success"] is True
    assert ev["framework"] == "node"
    assert ev["teardown"] in ("terminated", "killed")
    assert proc.terminated is True  # reliable cleanup


def test_node_startup_timeout_classified():
    proc = _FakeProc(alive=True)
    ev = run_startup_probe(
        _node_target(),
        ready_timeout=0.2,
        poll_interval=0.05,
        launcher=lambda cmd, cwd, port: proc,
        prober=lambda url, timeout=1.0: (False, None),
    )
    assert ev["classification"] == "node_startup_timeout"
    assert ev["teardown"] in ("terminated", "killed")


def test_node_startup_crash_classified():
    proc = _FakeProc(alive=False, exit_code=1, output="ReferenceError: x is not defined")
    ev = run_startup_probe(
        _node_target(),
        launcher=lambda cmd, cwd, port: proc,
        prober=lambda url, timeout=1.0: (False, None),
    )
    assert ev["classification"] == "node_startup_failed"
    assert ev["exit_code"] == 1


def test_node_missing_module_crash_classified():
    proc = _FakeProc(alive=False, exit_code=1, output="Error: Cannot find module 'express'")
    ev = run_startup_probe(
        _node_target(),
        launcher=lambda cmd, cwd, port: proc,
        prober=lambda url, timeout=1.0: (False, None),
    )
    assert ev["classification"] == "missing_runtime_dependency"


def test_node_port_bind_crash_classified():
    proc = _FakeProc(alive=False, exit_code=1, output="Error: listen EADDRINUSE: address already in use")
    ev = run_startup_probe(
        _node_target(),
        launcher=lambda cmd, cwd, port: proc,
        prober=lambda url, timeout=1.0: (False, None),
    )
    assert ev["classification"] == "port_bind_failed"


def test_next_startup_timeout_classified():
    proc = _FakeProc(alive=True)
    ev = run_startup_probe(
        _node_target("next"),
        ready_timeout=0.2,
        poll_interval=0.05,
        launcher=lambda cmd, cwd, port: proc,
        prober=lambda url, timeout=1.0: (False, None),
    )
    assert ev["classification"] == "next_startup_timeout"


def test_teardown_runs_even_when_launcher_fails():
    ev = run_startup_probe(
        _node_target(),
        launcher=lambda cmd, cwd, port: (_ for _ in ()).throw(FileNotFoundError()),
        prober=lambda url, timeout=1.0: (True, 200),
    )
    assert ev["success"] is False
    assert ev["classification"] == "startup_command_failed"
    assert ev["teardown"] == "no_process"  # nothing to clean up, reported honestly


# ── Docker hook: honest, gated, bounded ──────────────────────────────────────


def _docker_target():
    return BootTarget(
        framework="docker",
        project_dir="generated/svc",
        entry_file="generated/svc/docker-compose.yml",
        entry_module="",
        app_attr="",
        health_path="/",
        command=[],
    )


def test_docker_validation_skipped_when_disabled(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "enable_docker_validation", False)
    ev = run_startup_probe(_docker_target())
    assert ev["attempted"] is False
    assert ev["framework"] == "docker"
    assert "not enabled" in ev["reason"]
    assert "classification" not in ev  # a skip is not a failure


def test_docker_unavailable_reported_when_enabled_but_absent(monkeypatch):
    from app.core.config import settings
    import app.startup_validator as sv

    monkeypatch.setattr(settings, "enable_docker_validation", True)
    monkeypatch.setattr(sv.shutil, "which", lambda name: None)
    ev = run_startup_probe(_docker_target())
    assert ev["classification"] == "docker_unavailable"
    assert "not available" in ev["reason"]


def test_docker_available_does_not_fake_a_boot(monkeypatch):
    from app.core.config import settings
    import app.startup_validator as sv

    monkeypatch.setattr(settings, "enable_docker_validation", True)
    monkeypatch.setattr(sv.shutil, "which", lambda name: "/usr/bin/docker")
    ev = run_startup_probe(_docker_target())
    # Honest: detected + available, but no fake "validated" success.
    assert ev.get("success") is not True
    assert ev["attempted"] is False
    assert ev["docker_available"] is True


# ── Evidence-driven repair targeting ─────────────────────────────────────────


def test_missing_dependency_targets_package_json_for_node():
    files = ["generated/svc/package.json", "generated/svc/server.js"]
    target = _startup_repair_target("missing_runtime_dependency", "Cannot find module 'express'", files, "generated/svc/server.js", "node")
    assert target.endswith("package.json")


def test_node_crash_targets_entry_file():
    files = ["generated/svc/package.json", "generated/svc/server.js"]
    target = _startup_repair_target("node_startup_failed", "ReferenceError", files, "generated/svc/server.js", "node")
    assert target == "generated/svc/server.js"


def test_docker_failure_targets_compose_file():
    files = ["generated/svc/docker-compose.yml", "generated/svc/Dockerfile"]
    target = _startup_repair_target("docker_startup_failed", "", files, "generated/svc/docker-compose.yml", "docker")
    assert target.endswith("docker-compose.yml")


def test_repair_target_traceback_path_wins():
    files = ["generated/svc/package.json", "generated/svc/routes.js"]
    target = _startup_repair_target(
        "node_startup_failed",
        "    at Object.<anonymous> (generated/svc/routes.js:12:5)",
        files,
        "generated/svc/server.js",
        "node",
    )
    # The strongest signal (a path in the stack) overrides the entry default.
    assert target == "generated/svc/routes.js"


# ── Reporting: honest success / skip / failure ───────────────────────────────


def test_report_node_startup_success_is_honest():
    evidence = {
        "status": "completed",
        "commands": [{"type": "install", "success": True}, {"type": "build", "success": True}],
        "repairs": [],
        "startup": {"attempted": True, "success": True, "framework": "node", "health_url": "http://127.0.0.1:5/health", "probe_status": 200, "startup_seconds": 1.2},
    }
    report = render_runtime_report(evidence)
    assert "Node service booted" in report
    assert "/health" in report


def test_report_docker_skip_is_honest():
    evidence = {
        "status": "completed",
        "commands": [{"type": "install", "success": True}],
        "repairs": [],
        "startup": {"attempted": False, "framework": "docker", "reason": "Docker startup validation is not enabled for this deployment"},
    }
    report = render_runtime_report(evidence)
    assert "Startup check skipped" in report
    assert "not enabled" in report
    # No fake "working app" language without boot evidence.
    assert "booted" not in report


def test_report_node_startup_failure_is_clean():
    evidence = {
        "status": "failed",
        "failure_class": "node_startup_failed",
        "commands": [{"type": "install", "success": True, "command": "npm install"}],
        "repairs": [],
        "startup": {"attempted": True, "success": False, "framework": "node", "classification": "node_startup_failed", "health_url": "http://127.0.0.1:5/health", "output": "ReferenceError: boom", "teardown": "terminated"},
    }
    report = render_runtime_report(evidence)
    assert "Runtime validation failed (node_startup_failed)" in report
    assert "earlier checks passed" in report
    assert "process teardown: terminated" in report
