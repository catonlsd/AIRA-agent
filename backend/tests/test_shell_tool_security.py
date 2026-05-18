import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from tools.tool_router import ToolRouter


def assert_true(condition, label):
    if not condition:
        raise AssertionError(f"{label} failed.")


print("Testing safe shell command...")

safe_result = ToolRouter.run(
    tool_name="shell_tool",
    action="run",
    payload={"command": "echo AIRA-X shell security test"},
)

assert_true(safe_result["success"], "Safe shell command should succeed")
assert_true(
    "AIRA-X shell security test" in safe_result["output"],
    "Safe shell command should return expected output",
)

print("✅ Safe shell command passed")


print("Testing blocked shell command...")

blocked_result = ToolRouter.run(
    tool_name="shell_tool",
    action="run",
    payload={"command": "rm -rf /"},
)

assert_true(
    blocked_result["success"] is False,
    "Dangerous shell command should fail",
)

assert_true(
    "blocked" in blocked_result["error"].lower(),
    "Dangerous shell command should return blocked error",
)

print("✅ Dangerous shell command blocked successfully")


print("Testing retry demo failure command...")

retry_fail_result = ToolRouter.run(
    tool_name="shell_tool",
    action="run",
    payload={"command": "non_existing_command_for_retry_demo"},
)

assert_true(
    retry_fail_result["success"] is False,
    "Unknown command should fail safely",
)

print("✅ Unknown command failure handled safely")

print("\n🎉 Shell Tool security tests passed!\n")