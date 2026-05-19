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
            "policy": {
                "run": {
                    "risk_level": "variable",
                    "requires_approval": False,
                    "description": "Shell commands are checked by Safety Agent and Approval Agent before execution.",
                }
            },
        },
        "file_tool": {
            "description": "Reads, writes, and lists files.",
            "actions": ["read_file", "write_file", "list_files"],
            "examples": [
                "read_file",
                "write_file",
                "list_files",
            ],
            "policy": {
                "read_file": {
                    "risk_level": "safe",
                    "requires_approval": False,
                    "description": "Reads file content without modifying the environment.",
                },
                "write_file": {
                    "risk_level": "sensitive",
                    "requires_approval": False,
                    "description": "Writes or modifies files inside the project workspace.",
                },
                "list_files": {
                    "risk_level": "safe",
                    "requires_approval": False,
                    "description": "Lists files without modifying the environment.",
                },
            },
        },
        "python_tool": {
            "description": "Executes Python code snippets.",
            "actions": ["run_code"],
            "examples": [
                "print('hello')",
                "import math; print(math.sqrt(16))",
            ],
            "policy": {
                "run_code": {
                    "risk_level": "sensitive",
                    "requires_approval": False,
                    "description": "Executes Python code in a controlled subprocess.",
                }
            },
        },
        "git_tool": {
            "description": "Reads Git repository state and performs approval-gated local Git writes.",
            "actions": [
                "status",
                "branch",
                "recent_commits",
                "diff",
                "full_diff",
                "staged_files",
                "staged_diff",
                "full_staged_diff",
                "stage_all",
                "unstage_all",
                "commit",
            ],
            "examples": [
                "git status --short",
                "git branch --show-current",
                "git log --oneline -5",
                "git diff --stat",
                "git diff",
                "git diff --cached --name-status",
                "git diff --cached --stat",
                "git diff --cached",
                "git add .",
                "git restore --staged .",
                "git commit -m \"message\"",
            ],
            "policy": {
                "status": {
                    "risk_level": "safe",
                    "requires_approval": False,
                    "description": "Reads current repository status.",
                },
                "branch": {
                    "risk_level": "safe",
                    "requires_approval": False,
                    "description": "Reads the current Git branch.",
                },
                "recent_commits": {
                    "risk_level": "safe",
                    "requires_approval": False,
                    "description": "Reads recent Git commit history.",
                },
                "diff": {
                    "risk_level": "safe",
                    "requires_approval": False,
                    "description": "Reads a summary of unstaged Git changes.",
                },
                "full_diff": {
                    "risk_level": "safe",
                    "requires_approval": False,
                    "description": "Reads full unstaged Git changes.",
                },
                "staged_files": {
                    "risk_level": "safe",
                    "requires_approval": False,
                    "description": "Reads files currently staged for commit.",
                },
                "staged_diff": {
                    "risk_level": "safe",
                    "requires_approval": False,
                    "description": "Reads a summary of staged Git changes.",
                },
                "full_staged_diff": {
                    "risk_level": "safe",
                    "requires_approval": False,
                    "description": "Reads full staged Git changes.",
                },
                "stage_all": {
                    "risk_level": "sensitive",
                    "requires_approval": True,
                    "description": "Stages all current repository changes. Requires user approval.",
                },
                "unstage_all": {
                    "risk_level": "sensitive",
                    "requires_approval": False,
                    "description": "Unstages all currently staged files after commit rejection. Does not delete file changes.",
                },
                "commit": {
                    "risk_level": "sensitive",
                    "requires_approval": True,
                    "description": "Creates a local Git commit. Requires user approval.",
                },
            },
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
    def get_action_policy(cls, tool_name: str, action: str) -> Dict[str, Any]:
        tool = cls.get_tool(tool_name)

        if not tool:
            return {
                "risk_level": "unknown",
                "requires_approval": True,
                "description": "Unknown tool.",
            }

        return tool.get("policy", {}).get(
            action,
            {
                "risk_level": "unknown",
                "requires_approval": True,
                "description": "Unknown action policy.",
            },
        )

    @classmethod
    def describe_tools(cls) -> List[Dict[str, Any]]:
        return [
            {
                "tool_name": tool_name,
                "description": config["description"],
                "actions": config["actions"],
                "examples": config["examples"],
                "policy": config.get("policy", {}),
            }
            for tool_name, config in cls.tools.items()
        ]