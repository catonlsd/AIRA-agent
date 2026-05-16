from agents.base_agent import BaseAgent
from schemas.aira_state import AiraXState


class SafetyAgent(BaseAgent):
    name = "safety_agent"
    description = "Checks whether an action or command is safe before execution."

    blocked_patterns = [
        "rm -rf",
        "del /s",
        "format",
        "shutdown",
        "restart",
        "taskkill",
        "reg delete",
        "Remove-Item -Recurse",
    ]

    async def run(self, state: AiraXState) -> AiraXState:
        action = state.memory.get("pending_action", "")

        for pattern in self.blocked_patterns:
            if pattern.lower() in action.lower():
                state.status = "failed"
                state.decision = "blocked_by_safety_agent"
                state.final_answer = f"Unsafe action blocked: {action}"
                return state

        state.decision = "safety_approved"
        return state