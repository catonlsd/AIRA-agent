from agents.base_agent import BaseAgent
from schemas.aira_state import AiraXState
from memory.workflow_memory import WorkflowMemory


class MemoryAgent(BaseAgent):
    name = "memory_agent"
    description = "Summarizes and stores workflow memory."

    async def run(self, state: AiraXState) -> AiraXState:
        completed_steps = [
            {
                "id": step.id,
                "title": step.title,
                "status": step.status,
                "assigned_agent": step.assigned_agent,
                "result": step.result,
                "error": step.error,
            }
            for step in state.plan
        ]

        memory_summary = {
            "user_goal": state.user_goal,
            "final_status": state.status,
            "final_decision": state.decision,
            "final_answer": state.final_answer,
            "retry_count": state.retry_count,
            "steps": completed_steps,
            "tool_calls_count": len(state.execution_outputs),
            "reflection_count": len(state.memory.get("reflections", [])),
        }

        state.memory["workflow_summary"] = memory_summary

        WorkflowMemory.add_log(
            state,
            agent=self.name,
            event="memory_summary_created",
            details=memory_summary,
        )

        return state