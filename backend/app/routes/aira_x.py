from uuid import uuid4
from datetime import datetime, timezone

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


class AiraXRunRequest(BaseModel):
    goal: str


class AiraXApproveRequest(BaseModel):
    run_id: str


class AiraXRejectRequest(BaseModel):
    run_id: str


def serialize_state(state):
    return {
        "run_id": state.run_id,
        "status": state.status,
        "decision": state.decision,
        "final_answer": state.final_answer,
        "plan": [step.model_dump() for step in state.plan],
        "execution_outputs": state.execution_outputs,
        "memory": state.memory,
        "workflow_logs": state.memory.get("workflow_logs", []),
        "workflow_summary": state.memory.get("workflow_summary", {}),
        "requires_approval": state.status == "requires_approval",
        "pending_action": state.memory.get("pending_action"),
        "approval_context": state.memory.get("approval_context", {}),
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _approval_is_being_processed(state) -> bool:
    return state.memory.get("approval_in_progress") is True


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
    state = WorkflowStore.get(request.run_id)

    if not state:
        return {
            "success": False,
            "error": f"No workflow found for run_id: {request.run_id}",
        }

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

    state.memory["approval_in_progress"] = True
    state.memory["approval_resolution"] = {
        "status": "approved",
        "action": pending_action,
        "requested_at": _utc_now_iso(),
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
            "completed_at": _utc_now_iso(),
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
        "completed_at": _utc_now_iso(),
        "final_status": resumed_state.status,
        "final_decision": resumed_state.decision,
    }

    WorkflowStore.save(resumed_state)

    return serialize_state(resumed_state)


@router.post("/reject")
async def reject_aira_x_action(request: AiraXRejectRequest):
    state = WorkflowStore.get(request.run_id)

    if not state:
        return {
            "success": False,
            "error": f"No workflow found for run_id: {request.run_id}",
        }

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

    state.memory["approval_in_progress"] = True
    state.memory["approval_resolution"] = {
        "status": "rejected",
        "action": pending_action,
        "requested_at": _utc_now_iso(),
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
        "completed_at": _utc_now_iso(),
        "final_status": state.status,
        "final_decision": state.decision,
    }

    WorkflowStore.save(state)

    return serialize_state(state)


@router.get("/runs")
async def list_aira_x_runs():
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

    return {
        "success": True,
        "run": serialize_state(state),
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