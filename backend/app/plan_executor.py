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
