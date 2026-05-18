from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel

from graph.aira_workflow import AiraXWorkflow
from tools.tool_registry import ToolRegistry
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
    }


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

    if state.status != "requires_approval":
        return {
            "success": False,
            "error": f"Workflow is not waiting for approval. Current status: {state.status}",
        }

    pending_action = state.memory.get("pending_action")

    if not pending_action:
        return {
            "success": False,
            "error": "No pending action found for approval.",
        }

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
    resumed_state = await workflow.resume(state)

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

    if state.status != "requires_approval":
        return {
            "success": False,
            "error": f"Workflow is not waiting for rejection. Current status: {state.status}",
        }

    pending_action = state.memory.get("pending_action")

    if not pending_action:
        return {
            "success": False,
            "error": "No pending action found for rejection.",
        }

    current_step = next(
        (step for step in state.plan if step.id == state.current_step),
        None,
    )

    rejection_message = f"User rejected the action: {pending_action}"

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