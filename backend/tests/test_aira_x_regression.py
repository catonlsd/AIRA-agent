import sys
from pathlib import Path
import asyncio

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.routes.aira_x import (
    AiraXApproveRequest,
    AiraXRejectRequest,
    AiraXRunRequest,
    approve_aira_x_action,
    reject_aira_x_action,
    run_aira_x,
    list_aira_x_tools,
    list_aira_x_agents,
    list_aira_x_runs,
    get_aira_x_run,
    get_aira_x_overview,
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


def assert_true(condition, label):
    if not condition:
        raise AssertionError(f"{label} failed.")


async def test_normal_python_execution():
    print("Testing normal Python execution...")

    response = await run_aira_x(AiraXRunRequest(goal="run python code"))

    assert_equal(response["status"], "completed", "Python execution status")
    assert_contains(
        response["final_answer"],
        "Workflow completed successfully",
        "Python execution final answer",
    )

    print("✅ Normal Python execution passed")

    return response


async def test_retry_self_correction():
    print("Testing retry self-correction...")

    response = await run_aira_x(AiraXRunRequest(goal="test retry"))

    assert_equal(response["status"], "completed", "Retry workflow status")
    assert_true(response["memory"].get("reflections"), "Reflection memory exists")

    print("✅ Retry self-correction passed")

    return response


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

    return response


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

    return rejected_response


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

    return approved_response


async def test_git_status():
    print("Testing Git status...")

    response = await run_aira_x(AiraXRunRequest(goal="git status"))

    assert_equal(response["status"], "completed", "Git status workflow status")

    first_step = response["plan"][0]

    assert_equal(first_step["tool_name"], "git_tool", "Git tool selection")
    assert_equal(first_step["tool_action"], "status", "Git action selection")

    print("✅ Git status passed")

    return response


async def test_git_diff():
    print("Testing Git diff...")

    response = await run_aira_x(AiraXRunRequest(goal="git diff"))

    assert_equal(response["status"], "completed", "Git diff workflow status")

    first_step = response["plan"][0]

    assert_equal(first_step["tool_name"], "git_tool", "Git diff tool selection")
    assert_equal(first_step["tool_action"], "diff", "Git diff action selection")

    print("✅ Git diff passed")

    return response


async def test_tool_registry_api():
    print("Testing Tool Registry API...")

    response = await list_aira_x_tools()

    assert_true(response["tool_count"] >= 4, "Tool count should be at least 4")

    tool_names = [tool["tool_name"] for tool in response["tools"]]

    assert_true("shell_tool" in tool_names, "shell_tool exists")
    assert_true("file_tool" in tool_names, "file_tool exists")
    assert_true("python_tool" in tool_names, "python_tool exists")
    assert_true("git_tool" in tool_names, "git_tool exists")

    git_tool = next(
        tool for tool in response["tools"] if tool["tool_name"] == "git_tool"
    )

    assert_true("diff" in git_tool["actions"], "git_tool diff action exists")
    assert_true(
        "full_diff" in git_tool["actions"],
        "git_tool full_diff action exists",
    )
    assert_true("stage_all" in git_tool["actions"], "git_tool stage_all action exists")
    assert_true("commit" in git_tool["actions"], "git_tool commit action exists")

    assert_true(
        git_tool["policy"]["stage_all"]["requires_approval"] is True,
        "git_tool stage_all requires approval",
    )

    assert_true(
        git_tool["policy"]["commit"]["requires_approval"] is True,
        "git_tool commit requires approval",
    )

    for tool in response["tools"]:
        assert_true("policy" in tool, f"{tool['tool_name']} has policy metadata")

    print("✅ Tool Registry API passed")


async def test_agent_registry_api():
    print("Testing Agent Registry API...")

    response = await list_aira_x_agents()

    assert_true(response["agent_count"] >= 8, "Agent count should be at least 8")

    agent_names = [agent["agent_name"] for agent in response["agents"]]

    assert_true("planner_agent" in agent_names, "planner_agent exists")
    assert_true("decision_agent" in agent_names, "decision_agent exists")
    assert_true("execution_agent" in agent_names, "execution_agent exists")
    assert_true("safety_agent" in agent_names, "safety_agent exists")
    assert_true("approval_agent" in agent_names, "approval_agent exists")
    assert_true("validation_agent" in agent_names, "validation_agent exists")
    assert_true("reflection_agent" in agent_names, "reflection_agent exists")
    assert_true("memory_agent" in agent_names, "memory_agent exists")

    print("✅ Agent Registry API passed")


async def test_workflow_runs_api(sample_run):
    print("Testing Workflow Runs API...")

    response = await list_aira_x_runs()

    assert_true(
        response["run_count"] >= 1,
        "Workflow run count should be at least 1",
    )

    run_ids = [run["run_id"] for run in response["runs"]]

    assert_true(sample_run["run_id"] in run_ids, "Sample run exists in history")

    print("✅ Workflow Runs API passed")


async def test_workflow_detail_api(sample_run):
    print("Testing Workflow Detail API...")

    response = await get_aira_x_run(sample_run["run_id"])

    assert_equal(response["success"], True, "Workflow detail success")

    run = response["run"]

    assert_equal(run["run_id"], sample_run["run_id"], "Workflow detail run_id")
    assert_true(len(run["plan"]) >= 1, "Workflow detail contains plan")
    assert_true(len(run["workflow_logs"]) >= 1, "Workflow detail contains logs")

    print("✅ Workflow Detail API passed")


async def test_platform_overview_api():
    print("Testing Platform Overview API...")

    response = await get_aira_x_overview()

    assert_equal(response["platform"], "AIRA-X", "Overview platform name")
    assert_true(response["agent_count"] >= 8, "Overview agent count")
    assert_true(response["tool_count"] >= 4, "Overview tool count")
    assert_true(
        "workflow_metrics" in response,
        "Overview contains workflow metrics",
    )

    metrics = response["workflow_metrics"]

    assert_true("total_runs" in metrics, "Overview metrics total_runs exists")
    assert_true("completed_runs" in metrics, "Overview metrics completed_runs exists")
    assert_true("latest_runs" in metrics, "Overview metrics latest_runs exists")

    print("✅ Platform Overview API passed")

async def test_git_commit_requires_approval():
    print("Testing Git commit approval requirement...")

    response = await run_aira_x(AiraXRunRequest(goal="git commit"))

    assert_equal(
        response["status"],
        "requires_approval",
        "Git commit should require approval",
    )

    assert_equal(
        response["decision"],
        "stop_approval_required",
        "Git commit approval decision",
    )

    first_step = response["plan"][0]

    assert_equal(first_step["tool_name"], "git_tool", "Git commit tool selection")
    assert_equal(first_step["tool_action"], "commit", "Git commit action selection")

    print("✅ Git commit approval requirement passed")

    return response


async def main():
    print("\nRunning AIRA-X regression test suite...\n")

    sample_run = await test_normal_python_execution()

    await test_retry_self_correction()
    await test_safety_block()
    await test_approval_rejection()
    await test_approval_continuation()
    await test_git_status()
    await test_git_diff()
    await test_git_commit_requires_approval()

    await test_tool_registry_api()
    await test_agent_registry_api()
    await test_platform_overview_api()
    await test_workflow_runs_api(sample_run)
    await test_workflow_detail_api(sample_run)

    print("\n🎉 All AIRA-X regression tests passed successfully!\n")


if __name__ == "__main__":
    asyncio.run(main())