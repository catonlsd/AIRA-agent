from fastapi import APIRouter
from pydantic import BaseModel

from graph.aira_workflow import AiraXWorkflow


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
    }