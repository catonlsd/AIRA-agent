import subprocess
from pathlib import Path
from typing import Dict, Any


class GitTool:
    name = "git_tool"

    @staticmethod
    def _repo_root() -> Path:
        return Path(__file__).resolve().parents[3]

    @staticmethod
    def status() -> Dict[str, Any]:
        return GitTool._run_git_command(
            ["git", "status", "--short"],
            action="status",
        )

    @staticmethod
    def branch() -> Dict[str, Any]:
        return GitTool._run_git_command(
            ["git", "branch", "--show-current"],
            action="branch",
        )

    @staticmethod
    def recent_commits(limit: int = 5) -> Dict[str, Any]:
        return GitTool._run_git_command(
            ["git", "log", "--oneline", f"-{limit}"],
            action="recent_commits",
        )

    @staticmethod
    def _run_git_command(command: list[str], action: str) -> Dict[str, Any]:
        try:
            result = subprocess.run(
                command,
                cwd=GitTool._repo_root(),
                capture_output=True,
                text=True,
                timeout=30,
            )

            return {
                "success": result.returncode == 0,
                "tool_name": "git_tool",
                "action": action,
                "command": " ".join(command),
                "output": result.stdout,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
            }
 
        except Exception as e:
            return {
                "success": False,
                "tool_name": "git_tool",
                "action": action,
                "command": " ".join(command),
                "output": "",
                "error": str(e),
            }