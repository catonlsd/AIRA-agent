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
    def status_branch() -> Dict[str, Any]:
        return GitTool._run_git_command(
            ["git", "status", "-sb"],
            action="status_branch",
        )

    @staticmethod
    def branch() -> Dict[str, Any]:
        return GitTool._run_git_command(
            ["git", "branch", "--show-current"],
            action="branch",
        )

    @staticmethod
    def remote_info() -> Dict[str, Any]:
        return GitTool._run_git_command(
            ["git", "remote", "-v"],
            action="remote_info",
        )

    @staticmethod
    def recent_commits(limit: int = 5) -> Dict[str, Any]:
        return GitTool._run_git_command(
            ["git", "log", "--oneline", f"-{limit}"],
            action="recent_commits",
        )

    @staticmethod
    def last_commit() -> Dict[str, Any]:
        return GitTool._run_git_command(
            ["git", "log", "-1", "--oneline"],
            action="last_commit",
        )

    @staticmethod
    def diff() -> Dict[str, Any]:
        return GitTool._run_git_command(
            ["git", "diff", "--stat"],
            action="diff",
        )

    @staticmethod
    def full_diff() -> Dict[str, Any]:
        return GitTool._run_git_command(
            ["git", "diff"],
            action="full_diff",
        )

    @staticmethod
    def staged_files() -> Dict[str, Any]:
        return GitTool._run_git_command(
            ["git", "diff", "--cached", "--name-status"],
            action="staged_files",
        )

    @staticmethod
    def staged_diff() -> Dict[str, Any]:
        return GitTool._run_git_command(
            ["git", "diff", "--cached", "--stat"],
            action="staged_diff",
        )

    @staticmethod
    def full_staged_diff() -> Dict[str, Any]:
        return GitTool._run_git_command(
            ["git", "diff", "--cached"],
            action="full_staged_diff",
        )

    @staticmethod
    def stage_all() -> Dict[str, Any]:
        return GitTool._run_git_command(
            ["git", "add", "."],
            action="stage_all",
        )

    @staticmethod
    def unstage_all() -> Dict[str, Any]:
        return GitTool._run_git_command(
            ["git", "restore", "--staged", "."],
            action="unstage_all",
        )

    @staticmethod
    def commit(message: str) -> Dict[str, Any]:
        clean_message = message.strip() or "AIRA-X automated commit"

        return GitTool._run_git_command(
            ["git", "commit", "-m", clean_message],
            action="commit",
        )

    @staticmethod
    def push(remote: str = "origin", branch: str | None = None) -> Dict[str, Any]:
        clean_remote = remote.strip() or "origin"
        clean_branch = branch.strip() if branch else ""

        if not clean_branch:
            branch_result = GitTool.branch()

            if not branch_result.get("success") or not branch_result.get("output"):
                return {
                    "success": False,
                    "tool_name": "git_tool",
                    "action": "push",
                    "command": "git push",
                    "output": "",
                    "error": "Could not determine current Git branch before push.",
                }

            clean_branch = branch_result["output"].strip()

        return GitTool._run_git_command(
            ["git", "push", clean_remote, clean_branch],
            action="push",
            timeout=120,
        )

    @staticmethod
    def _run_git_command(
        command: list[str],
        action: str,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        try:
            result = subprocess.run(
                command,
                cwd=GitTool._repo_root(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )

            output = result.stdout.strip() or result.stderr.strip()

            return {
                "success": result.returncode == 0,
                "tool_name": "git_tool",
                "action": action,
                "command": " ".join(command),
                "output": output,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "tool_name": "git_tool",
                "action": action,
                "command": " ".join(command),
                "output": "",
                "error": "Git command timed out.",
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