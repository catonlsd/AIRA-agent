from agents.base_agent import BaseAgent
from schemas.aira_state import AiraXState
from memory.workflow_memory import WorkflowMemory


class ApprovalAgent(BaseAgent):
    name = "approval_agent"
    description = "Detects actions that require explicit user approval before execution."

    approval_required_patterns = [
        "pip install",
        "pip uninstall",
        "npm install",
        "npm uninstall",
        "git add",
        "git commit",
        "git push",
        "git reset",
        "docker build",
        "docker run",
        "docker compose",
        "deploy",
        "vercel",
        "render",
        "railway",
    ]

    async def run(self, state: AiraXState) -> AiraXState:
        action = state.memory.get("pending_action", "")
        approved_actions = state.memory.get("approved_actions", [])

        WorkflowMemory.add_log(
            state,
            agent=self.name,
            event="approval_check_started",
            details={"action": action},
        )

        if action in approved_actions:
            state.decision = "approval_not_required"

            WorkflowMemory.add_log(
                state,
                agent=self.name,
                event="approval_already_granted",
                details={"action": action},
            )

            return state

        for pattern in self.approval_required_patterns:
            if pattern.lower() in action.lower():
                state.status = "requires_approval"
                state.decision = "approval_required"
                state.final_answer = (
                    "This action requires user approval before execution: "
                    f"{action}"
                )

                WorkflowMemory.add_log(
                    state,
                    agent=self.name,
                    event="approval_required",
                    details={
                        "action": action,
                        "matched_pattern": pattern,
                    },
                )

                return state

        state.decision = "approval_not_required"

        WorkflowMemory.add_log(
            state,
            agent=self.name,
            event="approval_not_required",
            details={"action": action},
        )

        return state