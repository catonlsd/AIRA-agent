import platform
import shlex
import subprocess
from pathlib import Path
from typing import Dict, Any


class ShellTool:
    name = "shell_tool"

    blocked_patterns = [
        "rm -rf",
        "del /s",
        "format",
        "shutdown",
        "restart",
        "taskkill",
        "reg delete",
        "remove-item -recurse",
        ":(){:|:&};:",
    ]

    windows_shell_builtins = [
        "dir",
        "echo",
        "type",
        "copy",
        "move",
        "ren",
        "cls",
    ]

    @staticmethod
    def _workspace_root() -> Path:
        return Path(__file__).resolve().parents[2]

    @staticmethod
    def _is_blocked(command: str) -> str | None:
        normalized_command = command.lower()

        for pattern in ShellTool.blocked_patterns:
            if pattern.lower() in normalized_command:
                return pattern

        return None

    @staticmethod
    def _prepare_command(command: str) -> list[str]:
        system_name = platform.system().lower()
        stripped_command = command.strip()
        lowered_command = stripped_command.lower()

        if system_name == "windows":
            first_word = lowered_command.split()[0] if lowered_command.split() else ""

            if first_word in ShellTool.windows_shell_builtins:
                return ["cmd", "/c", stripped_command]

            return shlex.split(stripped_command, posix=False)

        return shlex.split(stripped_command)

    @staticmethod
    def run(command: str) -> Dict[str, Any]:
        try:
            if not command or not command.strip():
                return {
                    "success": False,
                    "tool_name": "shell_tool",
                    "action": "run",
                    "command": command,
                    "output": "",
                    "error": "Empty shell command is not allowed.",
                }

            blocked_pattern = ShellTool._is_blocked(command)

            if blocked_pattern:
                return {
                    "success": False,
                    "tool_name": "shell_tool",
                    "action": "run",
                    "command": command,
                    "output": "",
                    "error": (
                        "Shell command blocked by ShellTool security guard. "
                        f"Matched pattern: {blocked_pattern}"
                    ),
                    "blocked_pattern": blocked_pattern,
                }

            workspace_root = ShellTool._workspace_root()
            prepared_command = ShellTool._prepare_command(command)

            result = subprocess.run(
                prepared_command,
                cwd=workspace_root,
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
            )

            output = result.stdout.strip() or result.stderr.strip()

            return {
                "success": result.returncode == 0,
                "tool_name": "shell_tool",
                "action": "run",
                "command": command,
                "prepared_command": prepared_command,
                "cwd": str(workspace_root),
                "output": output,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "tool_name": "shell_tool",
                "action": "run",
                "command": command,
                "output": "",
                "error": "Shell command timed out.",
            }

        except Exception as e:
            return {
                "success": False,
                "tool_name": "shell_tool",
                "action": "run",
                "command": command,
                "output": "",
                "error": str(e),
            }