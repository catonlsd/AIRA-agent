from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel

from graph.aira_workflow import AiraXWorkflow
from tools.tool_registry import ToolRegistry
from memory.workflow_store import WorkflowStore


router = APIRouter(prefix="/aira-x", tags=["AIRA-X"])


class AiraXRunRequest(BaseModel):
    goal: str


class AiraXApproveRequest(BaseModel):
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
    }


@router.post("/run")
async def run_aira_x(request: AiraXRunRequest):
    run_id = str(uuid4())

    workflow = AiraXWorkflow()
    state = await workflow.run(request.goal, run_id=run_id)

    if state.status == "requires_approval":
        WorkflowStore.save(state)

    return serialize_state(state)


@router.post("/approve")
async def approve_aira_x_action(request: AiraXApproveRequest):
    state = WorkflowStore.get(request.run_id)

    if not state:
        return {
            "success": False,
            "error": f"No pending workflow found for run_id: {request.run_id}",
        }

    pending_action = state.memory.get("pending_action")

    if not pending_action:
        return {
            "success": False,
            "error": "No pending action found for approval.",
        }

    state.memory.setdefault("approved_actions", [])
    state.memory["approved_actions"].append(pending_action)

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
    resumed_state = await workflow.resume(state)

    if resumed_state.status != "requires_approval":
        WorkflowStore.delete(request.run_id)
    else:
        WorkflowStore.save(resumed_state)

    return serialize_state(resumed_state)


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