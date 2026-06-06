import asyncio
import json
from uuid import uuid4
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.turn_classifier import (
    DOCUMENT_QA_MODE,
    SELF_MEMORY_MODE,
    WEB_RESEARCH_MODE,
)
from app.assistant_supervisor import AssistantSupervisor
from app.context_builder import build_turn_context
from app.services.trace_service import TraceService

from graph.langgraph_aira_workflow import LangGraphAiraXWorkflow
from tools.tool_registry import ToolRegistry
from tools.tool_router import ToolRouter
from agents.agent_registry import AgentRegistry
from memory.workflow_store import WorkflowStore
from memory.workflow_memory import WorkflowMemory
from agents.memory.memory_agent import MemoryAgent


router = APIRouter(prefix="/aira-x", tags=["AIRA-X"])

_APPROVAL_LOCKS: Dict[str, asyncio.Lock] = {}
_APPROVAL_STALE_AFTER_SECONDS = 10 * 60
_SAFE_BULK_DELETE_STATUSES = {"completed", "failed", "rejected"}


class AiraXRunRequest(BaseModel):
    goal: str
    session_id: str | None = None


class AiraXApproveRequest(BaseModel):
    run_id: str


class AiraXRejectRequest(BaseModel):
    run_id: str


def serialize_state(state):
    approval_context = state.memory.get("approval_context", {})
    approval_resolution = state.memory.get("approval_resolution", {})

    return {
        "run_id": state.run_id,
        "status": state.status,
        "decision": state.decision,
        "final_answer": state.final_answer,
        "created_at": state.created_at,
        "updated_at": state.updated_at,
        "completed_at": state.completed_at,
        "plan": [step.model_dump() for step in state.plan],
        "execution_outputs": state.execution_outputs,
        "memory": state.memory,
        "workflow_logs": state.memory.get("workflow_logs", []),
        "workflow_summary": state.memory.get("workflow_summary", {}),
        "requires_approval": state.status == "requires_approval",
        "pending_action": state.memory.get("pending_action"),
        "approval_context": approval_context,
        "approval_context_type": approval_context.get("type"),
        "approval_in_progress": state.memory.get("approval_in_progress", False),
        "approval_resolution": approval_resolution,
        "approval_resolution_status": approval_resolution.get("status"),
        "approval_resolution_action": approval_resolution.get("action"),
        "approval_stale_recovered": state.memory.get(
            "approval_stale_recovered",
            False,
        ),
    }


def _get_approval_lock(run_id: str) -> asyncio.Lock:
    if run_id not in _APPROVAL_LOCKS:
        _APPROVAL_LOCKS[run_id] = asyncio.Lock()

    return _APPROVAL_LOCKS[run_id]


def _approval_lock_is_active(run_id: Optional[str]) -> bool:
    if not run_id:
        return False

    approval_lock = _APPROVAL_LOCKS.get(run_id)

    return approval_lock.locked() if approval_lock else False


def _remove_inactive_approval_lock(run_id: str) -> None:
    approval_lock = _APPROVAL_LOCKS.get(run_id)

    if approval_lock and not approval_lock.locked():
        _APPROVAL_LOCKS.pop(run_id, None)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def _approval_processing_started_at(state) -> Optional[datetime]:
    approval_resolution = state.memory.get("approval_resolution", {})

    return _parse_iso_datetime(
        state.memory.get("approval_processing_started_at")
        or approval_resolution.get("requested_at")
    )


def _approval_processing_age_seconds(state) -> Optional[float]:
    started_at = _approval_processing_started_at(state)

    if not started_at:
        return None

    return (_utc_now() - started_at).total_seconds()


def _approval_is_being_processed(state) -> bool:
    return state.memory.get("approval_in_progress") is True


def _approval_processing_is_stale(state) -> bool:
    if not _approval_is_being_processed(state):
        return False

    age_seconds = _approval_processing_age_seconds(state)

    if age_seconds is None:
        return False

    return age_seconds >= _APPROVAL_STALE_AFTER_SECONDS


def _recover_stale_approval_processing_state(
    state,
    *,
    ignore_active_lock: bool = False,
) -> bool:
    if not _approval_processing_is_stale(state):
        return False

    if (
        not ignore_active_lock
        and state.run_id
        and _approval_lock_is_active(state.run_id)
    ):
        return False

    approval_resolution = state.memory.get("approval_resolution", {})
    pending_action = (
        state.memory.get("pending_action")
        or approval_resolution.get("action")
        or "unknown approval action"
    )
    started_at = (
        state.memory.get("approval_processing_started_at")
        or approval_resolution.get("requested_at")
    )
    recovered_at = _utc_now_iso()

    recovery_message = (
        "AIRA-X recovered a stale approval-processing state. "
        "No action was executed during the stale lock, so the workflow is now "
        "marked as failed and safe to inspect or delete."
    )

    current_step = next(
        (step for step in state.plan if step.id == state.current_step),
        None,
    )

    if current_step and current_step.status in {"blocked", "pending", "running"}:
        current_step.status = "failed"

        if not current_step.error:
            current_step.error = recovery_message

    state.status = "failed"
    state.decision = "approval_processing_stale_recovered"
    state.final_answer = recovery_message

    state.memory["approval_in_progress"] = False
    state.memory["approval_stale_recovered"] = True
    state.memory["approval_processing_recovered_at"] = recovered_at

    state.memory.setdefault("approval_recovery_events", [])
    state.memory["approval_recovery_events"].append(
        {
            "reason": "stale_approval_processing",
            "action": pending_action,
            "started_at": started_at,
            "recovered_at": recovered_at,
            "stale_after_seconds": _APPROVAL_STALE_AFTER_SECONDS,
            "previous_resolution_status": approval_resolution.get("status"),
        }
    )

    state.memory["approval_resolution"] = {
        "status": "stale_processing_recovered",
        "previous_status": approval_resolution.get("status"),
        "action": pending_action,
        "requested_at": approval_resolution.get("requested_at") or started_at,
        "completed_at": recovered_at,
        "final_status": state.status,
        "final_decision": state.decision,
        "error": recovery_message,
    }

    WorkflowMemory.add_log(
        state,
        agent="approval_agent",
        event="stale_approval_processing_recovered",
        details={
            "run_id": state.run_id,
            "action": pending_action,
            "started_at": started_at,
            "recovered_at": recovered_at,
            "stale_after_seconds": _APPROVAL_STALE_AFTER_SECONDS,
            "final_status": state.status,
            "final_decision": state.decision,
        },
    )

    return True


def _recover_stale_approval_processing_runs() -> None:
    for run_summary in WorkflowStore.list_runs():
        run_id = run_summary.get("run_id")

        if not run_id:
            continue

        state = WorkflowStore.get(run_id)

        if not state:
            continue

        if _recover_stale_approval_processing_state(state):
            WorkflowStore.save(state)


def _workflow_can_be_deleted(state) -> bool:
    if _approval_lock_is_active(state.run_id):
        return False

    if _approval_is_being_processed(state):
        return False

    return True


def _workflow_is_safe_bulk_delete_candidate(state) -> bool:
    if state.status not in _SAFE_BULK_DELETE_STATUSES:
        return False

    return _workflow_can_be_deleted(state)


def _workflow_delete_blocked_response(state, run_id: str):
    return {
        "success": False,
        "error": (
            "Workflow cannot be deleted while an approval-gated action is "
            "being processed. Wait for it to finish, or let stale approval "
            "recovery mark it safe first."
        ),
        "run_id": run_id,
        "current_status": state.status,
        "decision": state.decision,
        "approval_in_progress": state.memory.get("approval_in_progress", False),
        "approval_resolution": state.memory.get("approval_resolution"),
        "workflow": serialize_state(state),
    }


def _summarize_workflow_for_delete(state):
    return {
        "run_id": state.run_id,
        "user_goal": state.user_goal,
        "status": state.status,
        "decision": state.decision,
        "final_answer": state.final_answer,
        "created_at": state.created_at,
        "updated_at": state.updated_at,
        "completed_at": state.completed_at,
    }


def _safe_bulk_delete_skip_reason(state) -> str:
    if _approval_lock_is_active(state.run_id):
        return "approval_lock_active"

    if _approval_is_being_processed(state):
        return "approval_in_progress"

    if state.status not in _SAFE_BULK_DELETE_STATUSES:
        return "non_final_status"

    return "not_safe_to_delete"


def _approval_not_available_response(state, run_id: str, requested_action: str):
    return {
        "success": False,
        "error": (
            f"Workflow cannot be {requested_action}. "
            f"Current status: {state.status}. "
            "This approval may already be handled or no longer be pending."
        ),
        "run_id": run_id,
        "current_status": state.status,
        "decision": state.decision,
        "pending_action": state.memory.get("pending_action"),
        "approval_in_progress": state.memory.get("approval_in_progress", False),
        "approval_resolution": state.memory.get("approval_resolution"),
        "workflow": serialize_state(state),
    }


def _approval_processing_response(state, run_id: str, requested_action: str):
    return {
        "success": False,
        "error": (
            f"Workflow {requested_action} is already being processed. "
            "Please wait and refresh the workflow."
        ),
        "run_id": run_id,
        "current_status": state.status,
        "decision": state.decision,
        "pending_action": state.memory.get("pending_action"),
        "approval_in_progress": True,
        "approval_resolution": state.memory.get("approval_resolution"),
        "workflow": serialize_state(state),
    }


def _workflow_successfully_staged_changes(state) -> bool:
    return any(
        output.get("tool_used") == "git_tool"
        and output.get("tool_action") == "stage_all"
        and output.get("tool_result", {}).get("success") is True
        for output in state.execution_outputs
    )


def _should_cleanup_staged_changes_after_rejection(state) -> bool:
    approval_context = state.memory.get("approval_context", {})
    pending_action = state.memory.get("pending_action", "")

    is_commit_rejection = (
        approval_context.get("tool_name") == "git_tool"
        and approval_context.get("tool_action") == "commit"
        and pending_action.startswith("git_tool:commit")
    )

    return is_commit_rejection and _workflow_successfully_staged_changes(state)


def _cleanup_staged_changes_after_rejection(state):
    cleanup_result = ToolRouter.run(
        tool_name="git_tool",
        action="unstage_all",
        payload={},
    )

    state.memory.setdefault("cleanup_actions", [])
    state.memory["cleanup_actions"].append(
        {
            "reason": "commit_rejected_after_aira_x_stage_all",
            "tool_name": "git_tool",
            "tool_action": "unstage_all",
            "result": cleanup_result,
        }
    )

    WorkflowMemory.add_log(
        state,
        agent="git_tool",
        event="git_staging_cleanup_after_rejection",
        details={
            "reason": "Commit approval was rejected after AIRA-X staged changes.",
            "cleanup_action": "git_tool:unstage_all",
            "cleanup_success": cleanup_result.get("success", False),
            "cleanup_result": cleanup_result,
        },
    )

    return cleanup_result


def _dedupe_dict_list(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    unique_items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in items:
        if not isinstance(item, dict):
            continue

        marker = json.dumps(item, sort_keys=True, default=str)
        if marker in seen:
            continue

        seen.add(marker)
        unique_items.append(item)

    return unique_items


def _memory_dicts(memory: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = memory.get(key, [])

    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]

    if isinstance(value, dict):
        return [value]

    return []


def _collect_sources_from_workflow(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    memory = workflow.get("memory", {})

    sources: list[dict[str, Any]] = []
    sources.extend(_memory_dicts(memory, "sources"))
    sources.extend(_memory_dicts(memory, "document_sources"))
    sources.extend(_memory_dicts(memory, "web_sources"))
    sources.extend(_memory_dicts(memory, "citations"))
    sources.extend(_memory_dicts(workflow, "sources"))

    return _dedupe_dict_list(sources)


def _collect_artifacts_from_workflow(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    memory = workflow.get("memory", {})

    artifacts: list[dict[str, Any]] = []
    artifacts.extend(_memory_dicts(memory, "artifacts"))
    artifacts.extend(_memory_dicts(memory, "generated_artifacts"))
    artifacts.extend(_memory_dicts(workflow, "artifacts"))

    return _dedupe_dict_list(artifacts)


def _build_approval_summary_from_workflow(workflow: dict[str, Any]) -> dict[str, Any] | None:
    pending_action = workflow.get("pending_action")
    approval_context = workflow.get("approval_context") or {}
    approval_resolution = workflow.get("approval_resolution") or {}
    requires_approval = workflow.get("requires_approval", False)
    approval_in_progress = workflow.get("approval_in_progress", False)

    if not any(
        [
            pending_action,
            approval_context,
            approval_resolution,
            requires_approval,
            approval_in_progress,
        ]
    ):
        return None

    summary_message = None

    if requires_approval:
        summary_message = workflow.get("final_answer") or "Approval is required before execution."
    elif approval_in_progress:
        summary_message = "This approval request is currently being processed."
    elif approval_resolution.get("status") == "approved":
        summary_message = "The approval-gated action was approved."
    elif approval_resolution.get("status") == "rejected":
        summary_message = "The approval-gated action was rejected."
    elif approval_resolution.get("status") == "stale_processing_recovered":
        summary_message = (
            "A stale approval-processing state was recovered safely and the workflow was stopped."
        )

    return {
        "required": requires_approval,
        "in_progress": approval_in_progress,
        "pending_action": pending_action,
        "status": approval_resolution.get("status"),
        "action": approval_resolution.get("action") or pending_action,
        "context_type": approval_context.get("type"),
        "tool_name": approval_context.get("tool_name"),
        "tool_action": approval_context.get("tool_action"),
        "message": summary_message,
    }


def _build_clean_single_run_response(workflow: dict[str, Any]) -> dict[str, Any]:
    sources = _collect_sources_from_workflow(workflow)
    artifacts = _collect_artifacts_from_workflow(workflow)
    approval_summary = _build_approval_summary_from_workflow(workflow)

    cleaned = dict(workflow)
    cleaned["mode"] = "single_question"
    cleaned["message"] = workflow.get("final_answer")
    cleaned["sources"] = sources
    cleaned["artifacts"] = artifacts
    cleaned["approval_summary"] = approval_summary
    cleaned["meta"] = {
        "is_multi_question": False,
        "question_count": 1,
        "has_sources": bool(sources),
        "has_artifacts": bool(artifacts),
        "requires_approval": workflow.get("requires_approval", False),
    }

    return cleaned


def _normalize_multi_question_response(result: dict[str, Any]) -> dict[str, Any]:
    sub_answers = result.get("sub_answers", [])

    cleaned_sub_answers: list[dict[str, Any]] = []

    for item in sub_answers:
        raw_result = item.get("raw_result", {}) if isinstance(item, dict) else {}

        if not isinstance(raw_result, dict):
            raw_result = {}

        child_sources = item.get("sources") if isinstance(item.get("sources"), list) else []
        child_artifacts = item.get("artifacts") if isinstance(item.get("artifacts"), list) else []
        child_approval = item.get("approval_summary")

        if child_approval is None:
            child_approval = item.get("approval")

        if not child_sources and raw_result:
            child_sources = _collect_sources_from_workflow(raw_result)

        if not child_artifacts and raw_result:
            child_artifacts = _collect_artifacts_from_workflow(raw_result)

        if child_approval is None and raw_result:
            child_approval = _build_approval_summary_from_workflow(raw_result)

        cleaned_sub_answers.append(
            {
                "question_number": item.get("question_number"),
                "original_question_number": item.get("original_question_number"),
                "question": item.get("question"),
                "run_id": item.get("run_id"),
                "status": item.get("status"),
                "decision": item.get("decision"),
                "answer": item.get("answer"),
                "message": item.get("message") or item.get("answer"),
                "sources": child_sources,
                "artifacts": child_artifacts,
                "approval_summary": child_approval,
            }
        )

    top_sources = _dedupe_dict_list(
        source
        for child in cleaned_sub_answers
        for source in child.get("sources", [])
        if isinstance(source, dict)
    )

    top_artifacts = _dedupe_dict_list(
        artifact
        for child in cleaned_sub_answers
        for artifact in child.get("artifacts", [])
        if isinstance(artifact, dict)
    )

    top_approval_summary = [
        {
            "question_number": child["question_number"],
            "question": child["question"],
            "run_id": child.get("run_id"),
            "approval_summary": child["approval_summary"],
        }
        for child in cleaned_sub_answers
        if child.get("approval_summary") is not None
    ] or None

    return {
        "run_id": result.get("run_id"),
        "status": result.get("status"),
        "decision": result.get("decision"),
        "mode": "multi_question",
        "message": result.get("message") or result.get("final_answer"),
        "final_answer": result.get("final_answer") or result.get("message"),
        "sources": top_sources,
        "artifacts": top_artifacts,
        "approval_summary": top_approval_summary,
        "sub_answers": cleaned_sub_answers,
        "meta": result.get("meta", {}),
    }


def _normalize_run_response(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("meta", {}).get("is_multi_question") is True or result.get("sub_answers"):
        return _normalize_multi_question_response(result)

    if isinstance(result.get("mode"), str) and "message" in result and "final_answer" in result:
        return result

    return _build_clean_single_run_response(result)


@router.get("/overview")
async def get_aira_x_overview():
    _recover_stale_approval_processing_runs()

    workflow_metrics = WorkflowStore.get_metrics()

    return {
        "platform": "AIRA-X",
        "focus": "AI Research + Autonomous Execution",
        "status": "operational",
        "agent_count": len(AgentRegistry.list_agents()),
        "tool_count": len(ToolRegistry.list_tools()),
        "agents": AgentRegistry.describe_agents(),
        "tools": ToolRegistry.describe_tools(),
        "workflow_metrics": workflow_metrics,
    }

def _build_self_memory_response(goal: str, classification) -> dict[str, Any]:
    message = (
        "I only know what you share with me in this conversation or what I’m explicitly allowed "
        "to remember. I don’t know personal details about you unless you’ve provided them."
    )

    return {
        "run_id": str(uuid4()),
        "status": "completed",
        "decision": "self_memory_completed",
        "mode": SELF_MEMORY_MODE,
        "message": message,
        "final_answer": message,
        "sources": [],
        "artifacts": [],
        "approval_summary": None,
        "meta": {
            "is_multi_question": False,
            "question_count": 1,
            "has_sources": False,
            "has_artifacts": False,
            "requires_approval": False,
            "turn_classification": {
                "mode": classification.mode,
                "reason": classification.reason,
                "confidence": classification.confidence,
            },
        },
    }


def _build_document_qa_placeholder_response(goal: str, classification) -> dict[str, Any]:
    message = (
        "I understood this as a document-based question. The next step is to route it through "
        "document-first analysis so AIRA-X answers from uploaded files before using broader research."
    )

    return {
        "run_id": str(uuid4()),
        "status": "completed",
        "decision": "document_qa_routed",
        "mode": DOCUMENT_QA_MODE,
        "message": message,
        "final_answer": message,
        "sources": [],
        "artifacts": [],
        "approval_summary": None,
        "meta": {
            "is_multi_question": False,
            "question_count": 1,
            "has_sources": False,
            "has_artifacts": False,
            "requires_approval": False,
            "turn_classification": {
                "mode": classification.mode,
                "reason": classification.reason,
                "confidence": classification.confidence,
            },
        },
    }


def _build_web_research_placeholder_response(goal: str, classification) -> dict[str, Any]:
    message = (
        "I understood this as a research request. The next step is to connect it to the dedicated "
        "research flow so AIRA-X can gather and synthesize external information cleanly."
    )

    return {
        "run_id": str(uuid4()),
        "status": "completed",
        "decision": "web_research_routed",
        "mode": WEB_RESEARCH_MODE,
        "message": message,
        "final_answer": message,
        "sources": [],
        "artifacts": [],
        "approval_summary": None,
        "meta": {
            "is_multi_question": False,
            "question_count": 1,
            "has_sources": False,
            "has_artifacts": False,
            "requires_approval": False,
            "turn_classification": {
                "mode": classification.mode,
                "reason": classification.reason,
                "confidence": classification.confidence,
            },
        },
    }


@router.post("/run")
async def run_aira_x(request: AiraXRunRequest):
    """Thin adapter: build context, hand the turn to the supervisor, return one
    normalized response. Routing/answering logic lives in the supervisor."""
    ctx = build_turn_context(request.goal, session_id=request.session_id)
    response = await AssistantSupervisor().run_turn(ctx)
    return response.model_dump()


@router.get("/traces")
async def get_aira_x_traces(limit: int = 50):
    """Recent per-turn traces (route, latency, source type, status, events)."""
    records = TraceService().recent(limit=limit)
    return {"trace_count": len(records), "traces": records}


@router.post("/approve")
async def approve_aira_x_action(request: AiraXApproveRequest):
    approval_lock = _get_approval_lock(request.run_id)

    async with approval_lock:
        state = WorkflowStore.get(request.run_id)

        if not state:
            return {
                "success": False,
                "error": f"No workflow found for run_id: {request.run_id}",
            }

        if _recover_stale_approval_processing_state(
            state,
            ignore_active_lock=True,
        ):
            WorkflowStore.save(state)

            return _approval_not_available_response(
                state=state,
                run_id=request.run_id,
                requested_action="approved",
            )

        if _approval_is_being_processed(state):
            return _approval_processing_response(
                state=state,
                run_id=request.run_id,
                requested_action="approval",
            )

        if state.status != "requires_approval":
            return _approval_not_available_response(
                state=state,
                run_id=request.run_id,
                requested_action="approved",
            )

        pending_action = state.memory.get("pending_action")

        if not pending_action:
            return {
                "success": False,
                "error": "No pending action found for approval.",
                "run_id": request.run_id,
                "workflow": serialize_state(state),
            }

        approval_started_at = _utc_now_iso()

        state.memory["approval_in_progress"] = True
        state.memory["approval_processing_started_at"] = approval_started_at
        state.memory["approval_resolution"] = {
            "status": "approved",
            "action": pending_action,
            "requested_at": approval_started_at,
        }

        WorkflowStore.save(state)

        state.memory.setdefault("approved_actions", [])
        state.memory["approved_actions"].append(pending_action)

        WorkflowMemory.add_log(
            state,
            agent="approval_agent",
            event="approval_granted_by_user",
            details={
                "run_id": request.run_id,
                "approved_action": pending_action,
            },
        )

        current_step = next(
            (step for step in state.plan if step.id == state.current_step),
            None,
        )

        if current_step:
            current_step.status = "pending"
            current_step.error = None

        state.status = "retrying"
        state.decision = "retry_prepared"
        state.final_answer = None

        workflow = LangGraphAiraXWorkflow()

        try:
            resumed_state = await workflow.resume(state)

        except Exception as exc:
            state.status = "failed"
            state.decision = "approval_resume_failed"
            state.final_answer = f"Workflow failed after approval: {exc}"
            state.memory["approval_in_progress"] = False
            state.memory["approval_resolution"] = {
                "status": "approved_but_resume_failed",
                "action": pending_action,
                "requested_at": approval_started_at,
                "completed_at": _utc_now_iso(),
                "final_status": state.status,
                "final_decision": state.decision,
                "error": str(exc),
            }

            WorkflowMemory.add_log(
                state,
                agent="approval_agent",
                event="approval_resume_failed",
                details={
                    "run_id": request.run_id,
                    "approved_action": pending_action,
                    "error": str(exc),
                },
            )

            WorkflowStore.save(state)

            return serialize_state(state)

        resumed_state.memory["approval_in_progress"] = False
        resumed_state.memory["approval_resolution"] = {
            "status": "approved",
            "action": pending_action,
            "requested_at": approval_started_at,
            "completed_at": _utc_now_iso(),
            "final_status": resumed_state.status,
            "final_decision": resumed_state.decision,
        }

        WorkflowStore.save(resumed_state)

        return serialize_state(resumed_state)


@router.post("/reject")
async def reject_aira_x_action(request: AiraXRejectRequest):
    approval_lock = _get_approval_lock(request.run_id)

    async with approval_lock:
        state = WorkflowStore.get(request.run_id)

        if not state:
            return {
                "success": False,
                "error": f"No workflow found for run_id: {request.run_id}",
            }

        if _recover_stale_approval_processing_state(
            state,
            ignore_active_lock=True,
        ):
            WorkflowStore.save(state)

            return _approval_not_available_response(
                state=state,
                run_id=request.run_id,
                requested_action="rejected",
            )

        if _approval_is_being_processed(state):
            return _approval_processing_response(
                state=state,
                run_id=request.run_id,
                requested_action="rejection",
            )

        if state.status != "requires_approval":
            return _approval_not_available_response(
                state=state,
                run_id=request.run_id,
                requested_action="rejected",
            )

        pending_action = state.memory.get("pending_action")

        if not pending_action:
            return {
                "success": False,
                "error": "No pending action found for rejection.",
                "run_id": request.run_id,
                "workflow": serialize_state(state),
            }

        approval_started_at = _utc_now_iso()

        state.memory["approval_in_progress"] = True
        state.memory["approval_processing_started_at"] = approval_started_at
        state.memory["approval_resolution"] = {
            "status": "rejected",
            "action": pending_action,
            "requested_at": approval_started_at,
        }

        WorkflowStore.save(state)

        current_step = next(
            (step for step in state.plan if step.id == state.current_step),
            None,
        )

        cleanup_result = None

        if _should_cleanup_staged_changes_after_rejection(state):
            cleanup_result = _cleanup_staged_changes_after_rejection(state)

        rejection_message = f"User rejected the action: {pending_action}."

        if cleanup_result:
            if cleanup_result.get("success"):
                rejection_message += (
                    " AIRA-X also unstaged changes that it staged for this workflow."
                )
            else:
                rejection_message += (
                    " AIRA-X attempted to unstage changes, but cleanup failed."
                )

        if current_step:
            current_step.status = "rejected"
            current_step.error = rejection_message

        state.status = "rejected"
        state.decision = "approval_rejected"
        state.final_answer = rejection_message

        WorkflowMemory.add_log(
            state,
            agent="approval_agent",
            event="approval_rejected_by_user",
            details={
                "run_id": request.run_id,
                "rejected_action": pending_action,
                "cleanup_attempted": cleanup_result is not None,
            },
        )

        WorkflowMemory.add_log(
            state,
            agent="aira_x_workflow",
            event="workflow_stopped_after_rejection",
            details={
                "final_answer": rejection_message,
            },
        )

        memory_agent = MemoryAgent()
        state = await memory_agent.run(state)

        state.memory["approval_in_progress"] = False
        state.memory["approval_resolution"] = {
            "status": "rejected",
            "action": pending_action,
            "requested_at": approval_started_at,
            "completed_at": _utc_now_iso(),
            "final_status": state.status,
            "final_decision": state.decision,
        }

        WorkflowStore.save(state)

        return serialize_state(state)


@router.get("/runs")
async def list_aira_x_runs():
    _recover_stale_approval_processing_runs()

    return {
        "run_count": len(WorkflowStore.list_runs()),
        "runs": WorkflowStore.list_runs(),
    }


@router.get("/runs/{run_id}")
async def get_aira_x_run(run_id: str):
    state = WorkflowStore.get(run_id)

    if not state:
        return {
            "success": False,
            "error": f"No workflow found for run_id: {run_id}",
        }

    if _recover_stale_approval_processing_state(state):
        WorkflowStore.save(state)

    return {
        "success": True,
        "run": serialize_state(state),
    }


@router.delete("/runs/maintenance/safe")
async def delete_safe_aira_x_runs():
    _recover_stale_approval_processing_runs()

    deleted_runs = []
    skipped_runs = []

    for run_summary in WorkflowStore.list_runs():
        run_id = run_summary.get("run_id")

        if not run_id:
            continue

        state = WorkflowStore.get(run_id)

        if not state:
            continue

        if _recover_stale_approval_processing_state(state):
            WorkflowStore.save(state)

        if _workflow_is_safe_bulk_delete_candidate(state):
            deleted_runs.append(_summarize_workflow_for_delete(state))
            WorkflowStore.delete(run_id)
            _remove_inactive_approval_lock(run_id)
            continue

        skipped_runs.append(
            {
                "run_id": run_id,
                "user_goal": state.user_goal,
                "status": state.status,
                "decision": state.decision,
                "reason": _safe_bulk_delete_skip_reason(state),
                "created_at": state.created_at,
                "updated_at": state.updated_at,
                "completed_at": state.completed_at,
                "approval_in_progress": state.memory.get(
                    "approval_in_progress",
                    False,
                ),
            }
        )

    return {
        "success": True,
        "deleted_count": len(deleted_runs),
        "skipped_count": len(skipped_runs),
        "deleted_runs": deleted_runs,
        "skipped_runs": skipped_runs,
        "remaining_run_count": len(WorkflowStore.list_runs()),
        "safe_statuses": sorted(_SAFE_BULK_DELETE_STATUSES),
    }


@router.delete("/runs/{run_id}")
async def delete_aira_x_run(run_id: str):
    state = WorkflowStore.get(run_id)

    if not state:
        return {
            "success": False,
            "error": f"No workflow found for run_id: {run_id}",
            "run_id": run_id,
        }

    if _recover_stale_approval_processing_state(state):
        WorkflowStore.save(state)

    if not _workflow_can_be_deleted(state):
        return _workflow_delete_blocked_response(state, run_id)

    deleted_summary = _summarize_workflow_for_delete(state)

    WorkflowStore.delete(run_id)
    _remove_inactive_approval_lock(run_id)

    return {
        "success": True,
        "deleted_run_id": run_id,
        "deleted_run": deleted_summary,
        "remaining_run_count": len(WorkflowStore.list_runs()),
    }


@router.get("/tools")
async def list_aira_x_tools():
    return {
        "tool_count": len(ToolRegistry.list_tools()),
        "tools": ToolRegistry.describe_tools(),
    }


@router.get("/tools/{tool_name}")
async def get_aira_x_tool(tool_name: str):
    tool = ToolRegistry.get_tool(tool_name)

    if not tool:
        return {
            "success": False,
            "error": f"Tool '{tool_name}' does not exist.",
        }

    return {
        "success": True,
        "tool_name": tool_name,
        "tool": tool,
    }


@router.get("/agents")
async def list_aira_x_agents():
    return {
        "agent_count": len(AgentRegistry.list_agents()),
        "agents": AgentRegistry.describe_agents(),
    }


@router.get("/agents/{agent_name}")
async def get_aira_x_agent(agent_name: str):
    agent = AgentRegistry.get_agent(agent_name)

    if not agent:
        return {
            "success": False,
            "error": f"Agent '{agent_name}' does not exist.",
        }

    return {
        "success": True,
        "agent_name": agent_name,
        "agent": agent,
    }