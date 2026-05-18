from agents.base_agent import BaseAgent
from schemas.aira_state import AiraXState
from memory.workflow_memory import WorkflowMemory


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
        "remove-item -recurse",
    ]

    async def run(self, state: AiraXState) -> AiraXState:
        action = state.memory.get("pending_action", "")
        tool_policy = state.memory.get("current_tool_policy", {})

        WorkflowMemory.add_log(
            state,
            agent=self.name,
            event="safety_check_started",
            details={
                "action": action,
                "tool_policy": tool_policy,
            },
        )

        risk_level = tool_policy.get("risk_level")

        if risk_level == "dangerous":
            state.status = "failed"
            state.decision = "blocked_by_safety_agent"
            state.final_answer = f"Unsafe action blocked by policy: {action}"

            WorkflowMemory.add_log(
                state,
                agent=self.name,
                event="safety_blocked_action",
                details={
                    "action": action,
                    "reason": "Tool policy marked this action as dangerous.",
                    "risk_level": risk_level,
                },
            )

            return state

        for pattern in self.blocked_patterns:
            if pattern.lower() in action.lower():
                state.status = "failed"
                state.decision = "blocked_by_safety_agent"
                state.final_answer = f"Unsafe action blocked: {action}"

                WorkflowMemory.add_log(
                    state,
                    agent=self.name,
                    event="safety_blocked_action",
                    details={
                        "action": action,
                        "blocked_pattern": pattern,
                    },
                )

                return state

        state.decision = "safety_approved"

        WorkflowMemory.add_log(
            state,
            agent=self.name,
            event="safety_approved",
            details={
                "action": action,
                "risk_level": risk_level,
            },
        )

        return state