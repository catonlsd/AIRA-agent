from pathlib import Path
from typing import Dict, Any


class FileTool:
    name = "file_tool"

    @staticmethod
    def _workspace_root() -> Path:
        return Path(__file__).resolve().parents[2]

    @staticmethod
    def _resolve_safe_path(path: str) -> Path:
        workspace_root = FileTool._workspace_root().resolve()

        requested_path = Path(path)

        if requested_path.is_absolute():
            resolved_path = requested_path.resolve()
        else:
            resolved_path = (workspace_root / requested_path).resolve()

        if workspace_root not in resolved_path.parents and resolved_path != workspace_root:
            raise PermissionError(
                f"Access denied. Path is outside workspace: {path}"
            )

        return resolved_path

    @staticmethod
    def read_file(path: str) -> Dict[str, Any]:
        try:
            file_path = FileTool._resolve_safe_path(path)

            if not file_path.exists():
                return {
                    "success": False,
                    "tool_name": "file_tool",
                    "action": "read_file",
                    "path": path,
                    "output": "",
                    "error": "File does not exist.",
                }

            if not file_path.is_file():
                return {
                    "success": False,
                    "tool_name": "file_tool",
                    "action": "read_file",
                    "path": path,
                    "output": "",
                    "error": "Path is not a file.",
                }

            content = file_path.read_text(encoding="utf-8")

            return {
                "success": True,
                "tool_name": "file_tool",
                "action": "read_file",
                "path": str(file_path),
                "output": content,
                "content": content,
            }

        except Exception as e:
            return {
                "success": False,
                "tool_name": "file_tool",
                "action": "read_file",
                "path": path,
                "output": "",
                "error": str(e),
            }

    @staticmethod
    def write_file(path: str, content: str) -> Dict[str, Any]:
        try:
            file_path = FileTool._resolve_safe_path(path)

            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

            return {
                "success": True,
                "tool_name": "file_tool",
                "action": "write_file",
                "path": str(file_path),
                "output": "File written successfully.",
                "message": "File written successfully.",
            }

        except Exception as e:
            return {
                "success": False,
                "tool_name": "file_tool",
                "action": "write_file",
                "path": path,
                "output": "",
                "error": str(e),
            }

    @staticmethod
    def list_files(path: str = ".") -> Dict[str, Any]:
        try:
            folder = FileTool._resolve_safe_path(path)

            if not folder.exists():
                return {
                    "success": False,
                    "tool_name": "file_tool",
                    "action": "list_files",
                    "path": path,
                    "output": "",
                    "error": "Path does not exist.",
                }

            if not folder.is_dir():
                return {
                    "success": False,
                    "tool_name": "file_tool",
                    "action": "list_files",
                    "path": path,
                    "output": "",
                    "error": "Path is not a directory.",
                }

            files = [str(item) for item in folder.iterdir()]

            return {
                "success": True,
                "tool_name": "file_tool",
                "action": "list_files",
                "path": str(folder),
                "output": files,
                "files": files,
            }

        except Exception as e:
            return {
                "success": False,
                "tool_name": "file_tool",
                "action": "list_files",
                "path": path,
                "output": "",
                "error": str(e),
            }