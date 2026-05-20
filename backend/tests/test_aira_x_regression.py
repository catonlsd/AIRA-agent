import sys
from pathlib import Path
import asyncio

sys.path.append(str(Path(__file__).resolve().parents[1]))

import app.routes.aira_x as aira_x_routes

from schemas.aira_state import AiraXState, AiraXStep
from memory.workflow_store import WorkflowStore

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


async def test_git_commit_custom_message_requires_approval():
    print("Testing Git commit custom message approval requirement...")

    response = await run_aira_x(
        AiraXRunRequest(
            goal='git commit with message "Improve git commit planning"'
        )
    )

    assert_equal(
        response["status"],
        "requires_approval",
        "Git commit with custom message should require approval",
    )

    assert_equal(
        response["decision"],
        "stop_approval_required",
        "Git commit custom message approval decision",
    )

    assert_equal(
        response["pending_action"],
        "git_tool:commit -m Improve git commit planning",
        "Git commit custom pending action",
    )

    first_step = response["plan"][0]

    assert_equal(
        first_step["tool_name"],
        "git_tool",
        "Git commit custom message tool selection",
    )

    assert_equal(
        first_step["tool_action"],
        "commit",
        "Git commit custom message action selection",
    )

    assert_equal(
        first_step["tool_payload"]["message"],
        "Improve git commit planning",
        "Git commit custom message extraction",
    )

    print("✅ Git commit custom message approval requirement passed")

    return response


async def test_multi_step_commit_requires_stage_approval():
    print("Testing multi-step commit workflow approval requirement...")

    response = await run_aira_x(
        AiraXRunRequest(
            goal='commit all changes with message "Test multi step commit"'
        )
    )

    assert_equal(
        response["status"],
        "requires_approval",
        "Multi-step commit should require approval at staging step",
    )

    assert_equal(
        response["decision"],
        "stop_approval_required",
        "Multi-step commit approval decision",
    )

    assert_equal(
        response["pending_action"],
        "git_tool:stage_all",
        "Multi-step commit pending action should be stage_all first",
    )

    assert_true(
        len(response["plan"]) == 2,
        "Multi-step commit should create two workflow steps",
    )

    first_step = response["plan"][0]
    second_step = response["plan"][1]

    assert_equal(
        first_step["tool_name"],
        "git_tool",
        "Multi-step commit first step tool",
    )

    assert_equal(
        first_step["tool_action"],
        "stage_all",
        "Multi-step commit first step action",
    )

    assert_equal(
        second_step["tool_name"],
        "git_tool",
        "Multi-step commit second step tool",
    )

    assert_equal(
        second_step["tool_action"],
        "commit",
        "Multi-step commit second step action",
    )

    assert_equal(
        second_step["tool_payload"]["message"],
        "Test multi step commit",
        "Multi-step commit message extraction",
    )

    print("✅ Multi-step commit workflow approval requirement passed")

    return response


async def test_git_preflight_context():
    print("Testing Git preflight approval context...")

    response = await run_aira_x(
        AiraXRunRequest(
            goal='commit all changes with message "Test preflight context"'
        )
    )

    assert_equal(
        response["status"],
        "requires_approval",
        "Git preflight workflow should require approval",
    )

    assert_equal(
        response["pending_action"],
        "git_tool:stage_all",
        "Git preflight pending action should be stage_all",
    )

    approval_context = response.get("approval_context")

    assert_true(
        isinstance(approval_context, dict),
        "Approval context should exist",
    )

    assert_equal(
        approval_context.get("type"),
        "git_write_preflight",
        "Approval context type",
    )

    assert_equal(
        approval_context.get("tool_name"),
        "git_tool",
        "Approval context tool name",
    )

    assert_equal(
        approval_context.get("tool_action"),
        "stage_all",
        "Approval context tool action",
    )

    assert_equal(
        approval_context.get("pending_action"),
        "git_tool:stage_all",
        "Approval context pending action",
    )

    assert_true(
        "branch" in approval_context,
        "Approval context contains branch",
    )

    assert_true(
        "changed_files" in approval_context,
        "Approval context contains changed files",
    )

    assert_true(
        "diff_summary" in approval_context,
        "Approval context contains diff summary",
    )

    assert_true(
        "branch_success" in approval_context,
        "Approval context contains branch success flag",
    )

    assert_true(
        "status_success" in approval_context,
        "Approval context contains status success flag",
    )

    assert_true(
        "diff_success" in approval_context,
        "Approval context contains diff success flag",
    )

    print("✅ Git preflight approval context passed")

    return response


async def test_git_push_requires_approval():
    print("Testing Git push approval requirement...")

    response = await run_aira_x(AiraXRunRequest(goal="git push"))

    assert_equal(
        response["status"],
        "requires_approval",
        "Git push should require approval",
    )

    assert_equal(
        response["decision"],
        "stop_approval_required",
        "Git push approval decision",
    )

    assert_equal(
        response["pending_action"],
        "git_tool:push origin current_branch",
        "Git push pending action",
    )

    first_step = response["plan"][0]

    assert_equal(first_step["tool_name"], "git_tool", "Git push tool selection")
    assert_equal(first_step["tool_action"], "push", "Git push action selection")

    assert_equal(
        first_step["tool_payload"]["remote"],
        "origin",
        "Git push default remote",
    )

    assert_equal(
        first_step["tool_payload"]["branch"],
        None,
        "Git push default branch should be resolved later",
    )

    approval_context = response.get("approval_context")

    assert_true(
        isinstance(approval_context, dict),
        "Git push approval context should exist",
    )

    assert_equal(
        approval_context.get("type"),
        "git_push_preflight",
        "Git push approval context type",
    )

    assert_equal(
        approval_context.get("tool_name"),
        "git_tool",
        "Git push approval context tool name",
    )

    assert_equal(
        approval_context.get("tool_action"),
        "push",
        "Git push approval context tool action",
    )

    assert_equal(
        approval_context.get("pending_action"),
        "git_tool:push origin current_branch",
        "Git push approval context pending action",
    )

    assert_equal(
        approval_context.get("target_remote"),
        "origin",
        "Git push approval context target remote",
    )

    assert_true(
        "target_branch" in approval_context,
        "Git push approval context contains target branch",
    )

    assert_true(
        "branch" in approval_context,
        "Git push approval context contains current branch",
    )

    assert_true(
        "status_branch" in approval_context,
        "Git push approval context contains status branch",
    )

    assert_true(
        "remote_info" in approval_context,
        "Git push approval context contains remote info",
    )

    assert_true(
        "last_commit" in approval_context,
        "Git push approval context contains latest commit",
    )

    assert_true(
        "recent_commits" in approval_context,
        "Git push approval context contains recent commits",
    )

    print("✅ Git push approval requirement passed")

    return response


async def test_git_push_custom_target_requires_approval():
    print("Testing Git push custom target approval requirement...")

    response = await run_aira_x(AiraXRunRequest(goal="git push origin main"))

    assert_equal(
        response["status"],
        "requires_approval",
        "Git push custom target should require approval",
    )

    assert_equal(
        response["decision"],
        "stop_approval_required",
        "Git push custom target approval decision",
    )

    assert_equal(
        response["pending_action"],
        "git_tool:push origin main",
        "Git push custom target pending action",
    )

    first_step = response["plan"][0]

    assert_equal(
        first_step["tool_name"],
        "git_tool",
        "Git push custom target tool selection",
    )

    assert_equal(
        first_step["tool_action"],
        "push",
        "Git push custom target action selection",
    )

    assert_equal(
        first_step["tool_payload"]["remote"],
        "origin",
        "Git push custom target remote",
    )

    assert_equal(
        first_step["tool_payload"]["branch"],
        "main",
        "Git push custom target branch",
    )

    approval_context = response.get("approval_context")

    assert_true(
        isinstance(approval_context, dict),
        "Git push custom target approval context should exist",
    )

    assert_equal(
        approval_context.get("type"),
        "git_push_preflight",
        "Git push custom target approval context type",
    )

    assert_equal(
        approval_context.get("target_remote"),
        "origin",
        "Git push custom target approval context remote",
    )

    assert_equal(
        approval_context.get("target_branch"),
        "main",
        "Git push custom target approval context branch",
    )

    print("✅ Git push custom target approval requirement passed")

    return response


async def test_workflow_runs_include_git_preflight_summary():
    print("Testing Workflow Runs API includes Git preflight summary...")

    preflight_response = await run_aira_x(
        AiraXRunRequest(
            goal='commit all changes with message "Workflow list preflight test"'
        )
    )

    assert_equal(
        preflight_response["status"],
        "requires_approval",
        "Preflight workflow should require approval",
    )

    runs_response = await list_aira_x_runs()

    matching_run = next(
        (
            run
            for run in runs_response["runs"]
            if run["run_id"] == preflight_response["run_id"]
        ),
        None,
    )

    assert_true(
        matching_run is not None,
        "Preflight workflow should appear in workflow runs list",
    )

    assert_equal(
        matching_run["approval_context_type"],
        "git_write_preflight",
        "Workflow run summary should include approval context type",
    )

    assert_true(
        isinstance(matching_run.get("approval_context"), dict),
        "Workflow run summary should include approval context",
    )

    assert_equal(
        matching_run["approval_context"].get("pending_action"),
        "git_tool:stage_all",
        "Workflow run summary should include pending Git action",
    )

    assert_true(
        "branch" in matching_run["approval_context"],
        "Workflow run summary should include Git branch",
    )

    assert_true(
        "diff_summary" in matching_run["approval_context"],
        "Workflow run summary should include diff summary",
    )

    print("✅ Workflow Runs Git preflight summary passed")

    return matching_run


async def test_overview_latest_runs_include_git_preflight_summary():
    print("Testing Overview API includes Git preflight summary in latest runs...")

    preflight_response = await run_aira_x(
        AiraXRunRequest(
            goal='commit all changes with message "Overview preflight test"'
        )
    )

    assert_equal(
        preflight_response["status"],
        "requires_approval",
        "Overview preflight workflow should require approval",
    )

    overview_response = await get_aira_x_overview()

    latest_runs = overview_response["workflow_metrics"]["latest_runs"]

    matching_run = next(
        (
            run
            for run in latest_runs
            if run["run_id"] == preflight_response["run_id"]
        ),
        None,
    )

    assert_true(
        matching_run is not None,
        "Preflight workflow should appear in overview latest runs",
    )

    assert_equal(
        matching_run["approval_context_type"],
        "git_write_preflight",
        "Overview latest run should include approval context type",
    )

    assert_true(
        isinstance(matching_run.get("approval_context"), dict),
        "Overview latest run should include approval context",
    )

    assert_equal(
        matching_run["approval_context"].get("pending_action"),
        "git_tool:stage_all",
        "Overview latest run should include pending Git action",
    )

    assert_true(
        "branch" in matching_run["approval_context"],
        "Overview latest run should include Git branch",
    )

    assert_true(
        "diff_summary" in matching_run["approval_context"],
        "Overview latest run should include diff summary",
    )

    print("✅ Overview Git preflight summary passed")

    return matching_run


async def test_commit_rejection_triggers_unstage_cleanup():
    print("Testing commit rejection triggers unstage cleanup...")

    run_id = "test-auto-unstage-cleanup"

    state = AiraXState(
        user_goal='commit all changes with message "Test cleanup"',
        run_id=run_id,
    )

    state.status = "requires_approval"
    state.decision = "stop_approval_required"
    state.current_step = 2

    state.plan = [
        AiraXStep(
            id=1,
            title="Stage Git changes",
            description="Stage all current Git changes.",
            assigned_agent="execution_agent",
            tool_name="git_tool",
            tool_action="stage_all",
            tool_payload={},
            status="completed",
            result="Execution completed successfully.",
        ),
        AiraXStep(
            id=2,
            title="Commit Git changes",
            description="Create a local Git commit after staging.",
            assigned_agent="execution_agent",
            tool_name="git_tool",
            tool_action="commit",
            tool_payload={"message": "Test cleanup"},
            status="blocked",
            error="This action requires user approval.",
        ),
    ]

    state.memory["pending_action"] = "git_tool:commit -m Test cleanup"
    state.memory["approval_context"] = {
        "type": "git_write_preflight",
        "tool_name": "git_tool",
        "tool_action": "commit",
        "pending_action": "git_tool:commit -m Test cleanup",
        "commit_message": "Test cleanup",
        "branch": "main",
        "changed_files": "M backend/example.py",
        "diff_summary": "backend/example.py | 1 +",
    }

    state.execution_outputs.append(
        {
            "step_id": 1,
            "agent": "execution_agent",
            "tool_used": "git_tool",
            "tool_action": "stage_all",
            "tool_result": {
                "success": True,
                "output": "",
            },
        }
    )

    WorkflowStore.save(state)

    original_tool_run = aira_x_routes.ToolRouter.run
    cleanup_calls = []

    def fake_tool_run(tool_name, action, payload=None):
        cleanup_calls.append(
            {
                "tool_name": tool_name,
                "action": action,
                "payload": payload or {},
            }
        )

        if tool_name == "git_tool" and action == "unstage_all":
            return {
                "success": True,
                "tool_name": "git_tool",
                "action": "unstage_all",
                "command": "git restore --staged .",
                "output": "",
                "return_code": 0,
            }

        return {
            "success": False,
            "tool_name": tool_name,
            "action": action,
            "output": "",
            "error": "Unexpected mocked tool call.",
        }

    try:
        aira_x_routes.ToolRouter.run = staticmethod(fake_tool_run)

        response = await reject_aira_x_action(
            AiraXRejectRequest(run_id=run_id)
        )

    finally:
        aira_x_routes.ToolRouter.run = original_tool_run
        WorkflowStore.delete(run_id)

    assert_equal(
        response["status"],
        "rejected",
        "Cleanup rejection workflow status",
    )

    assert_equal(
        response["decision"],
        "approval_rejected",
        "Cleanup rejection workflow decision",
    )

    assert_contains(
        response["final_answer"],
        "unstaged changes",
        "Cleanup final answer should mention unstaged changes",
    )

    assert_true(
        any(
            call["tool_name"] == "git_tool"
            and call["action"] == "unstage_all"
            for call in cleanup_calls
        ),
        "Rejecting commit after stage_all should call git_tool.unstage_all",
    )

    cleanup_actions = response["memory"].get("cleanup_actions", [])

    assert_true(
        len(cleanup_actions) >= 1,
        "Cleanup action should be recorded in memory",
    )

    assert_equal(
        cleanup_actions[-1]["tool_action"],
        "unstage_all",
        "Cleanup memory should record unstage_all",
    )

    assert_true(
        cleanup_actions[-1]["result"]["success"] is True,
        "Cleanup result should be successful",
    )

    print("✅ Commit rejection unstage cleanup passed")

    return response


async def test_cleanup_metrics_in_runs_and_overview():
    print("Testing cleanup metrics in Workflow Runs and Overview APIs...")

    run_id = "test-cleanup-metrics-summary"

    WorkflowStore.delete(run_id)

    state = AiraXState(
        user_goal='commit all changes with message "Cleanup metrics test"',
        run_id=run_id,
    )

    state.status = "rejected"
    state.decision = "approval_rejected"
    state.current_step = 2
    state.final_answer = (
        "User rejected the action: git_tool:commit -m Cleanup metrics test. "
        "AIRA-X also unstaged changes that it staged for this workflow."
    )

    state.plan = [
        AiraXStep(
            id=1,
            title="Stage Git changes",
            description="Stage all current Git changes.",
            assigned_agent="execution_agent",
            tool_name="git_tool",
            tool_action="stage_all",
            tool_payload={},
            status="completed",
            result="Execution completed successfully.",
        ),
        AiraXStep(
            id=2,
            title="Commit Git changes",
            description="Create a local Git commit after staging.",
            assigned_agent="execution_agent",
            tool_name="git_tool",
            tool_action="commit",
            tool_payload={"message": "Cleanup metrics test"},
            status="rejected",
            error="User rejected the action.",
        ),
    ]

    state.memory["pending_action"] = "git_tool:commit -m Cleanup metrics test"
    state.memory["approval_context"] = {
        "type": "git_write_preflight",
        "tool_name": "git_tool",
        "tool_action": "commit",
        "pending_action": "git_tool:commit -m Cleanup metrics test",
        "commit_message": "Cleanup metrics test",
        "branch": "main",
        "changed_files": "M backend/example.py",
        "diff_summary": "backend/example.py | 1 +",
    }
    state.memory["cleanup_actions"] = [
        {
            "reason": "commit_rejected_after_aira_x_stage_all",
            "tool_name": "git_tool",
            "tool_action": "unstage_all",
            "result": {
                "success": True,
                "tool_name": "git_tool",
                "action": "unstage_all",
                "command": "git restore --staged .",
                "output": "",
                "return_code": 0,
            },
        }
    ]

    try:
        WorkflowStore.save(state)

        runs_response = await list_aira_x_runs()

        matching_run = next(
            (
                run
                for run in runs_response["runs"]
                if run["run_id"] == run_id
            ),
            None,
        )

        assert_true(
            matching_run is not None,
            "Cleanup workflow should appear in workflow runs list",
        )

        assert_true(
            matching_run["has_cleanup"] is True,
            "Workflow run summary should mark cleanup as performed",
        )

        assert_equal(
            matching_run["cleanup_count"],
            1,
            "Workflow run summary should include cleanup count",
        )

        assert_true(
            isinstance(matching_run.get("cleanup_actions"), list),
            "Workflow run summary should include cleanup actions list",
        )

        assert_equal(
            matching_run["cleanup_actions"][0]["tool_action"],
            "unstage_all",
            "Workflow run summary should include unstage cleanup action",
        )

        overview_response = await get_aira_x_overview()

        metrics = overview_response["workflow_metrics"]

        assert_true(
            "cleanup_runs" in metrics,
            "Overview metrics should include cleanup_runs",
        )

        assert_true(
            "total_cleanup_actions" in metrics,
            "Overview metrics should include total_cleanup_actions",
        )

        assert_true(
            metrics["cleanup_runs"] >= 1,
            "Overview cleanup_runs should count cleanup workflows",
        )

        assert_true(
            metrics["total_cleanup_actions"] >= 1,
            "Overview total_cleanup_actions should count cleanup actions",
        )

        latest_runs = metrics["latest_runs"]

        latest_matching_run = next(
            (
                run
                for run in latest_runs
                if run["run_id"] == run_id
            ),
            None,
        )

        assert_true(
            latest_matching_run is not None,
            "Cleanup workflow should appear in overview latest runs",
        )

        assert_true(
            latest_matching_run["has_cleanup"] is True,
            "Overview latest run should mark cleanup as performed",
        )

        assert_equal(
            latest_matching_run["cleanup_count"],
            1,
            "Overview latest run should include cleanup count",
        )

        assert_equal(
            latest_matching_run["cleanup_actions"][0]["tool_action"],
            "unstage_all",
            "Overview latest run should include unstage cleanup action",
        )

    finally:
        WorkflowStore.delete(run_id)

    print("✅ Cleanup metrics in runs and overview passed")

    return True


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

    assert_true("status" in git_tool["actions"], "git_tool status action exists")
    assert_true(
        "status_branch" in git_tool["actions"],
        "git_tool status_branch action exists",
    )
    assert_true("branch" in git_tool["actions"], "git_tool branch action exists")
    assert_true(
        "remote_info" in git_tool["actions"],
        "git_tool remote_info action exists",
    )
    assert_true(
        "recent_commits" in git_tool["actions"],
        "git_tool recent_commits action exists",
    )
    assert_true(
        "last_commit" in git_tool["actions"],
        "git_tool last_commit action exists",
    )
    assert_true("diff" in git_tool["actions"], "git_tool diff action exists")
    assert_true(
        "full_diff" in git_tool["actions"],
        "git_tool full_diff action exists",
    )

    assert_true(
        "staged_files" in git_tool["actions"],
        "git_tool staged_files action exists",
    )
    assert_true(
        "staged_diff" in git_tool["actions"],
        "git_tool staged_diff action exists",
    )
    assert_true(
        "full_staged_diff" in git_tool["actions"],
        "git_tool full_staged_diff action exists",
    )

    assert_true("stage_all" in git_tool["actions"], "git_tool stage_all action exists")
    assert_true(
        "unstage_all" in git_tool["actions"],
        "git_tool unstage_all action exists",
    )
    assert_true("commit" in git_tool["actions"], "git_tool commit action exists")
    assert_true("push" in git_tool["actions"], "git_tool push action exists")

    assert_true(
        git_tool["policy"]["status_branch"]["requires_approval"] is False,
        "git_tool status_branch does not require approval",
    )

    assert_true(
        git_tool["policy"]["remote_info"]["requires_approval"] is False,
        "git_tool remote_info does not require approval",
    )

    assert_true(
        git_tool["policy"]["last_commit"]["requires_approval"] is False,
        "git_tool last_commit does not require approval",
    )

    assert_true(
        git_tool["policy"]["stage_all"]["requires_approval"] is True,
        "git_tool stage_all requires approval",
    )

    assert_true(
        git_tool["policy"]["commit"]["requires_approval"] is True,
        "git_tool commit requires approval",
    )

    assert_true(
        git_tool["policy"]["push"]["requires_approval"] is True,
        "git_tool push requires approval",
    )

    assert_true(
        git_tool["policy"]["unstage_all"]["requires_approval"] is False,
        "git_tool unstage_all does not require approval",
    )

    assert_true(
        git_tool["policy"]["staged_files"]["requires_approval"] is False,
        "git_tool staged_files does not require approval",
    )

    assert_true(
        git_tool["policy"]["staged_diff"]["requires_approval"] is False,
        "git_tool staged_diff does not require approval",
    )

    assert_true(
        git_tool["policy"]["full_staged_diff"]["requires_approval"] is False,
        "git_tool full_staged_diff does not require approval",
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
    assert_true("cleanup_runs" in metrics, "Overview metrics cleanup_runs exists")
    assert_true(
        "total_cleanup_actions" in metrics,
        "Overview metrics total_cleanup_actions exists",
    )

    print("✅ Platform Overview API passed")


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
    await test_git_commit_custom_message_requires_approval()
    await test_multi_step_commit_requires_stage_approval()
    await test_git_preflight_context()
    await test_git_push_requires_approval()
    await test_git_push_custom_target_requires_approval()
    await test_workflow_runs_include_git_preflight_summary()
    await test_overview_latest_runs_include_git_preflight_summary()
    await test_commit_rejection_triggers_unstage_cleanup()
    await test_cleanup_metrics_in_runs_and_overview()

    await test_tool_registry_api()
    await test_agent_registry_api()
    await test_platform_overview_api()
    await test_workflow_runs_api(sample_run)
    await test_workflow_detail_api(sample_run)

    print("\n🎉 All AIRA-X regression tests passed successfully!\n")


if __name__ == "__main__":
    asyncio.run(main())
