import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from tools.tool_router import ToolRouter


def assert_true(condition, label):
    if not condition:
        raise AssertionError(f"{label} failed.")


print("Testing safe file write...")

safe_result = ToolRouter.run(
    tool_name="file_tool",
    action="write_file",
    payload={
        "path": "tmp/security_test.txt",
        "content": "AIRA-X workspace boundary test",
    },
)

assert_true(safe_result["success"], "Safe file write should succeed")

print("✅ Safe file write passed")


print("Testing unsafe file write outside workspace...")

unsafe_result = ToolRouter.run(
    tool_name="file_tool",
    action="write_file",
    payload={
        "path": "../outside_workspace.txt",
        "content": "This should not be allowed",
    },
)

assert_true(
    unsafe_result["success"] is False,
    "Unsafe file write should fail",
)

assert_true(
    "outside workspace" in unsafe_result["error"].lower()
    or "access denied" in unsafe_result["error"].lower(),
    "Unsafe file write should return workspace error",
)

print("✅ Unsafe file write blocked successfully")

print("\n🎉 File Tool workspace security tests passed!\n")