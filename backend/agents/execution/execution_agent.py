from datetime import datetime
from typing import Dict, Any

from agents.base_agent import BaseAgent
from schemas.aira_state import AiraXState
from tools.tool_router import ToolRouter
from tools.tool_registry import ToolRegistry
from agents.safety.safety_agent import SafetyAgent
from agents.approval.approval_agent import ApprovalAgent
from memory.workflow_memory import WorkflowMemory


class ExecutionAgent(BaseAgent):
    name = "execution_agent"
    description = "Executes workflow steps using dynamically selected tools."

    async def run(self, state: AiraXState) -> AiraXState:
        if state.current_step is None:
            state.decision = "no_step_to_execute"
            state.status = "failed"
            return state

        current_step = next(
            (step for step in state.plan if step.id == state.current_step),
            None,
        )

        if current_step is None:
            state.decision = "step_not_found"
            state.status = "failed"
            return state

        current_step.status = "running"

        if not current_step.tool_name or not current_step.tool_action:
            current_step.status = "failed"
            current_step.error = "No tool assigned to this execution step."
            state.status = "failed"
            state.decision = "execution_failed"
            state.memory["last_execution_error"] = current_step.error
            return state

        tool_policy = ToolRegistry.get_action_policy(
            current_step.tool_name,
            current_step.tool_action,
        )

        WorkflowMemory.add_log(
            state,
            agent=self.name,
            event="execution_started",
            details={
                "step_id": current_step.id,
                "step_title": current_step.title,
                "retry_count": state.retry_count,
                "tool_name": current_step.tool_name,
                "tool_action": current_step.tool_action,
                "tool_policy": tool_policy,
            },
        )

        WorkflowMemory.add_log(
            state,
            agent=self.name,
            event="tool_policy_checked",
            details={
                "tool_name": current_step.tool_name,
                "tool_action": current_step.tool_action,
                "risk_level": tool_policy.get("risk_level"),
                "requires_approval": tool_policy.get("requires_approval"),
                "description": tool_policy.get("description"),
            },
        )

        if "run retry demo command" in current_step.title.lower():
            if state.retry_count == 0:
                current_step.tool_payload = {
                    "command": "non_existing_command_for_retry_demo"
                }
            else:
                current_step.tool_payload = {
                    "command": "echo AIRA-X self-correction retry succeeded"
                }

        pending_action = self._build_pending_action(
            current_step.tool_name,
            current_step.tool_action,
            current_step.tool_payload,
        )

        state.memory["pending_action"] = pending_action
        state.memory["current_tool_policy"] = tool_policy
        state.memory["approval_context"] = self._build_approval_context(
            tool_name=current_step.tool_name,
            action=current_step.tool_action,
            payload=current_step.tool_payload,
            pending_action=pending_action,
        )

        safety = SafetyAgent()
        state = await safety.run(state)

        if state.decision == "blocked_by_safety_agent":
            current_step.status = "failed"
            current_step.error = state.final_answer
            state.memory["last_execution_error"] = current_step.error

            WorkflowMemory.add_log(
                state,
                agent=self.name,
                event="execution_blocked_by_safety",
                details={
                    "step_id": current_step.id,
                    "action": pending_action,
                },
            )

            return state

        approval = ApprovalAgent()
        state = await approval.run(state)

        if state.decision == "approval_required":
            current_step.status = "blocked"
            current_step.error = state.final_answer

            WorkflowMemory.add_log(
                state,
                agent=self.name,
                event="execution_waiting_for_approval",
                details={
                    "step_id": current_step.id,
                    "action": pending_action,
                    "approval_context": state.memory.get("approval_context", {}),
                },
            )

            return state

        tool_result = ToolRouter.run(
            tool_name=current_step.tool_name,
            action=current_step.tool_action,
            payload=current_step.tool_payload,
        )

        output = {
            "step_id": current_step.id,
            "agent": self.name,
            "timestamp": datetime.utcnow().isoformat(),
            "tool_used": current_step.tool_name,
            "tool_action": current_step.tool_action,
            "tool_policy": tool_policy,
            "safety_decision": "approved",
            "approval_decision": "not_required",
            "tool_result": tool_result,
        }

        state.execution_outputs.append(output)

        if tool_result.get("success"):
            raw_output = tool_result.get("output")

            if isinstance(raw_output, list):
                current_step.result = "\n".join(raw_output)

            elif raw_output:
                current_step.result = str(raw_output).strip()

            else:
                current_step.result = "Execution completed successfully."

            current_step.status = "completed"
            state.status = "executing"
            state.decision = "execution_completed"

            WorkflowMemory.add_log(
                state,
                agent=self.name,
                event="execution_success",
                details={
                    "step_id": current_step.id,
                    "tool_used": current_step.tool_name,
                    "tool_action": current_step.tool_action,
                    "risk_level": tool_policy.get("risk_level"),
                    "result": current_step.result,
                },
            )

        else:
            current_step.error = (
                tool_result.get("stderr")
                or tool_result.get("error")
                or tool_result.get("output")
                or "Tool execution failed."
            )

            current_step.status = "failed"
            state.status = "failed"
            state.decision = "execution_failed"
            state.memory["last_execution_error"] = current_step.error

            WorkflowMemory.add_log(
                state,
                agent=self.name,
                event="execution_failed",
                details={
                    "step_id": current_step.id,
                    "tool_used": current_step.tool_name,
                    "tool_action": current_step.tool_action,
                    "risk_level": tool_policy.get("risk_level"),
                    "error": current_step.error,
                },
            )

        return state

    def _build_pending_action(self, tool_name: str, action: str, payload: dict) -> str:
        if tool_name == "shell_tool":
            return payload.get("command", "")

        if tool_name == "python_tool":
            return f"python_code: {payload.get('code', '')}"

        if tool_name == "file_tool":
            return f"{action}: {payload.get('path', '')}"

        if tool_name == "git_tool":
            if action == "commit":
                return (
                    "git_tool:commit -m "
                    f"{payload.get('message', 'AIRA-X automated commit')}"
                )

            return f"git_tool:{action}"

        return f"{tool_name}:{action}"

    def _build_approval_context(
        self,
        tool_name: str,
        action: str,
        payload: Dict[str, Any],
        pending_action: str,
    ) -> Dict[str, Any]:
        if tool_name == "git_tool" and action in {"stage_all", "commit"}:
            branch_result = ToolRouter.run(
                tool_name="git_tool",
                action="branch",
                payload={},
            )

            status_result = ToolRouter.run(
                tool_name="git_tool",
                action="status",
                payload={},
            )

            diff_result = ToolRouter.run(
                tool_name="git_tool",
                action="diff",
                payload={},
            )

            return {
                "type": "git_write_preflight",
                "tool_name": tool_name,
                "tool_action": action,
                "pending_action": pending_action,
                "commit_message": payload.get("message"),
                "branch": branch_result.get("output", ""),
                "changed_files": status_result.get("output", ""),
                "diff_summary": diff_result.get("output", ""),
                "branch_success": branch_result.get("success", False),
                "status_success": status_result.get("success", False),
                "diff_success": diff_result.get("success", False),
            }

        return {
            "type": "generic_action",
            "tool_name": tool_name,
            "tool_action": action,
            "pending_action": pending_action,
        }