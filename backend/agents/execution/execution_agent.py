from datetime import datetime

from agents.base_agent import BaseAgent
from schemas.aira_state import AiraXState
from tools.tool_router import ToolRouter
from agents.safety.safety_agent import SafetyAgent
from memory.workflow_memory import WorkflowMemory


class ExecutionAgent(BaseAgent):
    name = "execution_agent"
    description = "Executes workflow steps using available tools."

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

        WorkflowMemory.add_log(
            state,
            agent=self.name,
            event="execution_started",
            details={
                "step_id": current_step.id,
                "step_title": current_step.title,
                "retry_count": state.retry_count,
            },
        )

        safety = SafetyAgent()
        tool_used = "shell_tool"

        if "list project files" in current_step.title.lower():
            pending_action = "dir"
            state.memory["pending_action"] = pending_action

            state = await safety.run(state)
            if state.decision == "blocked_by_safety_agent":
                current_step.status = "failed"
                current_step.error = state.final_answer
                return state

            tool_used = "shell_tool"
            tool_result = ToolRouter.run(
                tool_name="shell_tool",
                action="run",
                payload={"command": pending_action},
            )

        elif "create a test file" in current_step.title.lower():
            pending_action = "write_file: tmp/aira_x_generated.txt"
            state.memory["pending_action"] = pending_action

            state = await safety.run(state)
            if state.decision == "blocked_by_safety_agent":
                current_step.status = "failed"
                current_step.error = state.final_answer
                return state

            tool_used = "file_tool"
            tool_result = ToolRouter.run(
                tool_name="file_tool",
                action="write_file",
                payload={
                    "path": "tmp/aira_x_generated.txt",
                    "content": "AIRA-X autonomously created this file.",
                },
            )

        elif "run python code" in current_step.title.lower():
            pending_action = "python_code: print('AIRA-X executed Python code successfully')"
            state.memory["pending_action"] = pending_action

            state = await safety.run(state)
            if state.decision == "blocked_by_safety_agent":
                current_step.status = "failed"
                current_step.error = state.final_answer
                return state

            tool_used = "python_tool"
            tool_result = ToolRouter.run(
                tool_name="python_tool",
                action="run_code",
                payload={
                    "code": "print('AIRA-X executed Python code successfully')"
                },
            )

        elif "run retry demo command" in current_step.title.lower():
            if state.retry_count == 0:
                pending_action = "non_existing_command_for_retry_demo"
            else:
                pending_action = "echo AIRA-X self-correction retry succeeded"

            state.memory["pending_action"] = pending_action

            state = await safety.run(state)
            if state.decision == "blocked_by_safety_agent":
                current_step.status = "failed"
                current_step.error = state.final_answer
                return state

            tool_used = "shell_tool"
            tool_result = ToolRouter.run(
                tool_name="shell_tool",
                action="run",
                payload={"command": pending_action},
            )

        else:
            pending_action = "echo AIRA-X dynamic execution working"
            state.memory["pending_action"] = pending_action

            state = await safety.run(state)
            if state.decision == "blocked_by_safety_agent":
                current_step.status = "failed"
                current_step.error = state.final_answer
                return state

            tool_used = "shell_tool"
            tool_result = ToolRouter.run(
                tool_name="shell_tool",
                action="run",
                payload={"command": pending_action},
            )

        output = {
            "step_id": current_step.id,
            "agent": self.name,
            "timestamp": datetime.utcnow().isoformat(),
            "tool_used": tool_used,
            "safety_decision": "approved",
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
                    "tool_used": tool_used,
                    "result": current_step.result,
                },
            )

        else:
            current_step.error = tool_result.get("stderr") or tool_result.get("error")
            current_step.status = "failed"
            state.status = "failed"
            state.decision = "execution_failed"

            WorkflowMemory.add_log(
                state,
                agent=self.name,
                event="execution_failed",
                details={
                    "step_id": current_step.id,
                    "tool_used": tool_used,
                    "error": current_step.error,
                },
            )

        return state