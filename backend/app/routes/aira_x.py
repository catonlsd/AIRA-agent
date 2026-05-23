import asyncio
from uuid import uuid4
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from graph.aira_workflow import AiraXWorkflow
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
        "Approval processing became stale before completion. "
        "AIRA-X stopped this workflow to prevent duplicate execution. "
        "Review the workflow state before running the action again."
    )

    current_step = next(
        (step for step in state.plan if step.id == state.current_step),
        None,
    )

    if current_step:
        current_step.status = "failed"
        current_step.error = recovery_message

    state.status = "failed"
    state.decision = "approval_processing_stale"
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


@router.post("/run")
async def run_aira_x(request: AiraXRunRequest):
    run_id = str(uuid4())

    workflow = AiraXWorkflow()
    state = await workflow.run(request.goal, run_id=run_id)

    WorkflowStore.save(state)

    return serialize_state(state)


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

        workflow = AiraXWorkflow()

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
