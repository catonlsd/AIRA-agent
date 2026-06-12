# File: backend/app/plan_executor.py
"""
Executable plans + the step-loop executor (execution-focused AIRA-X).

This module turns a resolved task into a STRUCTURED, machine-readable plan and
then actually executes it with real tools:

    prepare -> safety check -> tool call -> validate -> repair/retry -> next

A run only counts as completed when there is real evidence: files written on
disk, read back, and validated. Prose is never accepted as execution.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

from tools.tool_registry import ToolRegistry
from tools.tool_router import ToolRouter

# Patterns never allowed in any payload (mirrors the SafetyAgent blocklist).
_BLOCKED_PATTERNS = (
    "rm -rf",
    "del /s",
    "format ",
    "shutdown",
    "restart",
    "taskkill",
    "reg delete",
    "remove-item -recurse",
)

_MAX_MANIFEST_FILES = 10
_GENERATED_ROOT = "generated"


@dataclass
class PlanStep:
    """One machine-executable step."""

    id: int
    type: str  # scaffold | write | validate
    tool: str
    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    status: str = "pending"  # pending | executing | completed | failed | repaired


@dataclass
class ExecutablePlan:
    """The structured plan stored at approval time and executed on approval."""

    task_type: str  # "execution" | "research_then_execution"
    goal: str
    requires_plan_approval: bool
    project_dir: str
    steps: list[PlanStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "goal": self.goal,
            "requires_plan_approval": self.requires_plan_approval,
            "project_dir": self.project_dir,
            "steps": [asdict(step) for step in self.steps],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutablePlan":
        return cls(
            task_type=data.get("task_type", "execution"),
            goal=data.get("goal", ""),
            requires_plan_approval=bool(data.get("requires_plan_approval", True)),
            project_dir=data.get("project_dir", _GENERATED_ROOT),
            steps=[PlanStep(**step) for step in data.get("steps", [])],
        )


@dataclass
class ExecutionReport:
    """Evidence-backed outcome of running an ExecutablePlan."""

    status: str = "failed"  # completed | failed
    files_written: list[dict[str, Any]] = field(default_factory=list)
    step_results: list[dict[str, Any]] = field(default_factory=list)
    repairs: list[dict[str, Any]] = field(default_factory=list)
    validation: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


# ── Plan construction ────────────────────────────────────────────────────────


def project_slug(original_request: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", original_request.lower()).strip("_")
    return slug[:40] or "project"


def _fallback_manifest(resolved_task: dict[str, Any]) -> list[dict[str, str]]:
    """Deterministic manifest when the LLM cannot produce a usable one."""
    output_format = (resolved_task.get("selected_output_format") or "").lower()
    plan_only = "plan" in output_format and "backend" not in output_format

    if plan_only:
        return [
            {"path": "IMPLEMENTATION_PLAN.md", "purpose": "Step-by-step implementation plan"}
        ]

    manifest = [
        {"path": "app/main.py", "purpose": "Application entrypoint and API routes"},
        {"path": "app/rag_service.py", "purpose": "Ingestion, retrieval, and answer generation"},
        {"path": "requirements.txt", "purpose": "Python dependencies"},
        {"path": "README.md", "purpose": "Setup and usage instructions"},
    ]
    if "frontend" in output_format:
        manifest.append(
            {"path": "frontend/index.html", "purpose": "Minimal frontend for upload and chat"}
        )
    return manifest


def _parse_manifest(raw: str) -> Optional[list[dict[str, str]]]:
    """Extract a [{path, purpose}] JSON array from an LLM reply."""
    if not raw:
        return None
    match = re.search(r"\[[\s\S]*\]", raw)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    manifest: list[dict[str, str]] = []
    for entry in data[:_MAX_MANIFEST_FILES]:
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("path") or "").strip().lstrip("/\\")
        if not path or ".." in path:
            continue
        manifest.append({"path": path, "purpose": str(entry.get("purpose") or "")})
    return manifest or None


def design_file_manifest(
    goal: str,
    resolved_task: dict[str, Any],
    generate: Callable[..., str],
) -> list[dict[str, str]]:
    """Ask the model which files the project needs; fall back deterministically."""
    prompt = (
        f"{goal}\n\n"
        "List the files needed to implement this, as a JSON array of objects "
        'with keys "path" (relative file path) and "purpose" (one line). '
        f"Maximum {_MAX_MANIFEST_FILES} files. Honor the selected output format: "
        "backend-only must not include frontend files. Respond with ONLY the "
        "JSON array."
    )
    for attempt in range(2):
        try:
            raw = generate(
                system=(
                    "You are AIRA-X's implementation planner. Respond with only "
                    "a JSON array — no prose, no markdown fences."
                ),
                prompt=prompt if attempt == 0 else prompt + "\nJSON ONLY.",
                temperature=0.0,
            )
        except Exception:
            break
        manifest = _parse_manifest(raw)
        if manifest:
            return manifest
    return _fallback_manifest(resolved_task)


def build_executable_plan(
    original_request: str,
    goal: str,
    resolved_task: dict[str, Any],
    generate: Callable[..., str],
    task_type: str = "execution",
) -> ExecutablePlan:
    """Build the structured plan: one write step per manifest file + validation."""
    project_dir = f"{_GENERATED_ROOT}/{project_slug(original_request)}"
    manifest = design_file_manifest(goal, resolved_task, generate)

    steps: list[PlanStep] = []
    for index, entry in enumerate(manifest, start=1):
        steps.append(
            PlanStep(
                id=index,
                type="write",
                tool="file_tool",
                action="write_file",
                payload={
                    "path": f"{project_dir}/{entry['path']}",
                    "purpose": entry["purpose"],
                },
                description=f"Create {entry['path']} — {entry['purpose']}",
            )
        )
    steps.append(
        PlanStep(
            id=len(steps) + 1,
            type="validate",
            tool="file_tool",
            action="list_files",
            payload={"path": project_dir},
            description="Validate all files exist and are well-formed",
        )
    )

    return ExecutablePlan(
        task_type=task_type,
        goal=goal,
        requires_plan_approval=True,
        project_dir=project_dir,
        steps=steps,
    )


# ── Execution loop ───────────────────────────────────────────────────────────


def _is_payload_safe(payload: dict[str, Any]) -> Optional[str]:
    """Return a reason when the payload is unsafe, else None."""
    flat = json.dumps(payload).lower()
    for pattern in _BLOCKED_PATTERNS:
        if pattern in flat:
            return f"blocked pattern: {pattern}"
    path = str(payload.get("path") or "")
    if ".." in path:
        return "path traversal"
    return None


def _strip_code_fences(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_+-]*\n", "", text)
        if text.endswith("```"):
            text = text[: -len("```")]
    return text.strip() + "\n"


def _generate_file_content(
    plan: ExecutablePlan,
    step: PlanStep,
    generate: Callable[..., str],
    error_context: Optional[str] = None,
) -> str:
    manifest_lines = "\n".join(
        f"- {s.payload.get('path')}: {s.payload.get('purpose', '')}"
        for s in plan.steps
        if s.type == "write"
    )
    repair_note = (
        f"\n\nThe previous attempt failed validation with this error — fix it:\n{error_context}"
        if error_context
        else ""
    )
    raw = generate(
        system=(
            "You are AIRA-X executing an approved implementation plan. Write the "
            "COMPLETE contents of exactly one file. STRICT RULES: use EXACTLY "
            "the technologies stated in the task (never substitute a different "
            "vector store, framework, or LLM provider). Output ONLY the raw "
            "file content — no markdown fences, no commentary."
        ),
        prompt=(
            f"{plan.goal}\n\n"
            f"Project files:\n{manifest_lines}\n\n"
            f"Write this file now: {step.payload.get('path')}\n"
            f"Purpose: {step.payload.get('purpose', '')}{repair_note}"
        ),
        temperature=0.2,
    )
    return _strip_code_fences(raw)


def _validate_written_file(path: str) -> Optional[str]:
    """Read the file back through the tool; return an error string or None."""
    read = ToolRouter.run("file_tool", "read_file", {"path": path})
    if not read.get("success"):
        return f"file not readable: {read.get('error')}"
    content = read.get("content") or ""
    if not content.strip():
        return "file is empty"
    if path.endswith(".py"):
        try:
            compile(content, path, "exec")
        except SyntaxError as error:
            return f"Python syntax error: {error}"
    if path.endswith(".json"):
        try:
            json.loads(content)
        except json.JSONDecodeError as error:
            return f"invalid JSON: {error}"
    return None


def execute_plan(
    plan: ExecutablePlan,
    generate: Callable[..., str],
    on_event: Optional[Callable[[str, dict[str, Any]], None]] = None,
) -> ExecutionReport:
    """Run the step loop with real tools. Completion requires evidence."""

    def emit(event: str, **data: Any) -> None:
        if on_event:
            try:
                on_event(event, data)
            except Exception:
                pass

    report = ExecutionReport()

    for step in plan.steps:
        step.status = "executing"
        emit("executing_step", step_id=step.id, description=step.description)

        # Safety gate (registry policy + blocklist) before every tool call.
        if not ToolRegistry.is_action_allowed(step.tool, step.action):
            step.status = "failed"
            report.error = f"step {step.id}: action {step.tool}.{step.action} not allowed"
            report.step_results.append({"id": step.id, "status": "failed", "error": report.error})
            return report
        unsafe = _is_payload_safe(step.payload)
        if unsafe:
            step.status = "failed"
            report.error = f"step {step.id}: unsafe payload ({unsafe})"
            report.step_results.append({"id": step.id, "status": "failed", "error": report.error})
            return report

        if step.type == "write":
            error = _run_write_step(plan, step, generate, report, emit)
        elif step.type == "validate":
            error = _run_validate_step(plan, step, report, emit)
        else:
            result = ToolRouter.run(step.tool, step.action, dict(step.payload))
            error = None if result.get("success") else (result.get("error") or "tool failed")
            report.step_results.append(
                {"id": step.id, "status": "completed" if not error else "failed", "output": result.get("output", "")}
            )

        if error:
            step.status = "failed"
            report.error = f"step {step.id} ({step.description}): {error}"
            report.status = "failed"
            return report
        if step.status != "repaired":
            step.status = "completed"

    # Completion demands evidence: at least one file written and validated.
    if report.files_written and not report.error:
        report.status = "completed"
    else:
        report.status = "failed"
        report.error = report.error or "no files were written — nothing to complete"
    return report


def _run_write_step(
    plan: ExecutablePlan,
    step: PlanStep,
    generate: Callable[..., str],
    report: ExecutionReport,
    emit: Callable[..., None],
) -> Optional[str]:
    """Prepare (generate content), write via tool, validate, repair once."""
    path = str(step.payload.get("path"))
    error_context: Optional[str] = None

    for attempt in range(2):  # initial + one repair
        try:
            content = _generate_file_content(plan, step, generate, error_context)
        except Exception as error:
            return f"content generation failed: {error}"

        result = ToolRouter.run(
            "file_tool", "write_file", {"path": path, "content": content}
        )
        if not result.get("success"):
            error_context = result.get("error") or "write failed"
        else:
            validation_error = _validate_written_file(path)
            if validation_error is None:
                report.files_written.append({"path": path, "bytes": len(content)})
                report.step_results.append(
                    {"id": step.id, "status": "completed" if attempt == 0 else "repaired", "path": path}
                )
                if attempt > 0:
                    step.status = "repaired"
                    report.repairs.append({"path": path, "error": error_context})
                    emit("step_repaired", step_id=step.id, path=path)
                return None
            error_context = validation_error

        emit("step_repairing", step_id=step.id, path=path, error=error_context)

    report.step_results.append({"id": step.id, "status": "failed", "path": path, "error": error_context})
    return error_context


def _run_validate_step(
    plan: ExecutablePlan,
    step: PlanStep,
    report: ExecutionReport,
    emit: Callable[..., None],
) -> Optional[str]:
    """Final validation: every planned file exists, is readable, well-formed."""
    emit("validating", project_dir=plan.project_dir)
    expected = [
        str(s.payload.get("path")) for s in plan.steps if s.type == "write"
    ]
    missing: list[str] = []
    for path in expected:
        if _validate_written_file(path) is not None:
            missing.append(path)

    listing = ToolRouter.run("file_tool", "list_files", {"path": plan.project_dir})
    report.validation = {
        "expected_files": len(expected),
        "verified_files": len(expected) - len(missing),
        "missing_or_invalid": missing,
        "listing_success": bool(listing.get("success")),
    }
    report.step_results.append(
        {"id": step.id, "status": "completed" if not missing else "failed", **report.validation}
    )
    if missing:
        return f"validation failed for: {', '.join(missing)}"
    return None


# ── Runtime self-check (gated behind per-action approval) ───────────────────


def build_runtime_actions(plan: ExecutablePlan, report: ExecutionReport) -> list[dict[str, Any]]:
    """Typed, ordered validation steps derived from what was generated.

    Order is deliberate and stable: install -> compile/build -> import smoke.
    Each action carries a type used later for failure classification.
    """
    files = [entry["path"] for entry in report.files_written]
    actions: list[dict[str, Any]] = []

    def _add(action_type: str, command: str, description: str) -> None:
        actions.append(
            {
                "id": len(actions) + 1,
                "type": action_type,
                "tool": "shell_tool",
                "action": "run",
                "payload": {"command": command},
                "status": "pending",
                "description": description,
            }
        )

    requirements = next((p for p in files if p.endswith("requirements.txt")), None)
    if requirements:
        _add("install", f"pip install -r {requirements}", "Install Python dependencies")
    if any(p.endswith("package.json") for p in files):
        _add("install", f"npm install --prefix {plan.project_dir}", "Install JS dependencies")

    if any(p.endswith(".py") for p in files):
        _add(
            "smoke_test",
            f"python -m compileall -q {plan.project_dir}",
            "Compile-check the generated Python project",
        )
    if any(p.endswith((".ts", ".tsx")) for p in files) and any(
        p.endswith("package.json") for p in files
    ):
        _add(
            "build",
            f"npm run build --if-present --prefix {plan.project_dir}",
            "Build/type-check the generated JS/TS project",
        )

    # Import smoke test: actually import the Python entry module.
    entry = next((p for p in files if p.endswith("main.py")), None)
    if entry:
        rel = entry[len(plan.project_dir) + 1 :] if entry.startswith(plan.project_dir) else entry
        module = rel[:-3].replace("/", ".").replace("\\", ".")
        _add(
            "import_smoke",
            (
                f"python -c \"import sys; sys.path.insert(0, '{plan.project_dir}'); "
                f"import importlib; importlib.import_module('{module}')\""
            ),
            "Import the entry module as a startup smoke test",
        )
    return actions


# ── Failure classification (drives repair decisions, traces, reporting) ─────

_TRACEBACK_FILE = re.compile(r'File "([^"]+)"')
_MISSING_MODULE = re.compile(r"no module named '?\"?([\w.]+)", re.IGNORECASE)


def classify_runtime_failure(action_type: str, output: str) -> str:
    """Map a failed validation step to a meaningful failure class."""
    text = (output or "").lower()
    if action_type == "install":
        return "dependency_install_failed"
    if "no module named" in text or "modulenotfounderror" in text or "importerror" in text:
        return "import_failed"
    if "syntaxerror" in text or "indentationerror" in text:
        return "compile_failed"
    if action_type == "import_smoke":
        return "startup_failed"
    if action_type == "build":
        return "build_failed"
    if action_type == "smoke_test":
        return "compile_failed"
    if action_type == "healthcheck":
        return "healthcheck_failed"
    return "unrecoverable_runtime_failure"


def _repair_target(output: str, plan_files: list[str]) -> Optional[str]:
    """Map failure evidence to the most likely generated file to repair."""
    text = output or ""
    # 1. Traceback file paths are the strongest signal.
    for raw in _TRACEBACK_FILE.findall(text):
        name = raw.replace("\\", "/").split("/")[-1]
        for path in plan_files:
            if path.endswith(name):
                return path
    # 2. A missing module maps to its generated file, else to requirements.txt.
    missing = _MISSING_MODULE.search(text)
    if missing:
        module = missing.group(1).split(".")[-1]
        for path in plan_files:
            if path.endswith(f"{module}.py"):
                return path
        for path in plan_files:
            if path.endswith("requirements.txt"):
                return path
    # 3. Fallback: any generated filename mentioned in the output.
    return next((p for p in plan_files if p.split("/")[-1] in text), None)


def execute_runtime_validation(
    plan: ExecutablePlan,
    actions: list[dict[str, Any]],
    generate: Callable[..., str],
    run_tool: Optional[Callable[..., dict[str, Any]]] = None,
    on_event: Optional[Callable[[str, dict[str, Any]], None]] = None,
) -> dict[str, Any]:
    """Run approved install/smoke commands; diagnose + repair once on failure.

    Returns evidence: every command run with its captured output, repairs
    performed, and an honest completed/failed status.
    """

    def emit(event: str, **data: Any) -> None:
        if on_event:
            try:
                on_event(event, data)
            except Exception:
                pass

    # Resolved at call time so tests/hosts can swap the tool runner.
    if run_tool is None:
        run_tool = ToolRouter.run

    plan_files = [str(s.payload.get("path")) for s in plan.steps if s.type == "write"]
    evidence: dict[str, Any] = {
        "status": "completed",
        "commands": [],
        "repairs": [],
        "retry_count": 0,
    }

    for action in actions:
        command = str(action.get("payload", {}).get("command", ""))
        action_type = str(action.get("type", "smoke_test"))
        unsafe = _is_payload_safe(action.get("payload", {}))
        if unsafe:
            evidence["status"] = "failed"
            evidence["failure_class"] = "unrecoverable_runtime_failure"
            evidence["error"] = f"unsafe runtime action ({unsafe})"
            break

        for attempt in range(2):  # initial + one repaired retry, never more
            emit("executing_step", description=action.get("description"), command=command)
            result = run_tool(action["tool"], action["action"], dict(action["payload"]))
            output = str(result.get("output") or result.get("error") or "")
            entry: dict[str, Any] = {
                "command": command,
                "type": action_type,
                "success": bool(result.get("success")),
                "output": output[:2000],
            }
            if result.get("success"):
                evidence["commands"].append(entry)
                break

            failure_class = classify_runtime_failure(action_type, output)
            entry["classification"] = failure_class
            evidence["commands"].append(entry)
            evidence["failure_class"] = failure_class

            # Evidence-driven repair: map the failure to a generated file. A
            # failed dependency install only repairs its requirements file —
            # blind code regeneration cannot fix a broken installer.
            target = _repair_target(output, plan_files)
            if failure_class == "dependency_install_failed" and (
                target is None or not target.endswith("requirements.txt")
            ):
                target = next(
                    (p for p in plan_files if p.endswith("requirements.txt")), None
                )
            if attempt == 0 and target:
                emit("repairing", path=target, classification=failure_class, error=output[:300])
                evidence["retry_count"] += 1
                try:
                    step = next(s for s in plan.steps if str(s.payload.get("path")) == target)
                    content = _generate_file_content(plan, step, generate, error_context=output[:1500])
                except Exception as error:
                    evidence["status"] = "failed"
                    evidence["failure_class"] = "repair_failed"
                    evidence["error"] = f"repair generation failed: {error}"
                    break
                write = run_tool("file_tool", "write_file", {"path": target, "content": content})
                if write.get("success"):
                    evidence["repairs"].append(
                        {"path": target, "classification": failure_class, "error": output[:300]}
                    )
                    emit("retrying", command=command)
                    continue
            evidence["status"] = "failed"
            evidence["error"] = f"runtime validation failed: {command}"
            break
        if evidence["status"] == "failed":
            break

    executed = evidence["commands"]
    evidence["validation_summary"] = {
        "planned": len(actions),
        "executed": len({e["command"] for e in executed}),
        "passed": len([e for e in executed if e["success"]]),
        "failed": len([e for e in executed if not e["success"]]),
    }
    return evidence


def render_runtime_offer(actions: list[dict[str, Any]]) -> str:
    lines = ["", "Runtime validation available — with your approval I will run:"]
    for action in actions:
        lines.append(f"- {action['payload']['command']}  ({action['description']})")
    lines.append(
        'Reply "approve" to run and self-check the project, or "reject" to keep '
        "the files as-is."
    )
    return "\n".join(lines)


_TYPE_LABELS = {
    "install": "dependency install",
    "smoke_test": "compile check",
    "import_smoke": "import/startup smoke test",
    "build": "build/type-check",
    "healthcheck": "healthcheck",
}


def render_runtime_report(evidence: dict[str, Any]) -> str:
    """Honest, readable runtime summary — no raw log dumps in the main answer."""
    commands = evidence.get("commands", [])
    repairs = evidence.get("repairs", [])
    passed_types = [
        _TYPE_LABELS.get(e.get("type", ""), e.get("type", "check"))
        for e in commands
        if e["success"]
    ]
    lines: list[str] = []

    if evidence.get("status") == "completed":
        checks = ", ".join(dict.fromkeys(passed_types)) or "validation checks"
        lines.append(f"Runtime validation passed: {checks}.")
        if repairs:
            lines.append("")
            lines.append(f"Repairs made along the way ({len(repairs)}):")
            for repair in repairs:
                lines.append(
                    f"- {repair['path']} — regenerated after {repair.get('classification', 'a failure')}"
                )
        lines.append("")
        lines.append(
            "The generated project is installed and passes its checks. Next: "
            "review the files and run the app; ask me to adjust anything."
        )
        return "\n".join(lines)

    failure_class = evidence.get("failure_class", "runtime failure")
    failed = next((e for e in commands if not e["success"]), {})
    lines.append(f"Runtime validation failed ({failure_class}).")
    if failed:
        lines.append(f"- failing step: {failed.get('command', '?')}")
        excerpt = (failed.get("output") or "").strip()
        if excerpt:
            lines.append(f"- error excerpt: {excerpt[:240]}")
    if repairs:
        for repair in repairs:
            lines.append(
                f"- repair attempted: regenerated {repair['path']} "
                f"(after {repair.get('classification', 'failure')}) — the retry still failed"
            )
    else:
        lines.append("- no safe repair target could be identified, so no blind retry was made")
    lines.append("")
    lines.append(
        "The generated files are kept on disk. Manual follow-up is needed for "
        "the failing step above — or tell me what to change and I'll regenerate it."
    )
    return "\n".join(lines)


# ── Evidence report rendering ────────────────────────────────────────────────


def render_execution_report(plan: ExecutablePlan, report: ExecutionReport) -> str:
    """Human-readable evidence summary for the final answer."""
    lines: list[str] = []
    if report.status == "completed":
        lines.append("Execution complete — here is the evidence:")
    else:
        lines.append("Execution failed — here is what happened:")

    if report.files_written:
        lines.append("")
        lines.append(f"Files written ({len(report.files_written)}):")
        for entry in report.files_written:
            lines.append(f"- {entry['path']} ({entry['bytes']} bytes)")

    if report.validation:
        lines.append("")
        lines.append(
            f"Validation: {report.validation.get('verified_files', 0)}/"
            f"{report.validation.get('expected_files', 0)} files verified "
            "(read back, non-empty, syntax-checked for .py/.json)."
        )

    if report.repairs:
        lines.append("")
        lines.append(f"Repairs ({len(report.repairs)}):")
        for repair in report.repairs:
            lines.append(f"- {repair['path']}: regenerated after {repair['error']}")

    if report.error and report.status != "completed":
        lines.append("")
        lines.append(f"Error: {report.error}")

    if report.status == "completed":
        lines.append("")
        lines.append(
            f"Next steps: review the files under {plan.project_dir}/, install "
            "dependencies, and run the project. Ask me to adjust any file."
        )
    return "\n".join(lines)
