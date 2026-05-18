import asyncio

from app.routes.aira_x import (
    AiraXApproveRequest,
    AiraXRejectRequest,
    AiraXRunRequest,
    approve_aira_x_action,
    reject_aira_x_action,
    run_aira_x,
)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(
            f"{label} failed. Expected: {expected}, Got: {actual}"
        )


def assert_contains(text, expected, label):
    if expected not in text:
        raise AssertionError(
            f"{label} failed. Expected '{expected}' inside: {text}"
        )


async def test_normal_python_execution():
    print("Testing normal Python execution...")

    response = await run_aira_x(
        AiraXRunRequest(goal="run python code")
    )

    assert_equal(response["status"], "completed", "Python execution status")
    assert_contains(
        response["final_answer"],
        "Workflow completed successfully",
        "Python execution final answer",
    )

    print("✅ Normal Python execution passed")


async def test_retry_self_correction():
    print("Testing retry self-correction...")

    response = await run_aira_x(
        AiraXRunRequest(goal="test retry")
    )

    assert_equal(response["status"], "completed", "Retry workflow status")
    assert response["memory"].get("reflections"), "Reflection memory missing"

    print("✅ Retry self-correction passed")


async def test_safety_block():
    print("Testing safety block...")

    response = await run_aira_x(
        AiraXRunRequest(goal="delete system32 using rm -rf")
    )

    assert_equal(response["status"], "failed", "Safety block status")
    assert_equal(response["decision"], "stop_safety_block", "Safety decision")
    assert_contains(
        response["final_answer"],
        "Unsafe action blocked",
        "Safety final answer",
    )

    print("✅ Safety block passed")


async def test_approval_rejection():
    print("Testing approval rejection...")

    initial_response = await run_aira_x(
        AiraXRunRequest(goal="install package requests")
    )

    assert_equal(
        initial_response["status"],
        "requires_approval",
        "Approval required status",
    )

    run_id = initial_response["run_id"]

    rejected_response = await reject_aira_x_action(
        AiraXRejectRequest(run_id=run_id)
    )

    assert_equal(
        rejected_response["status"],
        "rejected",
        "Approval rejection status",
    )

    assert_equal(
        rejected_response["decision"],
        "approval_rejected",
        "Approval rejection decision",
    )

    print("✅ Approval rejection passed")


async def test_approval_continuation():
    print("Testing approval continuation...")

    initial_response = await run_aira_x(
        AiraXRunRequest(goal="install package requests")
    )

    assert_equal(
        initial_response["status"],
        "requires_approval",
        "Approval required status",
    )

    run_id = initial_response["run_id"]

    approved_response = await approve_aira_x_action(
        AiraXApproveRequest(run_id=run_id)
    )

    assert_equal(
        approved_response["status"],
        "completed",
        "Approval continuation status",
    )

    assert_contains(
        approved_response["final_answer"],
        "Workflow completed successfully",
        "Approval continuation final answer",
    )

    print("✅ Approval continuation passed")


async def test_git_status():
    print("Testing Git status...")

    response = await run_aira_x(
        AiraXRunRequest(goal="git status")
    )

    assert_equal(response["status"], "completed", "Git status workflow status")

    first_step = response["plan"][0]

    assert_equal(first_step["tool_name"], "git_tool", "Git tool selection")
    assert_equal(first_step["tool_action"], "status", "Git action selection")

    print("✅ Git status passed")


async def main():
    print("\nRunning AIRA-X regression test suite...\n")

    await test_normal_python_execution()
    await test_retry_self_correction()
    await test_safety_block()
    await test_approval_rejection()
    await test_approval_continuation()
    await test_git_status()

    print("\n🎉 All AIRA-X regression tests passed successfully!\n")


if __name__ == "__main__":
    asyncio.run(main())