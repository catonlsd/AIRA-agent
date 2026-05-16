from fastapi import APIRouter
from pydantic import BaseModel

from graph.aira_workflow import AiraXWorkflow
from tools.tool_registry import ToolRegistry


router = APIRouter(prefix="/aira-x", tags=["AIRA-X"])


class AiraXRunRequest(BaseModel):
    goal: str


@router.post("/run")
async def run_aira_x(request: AiraXRunRequest):
    workflow = AiraXWorkflow()
    state = await workflow.run(request.goal)

    return {
        "status": state.status,
        "decision": state.decision,
        "final_answer": state.final_answer,
        "plan": [step.model_dump() for step in state.plan],
        "execution_outputs": state.execution_outputs,
        "memory": state.memory,
        "workflow_logs": state.memory.get("workflow_logs", []),
        "workflow_summary": state.memory.get("workflow_summary", {}),
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