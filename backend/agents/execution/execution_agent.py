from datetime import datetime

from agents.base_agent import BaseAgent
from schemas.aira_state import AiraXState
from tools.tool_router import ToolRouter


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

        tool_used = "shell_tool"

        if "list project files" in current_step.title.lower():
            tool_used = "shell_tool"
            tool_result = ToolRouter.run(
                tool_name="shell_tool",
                action="run",
                payload={"command": "dir"},
            )

        elif "create a test file" in current_step.title.lower():
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
            tool_used = "python_tool"
            tool_result = ToolRouter.run(
                tool_name="python_tool",
                action="run_code",
                payload={
                    "code": "print('AIRA-X executed Python code successfully')"
                },
            )

        else:
            tool_used = "shell_tool"
            tool_result = ToolRouter.run(
                tool_name="shell_tool",
                action="run",
                payload={"command": "echo AIRA-X dynamic execution working"},
            )

        output = {
            "step_id": current_step.id,
            "agent": self.name,
            "timestamp": datetime.utcnow().isoformat(),
            "tool_used": tool_used,
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

        else:
            current_step.error = tool_result.get("stderr") or tool_result.get("error")
            current_step.status = "failed"
            state.status = "failed"
            state.decision = "execution_failed"

        return state