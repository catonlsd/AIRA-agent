from typing import Dict, Any, List


class ToolRegistry:
    name = "tool_registry"

    tools: Dict[str, Dict[str, Any]] = {
        "shell_tool": {
            "description": "Runs safe shell or terminal commands.",
            "actions": ["run"],
            "examples": [
                "dir",
                "echo Hello",
                "python --version",
            ],
        },
        "file_tool": {
            "description": "Reads, writes, and lists files.",
            "actions": ["read_file", "write_file", "list_files"],
            "examples": [
                "read_file",
                "write_file",
                "list_files",
            ],
        },
        "python_tool": {
            "description": "Executes Python code snippets.",
            "actions": ["run_code"],
            "examples": [
                "print('hello')",
                "import math; print(math.sqrt(16))",
            ],
        },
    }

    @classmethod
    def list_tools(cls) -> Dict[str, Dict[str, Any]]:
        return cls.tools

    @classmethod
    def get_tool(cls, tool_name: str) -> Dict[str, Any] | None:
        return cls.tools.get(tool_name)

    @classmethod
    def is_tool_available(cls, tool_name: str) -> bool:
        return tool_name in cls.tools

    @classmethod
    def is_action_allowed(cls, tool_name: str, action: str) -> bool:
        tool = cls.get_tool(tool_name)

        if not tool:
            return False

        return action in tool.get("actions", [])

    @classmethod
    def describe_tools(cls) -> List[Dict[str, Any]]:
        return [
            {
                "tool_name": tool_name,
                "description": config["description"],
                "actions": config["actions"],
                "examples": config["examples"],
            }
            for tool_name, config in cls.tools.items()
        ]