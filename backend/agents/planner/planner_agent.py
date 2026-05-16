from agents.base_agent import BaseAgent
from schemas.aira_state import AiraXState, AiraXStep
from memory.workflow_memory import WorkflowMemory


class PlannerAgent(BaseAgent):
    name = "planner_agent"
    description = "Breaks user goals into executable tool-ready steps."

    async def run(self, state: AiraXState) -> AiraXState:
        state.status = "planning"

        WorkflowMemory.add_log(
            state,
            agent=self.name,
            event="planning_started",
            details={"user_goal": state.user_goal},
        )

        goal = state.user_goal.lower()
        plan = []

        if "list files" in goal:
            plan.append(
                AiraXStep(
                    id=1,
                    title="List project files",
                    description="List files in the backend directory.",
                    assigned_agent="execution_agent",
                    tool_name="shell_tool",
                    tool_action="run",
                    tool_payload={"command": "dir"},
                )
            )

        elif "create file" in goal:
            plan.append(
                AiraXStep(
                    id=1,
                    title="Create a test file",
                    description="Create a new file using the filesystem tool.",
                    assigned_agent="execution_agent",
                    tool_name="file_tool",
                    tool_action="write_file",
                    tool_payload={
                        "path": "tmp/aira_x_generated.txt",
                        "content": "AIRA-X autonomously created this file.",
                    },
                )
            )

        elif "run python" in goal or "python code" in goal:
            plan.append(
                AiraXStep(
                    id=1,
                    title="Run Python code",
                    description="Execute Python code using the Python tool.",
                    assigned_agent="execution_agent",
                    tool_name="python_tool",
                    tool_action="run_code",
                    tool_payload={
                        "code": "print('AIRA-X executed Python code successfully')"
                    },
                )
            )

        elif "git status" in goal:
            plan.append(
                AiraXStep(
                    id=1,
                    title="Check Git status",
                    description="Check current repository status using the Git tool.",
                    assigned_agent="execution_agent",
                    tool_name="git_tool",
                    tool_action="status",
                    tool_payload={},
                )
            )

        elif "git branch" in goal:
            plan.append(
                AiraXStep(
                    id=1,
                    title="Check Git branch",
                    description="Check current Git branch using the Git tool.",
                    assigned_agent="execution_agent",
                    tool_name="git_tool",
                    tool_action="branch",
                    tool_payload={},
                )
            )

        elif "git log" in goal or "recent commits" in goal:
            plan.append(
                AiraXStep(
                    id=1,
                    title="Show recent Git commits",
                    description="Show recent commits using the Git tool.",
                    assigned_agent="execution_agent",
                    tool_name="git_tool",
                    tool_action="recent_commits",
                    tool_payload={"limit": 5},
                )
            )

        elif "rm -rf" in goal or "delete system32" in goal or "format disk" in goal:
            plan.append(
                AiraXStep(
                    id=1,
                    title="Run dangerous command",
                    description="Attempt dangerous command execution.",
                    assigned_agent="execution_agent",
                    tool_name="shell_tool",
                    tool_action="run",
                    tool_payload={"command": "rm -rf /"},
                )
            )

        elif "test retry" in goal or "retry demo" in goal:
            plan.append(
                AiraXStep(
                    id=1,
                    title="Run retry demo command",
                    description="Intentionally fail once, then self-correct and retry.",
                    assigned_agent="execution_agent",
                    tool_name="shell_tool",
                    tool_action="run",
                    tool_payload={"command": "non_existing_command_for_retry_demo"},
                )
            )

        else:
            plan = [
                AiraXStep(
                    id=1,
                    title="Understand user goal",
                    description=f"Analyze the task: {state.user_goal}",
                    assigned_agent="planner_agent",
                ),
                AiraXStep(
                    id=2,
                    title="Decide execution path",
                    description="Determine which agent should act next.",
                    assigned_agent="decision_agent",
                ),
                AiraXStep(
                    id=3,
                    title="Execute task",
                    description="Perform the required action using tools or execution.",
                    assigned_agent="execution_agent",
                    tool_name="shell_tool",
                    tool_action="run",
                    tool_payload={"command": "echo AIRA-X dynamic execution working"},
                ),
                AiraXStep(
                    id=4,
                    title="Validate result",
                    description="Check whether the task was completed successfully.",
                    assigned_agent="validation_agent",
                ),
            ]

        state.plan = plan
        state.current_step = 1
        state.decision = "plan_created"

        WorkflowMemory.add_log(
            state,
            agent=self.name,
            event="plan_created",
            details={
                "steps": [
                    {
                        "id": step.id,
                        "title": step.title,
                        "assigned_agent": step.assigned_agent,
                        "tool_name": step.tool_name,
                        "tool_action": step.tool_action,
                    }
                    for step in state.plan
                ]
            },
        )

        return state