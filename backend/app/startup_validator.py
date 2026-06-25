# File: backend/app/startup_validator.py
"""
Startup / health validation for generated apps (bounded and safe).

Compile + import smoke tests prove code parses and loads — they do NOT prove an
app actually boots and serves. This module closes that gap for runnable Python
services (FastAPI/uvicorn, Flask):

    detect a boot target -> launch in a controlled subprocess ->
    poll a health/readiness probe with an explicit timeout ->
    capture evidence -> ALWAYS tear the process down.

Safety is non-negotiable: there is no "sleep and hope", every wait is bounded,
the process is killed in a finally block, and an ephemeral free port avoids
conflicts. The launcher and prober are injectable so tests never spawn real
processes, and operators can disable boot validation entirely via config.
"""

from __future__ import annotations

import json
import re
import shutil
import socket
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Optional

from app.core.config import settings
from tools.tool_router import ToolRouter

# Startup/runtime failure taxonomy (extends the runtime-validation classes).
# Generic Python classes plus broader-framework classes (Node/Next/Docker).
STARTUP_FAILURE_CLASSES = (
    "startup_command_failed",
    "startup_timeout",
    "healthcheck_failed",
    "readiness_failed",
    "probe_failed",
    "port_bind_failed",
    "missing_runtime_dependency",
    "process_crashed",
    "node_startup_failed",
    "node_startup_timeout",
    "next_startup_failed",
    "next_startup_timeout",
    "docker_unavailable",
    "docker_startup_failed",
    "docker_startup_timeout",
    "startup_repair_failed",
    "unrecoverable_startup_failure",
)

# Node-family frameworks share startup/repair behaviour (npm-driven server).
_NODE_FAMILY = {"node", "express", "fastify", "nest", "koa"}
_NODE_SERVER_DEPS = ("express", "fastify", "@nestjs/core", "koa", "hapi", "@hapi/hapi", "restify")
_NODE_ENTRY_NAMES = ("server.js", "server.ts", "index.js", "index.ts", "app.js", "app.ts", "main.js", "main.ts")

_FASTAPI_APP = re.compile(r"(\w+)\s*=\s*FastAPI\s*\(")
_FLASK_APP = re.compile(r"(\w+)\s*=\s*Flask\s*\(")
_HEALTH_ROUTE = re.compile(r"[\"'](/(?:health|ready|healthz|livez)\w*)[\"']")
# A health route in a JS server, e.g. app.get('/health', ...) or '/healthz'.
_JS_HEALTH_ROUTE = re.compile(r"[\"'`](/(?:health|ready|healthz|livez)\w*)[\"'`]")


@dataclass
class BootTarget:
    framework: str          # fastapi | flask | node | next | docker
    project_dir: str
    entry_file: str         # the file a startup failure most likely lives in
    entry_module: str       # main:app  (module:attr) — Python only, else ""
    app_attr: str           # app — Python only, else ""
    health_path: str        # /health  (or / as a basic ping)
    command: list[str]      # launch argv with a {port} placeholder ([] for docker)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BootTarget":
        return cls(**data)


def detect_boot_target(
    project_dir: str,
    files: list[str],
    *,
    read_file: Optional[Callable[..., dict]] = None,
) -> Optional[BootTarget]:
    """Return a safe boot plan when the output is a runnable service.

    Conservative by design and ordered cheapest-first: a Python web app, then a
    Node/Next service, then a Dockerized service. Only when a clear runnable
    target AND a derivable startup command + probe exist. Otherwise None —
    startup validation is skipped honestly rather than guessed.
    """
    read = read_file or (lambda path: ToolRouter.run("file_tool", "read_file", {"path": path}))
    for detector in (_detect_python_target, _detect_node_target, _detect_docker_target):
        target = detector(project_dir, files, read)
        if target is not None:
            return target
    return None


def _detect_python_target(project_dir: str, files: list[str], read: Callable[..., dict]) -> Optional[BootTarget]:
    entry = next(
        (f for f in files if f.endswith("main.py")),
        next((f for f in files if f.endswith("app.py")), None),
    )
    if not entry:
        return None
    result = read(entry)
    if not result.get("success"):
        return None
    content = result.get("content") or ""

    fastapi = _FASTAPI_APP.search(content)
    flask = _FLASK_APP.search(content)
    if not fastapi and not flask:
        return None  # not an obviously runnable web service

    rel = entry[len(project_dir) + 1 :] if entry.startswith(project_dir) else entry
    module = rel[:-3].replace("/", ".").replace("\\", ".")
    health_match = _HEALTH_ROUTE.search(content)
    health_path = health_match.group(1) if health_match else "/"

    if fastapi:
        attr = fastapi.group(1)
        return BootTarget(
            framework="fastapi",
            project_dir=project_dir,
            entry_file=entry,
            entry_module=f"{module}:{attr}",
            app_attr=attr,
            health_path=health_path,
            command=["python", "-m", "uvicorn", f"{module}:{attr}", "--port", "{port}", "--log-level", "warning"],
        )
    attr = flask.group(1)
    return BootTarget(
        framework="flask",
        project_dir=project_dir,
        entry_file=entry,
        entry_module=f"{module}:{attr}",
        app_attr=attr,
        health_path=health_path,
        command=["python", rel],
    )


def _detect_node_target(project_dir: str, files: list[str], read: Callable[..., dict]) -> Optional[BootTarget]:
    """Node/JS/TS service or Next.js app: runnable only when a start command is
    derivable (a `start` script, or a recognized server dependency + entry)."""
    pkg_path = next((f for f in files if f.endswith("package.json")), None)
    if not pkg_path:
        return None
    result = read(pkg_path)
    if not result.get("success"):
        return None
    try:
        pkg = json.loads(result.get("content") or "{}")
    except (ValueError, TypeError):
        return None  # unparsable package.json → skip honestly, don't guess
    if not isinstance(pkg, dict):
        return None

    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    scripts = pkg.get("scripts") or {}
    has_start = isinstance(scripts.get("start"), str) and scripts["start"].strip() != ""
    is_next = "next" in deps
    is_node_server = any(dep in deps for dep in _NODE_SERVER_DEPS)

    # Locate a plausible server entry file (best-effort, for repair targeting).
    entry_file = next((f for f in files if f.split("/")[-1].split("\\")[-1] in _NODE_ENTRY_NAMES), None)

    # Next.js: needs a start script (production server boots `next start`).
    if is_next:
        if not has_start:
            return None  # dev-only / no derivable bounded boot → skip honestly
        return BootTarget(
            framework="next",
            project_dir=project_dir,
            entry_file=entry_file or pkg_path,
            entry_module="",
            app_attr="",
            health_path="/",
            command=["npm", "run", "start", "--prefix", project_dir],
        )

    # Plain Node service: a start script OR a known server dep + an entry file.
    if not (has_start or (is_node_server and entry_file)):
        return None  # ambiguous (library / tooling) → skip honestly

    health_path = "/"
    if entry_file:
        entry_read = read(entry_file)
        if entry_read.get("success"):
            match = _JS_HEALTH_ROUTE.search(entry_read.get("content") or "")
            if match:
                health_path = match.group(1)

    if has_start:
        command = ["npm", "run", "start", "--prefix", project_dir]
    else:
        rel = entry_file[len(project_dir) + 1 :] if entry_file.startswith(project_dir) else entry_file
        command = ["node", rel]

    return BootTarget(
        framework="node",
        project_dir=project_dir,
        entry_file=entry_file or pkg_path,
        entry_module="",
        app_attr="",
        health_path=health_path,
        command=command,
    )


def _detect_docker_target(project_dir: str, files: list[str], read: Callable[..., dict]) -> Optional[BootTarget]:
    """Dockerized service: detected when a Dockerfile/compose file is present.
    Live boot is gated/skipped at probe time — this only records the target."""
    compose = next(
        (f for f in files if f.split("/")[-1].split("\\")[-1] in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")),
        None,
    )
    dockerfile = next((f for f in files if f.split("/")[-1].split("\\")[-1] == "Dockerfile"), None)
    target_file = compose or dockerfile
    if not target_file:
        return None
    return BootTarget(
        framework="docker",
        project_dir=project_dir,
        entry_file=target_file,
        entry_module="",
        app_attr="",
        health_path="/",
        command=[],
    )


# ── Default (real) launcher + prober ─────────────────────────────────────────


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _default_launcher(command: list[str], cwd: str, env_port: int):
    import os
    import subprocess

    env = dict(os.environ)
    env["PORT"] = str(env_port)
    return subprocess.Popen(
        command,
        cwd=cwd or ".",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
    )


def _default_prober(url: str, timeout: float = 1.0) -> tuple[bool, Optional[int]]:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return True, resp.status
    except urllib.error.HTTPError as error:
        return True, error.code  # the server responded (even if 4xx/5xx)
    except Exception:
        return False, None


# ── The bounded startup probe ────────────────────────────────────────────────


def run_startup_probe(
    target: BootTarget,
    *,
    ready_timeout: Optional[float] = None,
    poll_interval: float = 0.3,
    launcher: Callable[..., Any] = _default_launcher,
    prober: Callable[..., tuple[bool, Optional[int]]] = _default_prober,
    on_event: Optional[Callable[[str, dict], None]] = None,
) -> dict[str, Any]:
    """Launch the app, probe health within a timeout, then tear it down.

    Returns evidence: success, classification, the command, the probed URL,
    the status, timing, an stdout/stderr excerpt, and teardown success.
    """
    timeout = ready_timeout if ready_timeout is not None else settings.boot_ready_timeout_seconds

    def emit(event: str, **data: Any) -> None:
        if on_event:
            try:
                on_event(event, data)
            except Exception:
                pass

    if not settings.enable_boot_validation:
        return {
            "attempted": False,
            "reason": "boot validation disabled by configuration",
        }

    if target.framework == "docker":
        return _docker_probe(target, emit)

    port = _free_port()
    command = [str(port) if part == "{port}" else part for part in target.command]
    url = f"http://127.0.0.1:{port}{target.health_path}"
    evidence: dict[str, Any] = {
        "attempted": True,
        "framework": target.framework,
        "command": " ".join(command),
        "health_url": url,
        "success": False,
        "teardown": "not_started",
    }

    process = None
    started = time.monotonic()
    try:
        emit("startup_validation_started", command=evidence["command"])
        try:
            process = launcher(command, target.project_dir, port)
        except FileNotFoundError:
            evidence["classification"] = "startup_command_failed"
            evidence["error"] = "launch executable not found"
            return evidence
        except Exception as error:
            evidence["classification"] = "startup_command_failed"
            evidence["error"] = f"launch failed: {error}"
            return evidence

        emit("waiting_for_ready", url=url)
        deadline = started + timeout
        last_status: Optional[int] = None
        while time.monotonic() < deadline:
            # If the process died, it's a crash — don't keep polling.
            if process.poll() is not None:
                evidence["classification"] = _crash_class(target.framework)
                evidence["exit_code"] = process.returncode
                evidence["output"] = _drain(process)[:2000]
                evidence["startup_seconds"] = round(time.monotonic() - started, 2)
                return _classify_crash(evidence)
            ok, status = prober(url)
            last_status = status
            if ok:
                evidence["success"] = True
                evidence["probe_status"] = status
                evidence["startup_seconds"] = round(time.monotonic() - started, 2)
                emit("healthcheck_probing", status=status)
                return evidence
            time.sleep(poll_interval)

        # Never became ready within the bounded window.
        evidence["probe_status"] = last_status
        evidence["startup_seconds"] = round(time.monotonic() - started, 2)
        evidence["classification"] = _timeout_class(target.framework)
        evidence["output"] = _drain(process)[:2000]
        return evidence
    finally:
        evidence["teardown"] = _teardown(process)


def _drain(process) -> str:
    try:
        if process and process.stdout:
            # Non-blocking-ish read of whatever is buffered.
            return process.stdout.read() or ""
    except Exception:
        pass
    return ""


def _timeout_class(framework: str) -> str:
    if framework == "next":
        return "next_startup_timeout"
    if framework in _NODE_FAMILY:
        return "node_startup_timeout"
    return "startup_timeout"


def _crash_class(framework: str) -> str:
    if framework == "next":
        return "next_startup_failed"
    if framework in _NODE_FAMILY:
        return "node_startup_failed"
    return "process_crashed"


def _classify_crash(evidence: dict[str, Any]) -> dict[str, Any]:
    out = (evidence.get("output") or "").lower()
    # Missing dependency — Python and Node forms.
    if (
        "no module named" in out
        or "modulenotfounderror" in out
        or "importerror" in out
        or "cannot find module" in out
        or "err_module_not_found" in out
    ):
        evidence["classification"] = "missing_runtime_dependency"
    elif "address already in use" in out or "errno 98" in out or "eaddrinuse" in out or "bind" in out:
        evidence["classification"] = "port_bind_failed"
    return evidence


def _docker_probe(target: BootTarget, emit: Callable[..., None]) -> dict[str, Any]:
    """Docker/compose validation hook — bounded and honest.

    Live container boot is gated behind ``enable_docker_validation`` (off by
    default) because it is heavy and environment-dependent. This is the seam a
    real bounded compose boot plugs into later; for now we detect + report
    honestly rather than ever claiming a container "validated" without evidence.
    """
    evidence: dict[str, Any] = {
        "attempted": False,
        "framework": "docker",
        "target_file": target.entry_file,
    }
    emit("startup_validation_started", command=f"docker target: {target.entry_file}")
    if not settings.enable_docker_validation:
        evidence["reason"] = "Docker startup validation is not enabled for this deployment"
        return evidence
    if shutil.which("docker") is None:
        evidence["classification"] = "docker_unavailable"
        evidence["reason"] = "Docker is not available on this host"
        return evidence
    # Docker is enabled and present, but a live multi-service boot is out of
    # scope for now — skip honestly rather than fake a successful container boot.
    evidence["reason"] = "Docker detected and available; live container boot is not performed by AIRA-X yet"
    evidence["docker_available"] = True
    return evidence


def _teardown(process) -> str:
    """Reliable cleanup: terminate, then kill if it doesn't exit promptly."""
    if process is None:
        return "no_process"
    try:
        if process.poll() is not None:
            return "already_exited"
        process.terminate()
        try:
            process.wait(timeout=2.0)
            return "terminated"
        except Exception:
            process.kill()
            try:
                process.wait(timeout=2.0)
            except Exception:
                pass
            return "killed"
    except Exception:
        return "teardown_error"
