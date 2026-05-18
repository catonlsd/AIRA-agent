from typing import Dict, Any, List


class AgentRegistry:
    name = "agent_registry"

    agents: Dict[str, Dict[str, Any]] = {
        "planner_agent": {
            "role": "Planning",
            "description": "Breaks user goals into executable, tool-ready workflow steps.",
            "responsibilities": [
                "Understand user goal",
                "Create execution plan",
                "Assign tools and actions",
                "Prepare structured workflow steps",
            ],
        },
        "decision_agent": {
            "role": "Routing and Control",
            "description": "Determines the next action in the workflow state machine.",
            "responsibilities": [
                "Route workflow between agents",
                "Handle retry decisions",
                "Stop unsafe workflows",
                "Move workflows toward validation and completion",
            ],
        },
        "execution_agent": {
            "role": "Execution",
            "description": "Executes workflow steps using tools selected by the planner.",
            "responsibilities": [
                "Run tool-based actions",
                "Call Safety Agent before execution",
                "Call Approval Agent for sensitive actions",
                "Record execution outputs",
            ],
        },
        "safety_agent": {
            "role": "Safety",
            "description": "Blocks dangerous or destructive actions before they execute.",
            "responsibilities": [
                "Inspect pending actions",
                "Block unsafe commands",
                "Prevent retrying dangerous actions",
                "Log safety decisions",
            ],
        },
        "approval_agent": {
            "role": "Human Approval",
            "description": "Pauses sensitive actions until the user explicitly approves or rejects them.",
            "responsibilities": [
                "Detect approval-required actions",
                "Pause workflow execution",
                "Resume approved workflows",
                "Stop rejected workflows safely",
            ],
        },
        "validation_agent": {
            "role": "Validation",
            "description": "Verifies whether execution produced a successful result.",
            "responsibilities": [
                "Check execution output",
                "Mark validation success",
                "Mark validation failure",
                "Log validation results",
            ],
        },
        "reflection_agent": {
            "role": "Self-Correction",
            "description": "Analyzes recoverable failures and prepares retry attempts.",
            "responsibilities": [
                "Analyze failed steps",
                "Create retry notes",
                "Increment retry count",
                "Reset recoverable steps for retry",
            ],
        },
        "memory_agent": {
            "role": "Memory",
            "description": "Summarizes workflow execution and stores structured workflow memory.",
            "responsibilities": [
                "Create workflow summaries",
                "Store final workflow state",
                "Count tool calls and reflections",
                "Preserve execution history",
            ],
        },
    }

    @classmethod
    def list_agents(cls) -> Dict[str, Dict[str, Any]]:
        return cls.agents

    @classmethod
    def get_agent(cls, agent_name: str) -> Dict[str, Any] | None:
        return cls.agents.get(agent_name)

    @classmethod
    def is_agent_available(cls, agent_name: str) -> bool:
        return agent_name in cls.agents

    @classmethod
    def describe_agents(cls) -> List[Dict[str, Any]]:
        return [
            {
                "agent_name": agent_name,
                "role": config["role"],
                "description": config["description"],
                "responsibilities": config["responsibilities"],
            }
            for agent_name, config in cls.agents.items()
        ]