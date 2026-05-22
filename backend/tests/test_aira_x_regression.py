import sys
from pathlib import Path
import asyncio

sys.path.append(str(Path(__file__).resolve().parents[1]))

import app.routes.aira_x as aira_x_routes

from schemas.aira_state import AiraXState, AiraXStep
from memory.workflow_store import WorkflowStore
from agents.decision.decision_agent import DecisionAgent

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



def build_stale_approval_processing_state(run_id: str) -> AiraXState:
    pending_action = "git_tool:push origin current_branch"
    stale_timestamp = "2000-01-01T00:00:00+00:00"

    state = AiraXState(
        user_goal="git push",
        run_id=run_id,
    )

    state.status = "requires_approval"
    state.decision = "stop_approval_required"
    state.current_step = 1
    state.final_answer = (
        "Approval required before executing: git_tool:push origin current_branch"
    )

    state.plan = [
        AiraXStep(
            id=1,
            title="Push Git changes",
            description="Push local commits to a remote Git repository.",
            assigned_agent="execution_agent",
            tool_name="git_tool",
            tool_action="push",
            tool_payload={"remote": "origin", "branch": None},
            status="blocked",
            error="This action requires user approval.",
        )
    ]

    state.memory["pending_action"] = pending_action
    state.memory["approval_in_progress"] = True
    state.memory["approval_processing_started_at"] = stale_timestamp
    state.memory["approval_resolution"] = {
        "status": "approved",
        "action": pending_action,
        "requested_at": stale_timestamp,
    }
    state.memory["approval_context"] = {
        "type": "git_push_preflight",
        "tool_name": "git_tool",
        "tool_action": "push",
        "pending_action": pending_action,
        "target_remote": "origin",
        "target_branch": "main",
        "branch": "main",
        "status_branch": "## main...origin/main",
        "remote_info": "origin https://github.com/example/repo.git (fetch)",
        "last_commit": "abc1234 Test commit",
        "recent_commits": "abc1234 Test commit",
    }

    return state


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


async def test_approved_git_push_success_uses_git_tool_without_real_push():
    print("Testing approved Git push success with mocked Git tool...")

    original_tool_run = aira_x_routes.ToolRouter.run
    tool_calls = []

    def fake_tool_run(tool_name, action, payload=None):
        payload = payload or {}

        tool_calls.append(
            {
                "tool_name": tool_name,
                "action": action,
                "payload": payload,
            }
        )

        if tool_name == "git_tool" and action == "branch":
            return {
                "success": True,
                "tool_name": "git_tool",
                "action": "branch",
                "command": "git branch --show-current",
                "output": "main",
                "return_code": 0,
            }

        if tool_name == "git_tool" and action == "status_branch":
            return {
                "success": True,
                "tool_name": "git_tool",
                "action": "status_branch",
                "command": "git status --short --branch",
                "output": "## main...origin/main",
                "return_code": 0,
            }

        if tool_name == "git_tool" and action == "remote_info":
            return {
                "success": True,
                "tool_name": "git_tool",
                "action": "remote_info",
                "command": "git remote -v",
                "output": (
                    "origin https://github.com/example/repo.git (fetch)\n"
                    "origin https://github.com/example/repo.git (push)"
                ),
                "return_code": 0,
            }

        if tool_name == "git_tool" and action == "last_commit":
            return {
                "success": True,
                "tool_name": "git_tool",
                "action": "last_commit",
                "command": "git log -1 --oneline",
                "output": "abc1234 Mock latest commit",
                "return_code": 0,
            }

        if tool_name == "git_tool" and action == "recent_commits":
            return {
                "success": True,
                "tool_name": "git_tool",
                "action": "recent_commits",
                "command": "git log --oneline -3",
                "output": "abc1234 Mock latest commit",
                "return_code": 0,
            }

        if tool_name == "git_tool" and action == "push":
            return {
                "success": True,
                "tool_name": "git_tool",
                "action": "push",
                "command": "git push origin main",
                "output": "Everything up-to-date",
                "return_code": 0,
            }

        return {
            "success": False,
            "tool_name": tool_name,
            "action": action,
            "output": "",
            "error": f"Unexpected mocked tool call: {tool_name}.{action}",
            "return_code": 1,
        }

    try:
        aira_x_routes.ToolRouter.run = staticmethod(fake_tool_run)

        initial_response = await run_aira_x(AiraXRunRequest(goal="git push"))

        assert_equal(
            initial_response["status"],
            "requires_approval",
            "Mocked Git push should first require approval",
        )

        assert_equal(
            initial_response["pending_action"],
            "git_tool:push origin current_branch",
            "Mocked Git push pending action",
        )

        approval_context = initial_response.get("approval_context")

        assert_true(
            isinstance(approval_context, dict),
            "Mocked Git push approval context should exist",
        )

        assert_equal(
            approval_context.get("type"),
            "git_push_preflight",
            "Mocked Git push approval context type",
        )

        run_id = initial_response["run_id"]

        approved_response = await approve_aira_x_action(
            AiraXApproveRequest(run_id=run_id)
        )

        assert_equal(
            approved_response["status"],
            "completed",
            "Approved mocked Git push workflow should complete",
        )

        assert_contains(
            approved_response["final_answer"],
            "Workflow completed successfully",
            "Approved mocked Git push final answer",
        )

        first_step = approved_response["plan"][0]

        assert_equal(
            first_step["tool_name"],
            "git_tool",
            "Approved mocked Git push tool selection",
        )

        assert_equal(
            first_step["tool_action"],
            "push",
            "Approved mocked Git push action selection",
        )

        assert_contains(
            first_step.get("result") or "",
            "Everything up-to-date",
            "Approved mocked Git push result",
        )

        assert_true(
            any(
                call["tool_name"] == "git_tool" and call["action"] == "push"
                for call in tool_calls
            ),
            "Approved mocked Git push should execute git_tool.push",
        )

        push_calls = [
            call
            for call in tool_calls
            if call["tool_name"] == "git_tool" and call["action"] == "push"
        ]

        assert_equal(
            len(push_calls),
            1,
            "Approved mocked Git push should execute exactly one push call",
        )

    finally:
        aira_x_routes.ToolRouter.run = original_tool_run

        if "initial_response" in locals() and initial_response.get("run_id"):
            WorkflowStore.delete(initial_response["run_id"])

    print("✅ Approved Git push success path passed")

    return True


async def test_double_approval_is_blocked_after_completion():
    print("Testing double approval is blocked after completion...")

    original_tool_run = aira_x_routes.ToolRouter.run
    tool_calls = []
    created_run_id = None

    def fake_tool_run(tool_name, action, payload=None):
        payload = payload or {}

        tool_calls.append(
            {
                "tool_name": tool_name,
                "action": action,
                "payload": payload,
            }
        )

        if tool_name == "git_tool" and action == "branch":
            return {
                "success": True,
                "tool_name": "git_tool",
                "action": "branch",
                "command": "git branch --show-current",
                "output": "main",
                "return_code": 0,
            }

        if tool_name == "git_tool" and action == "status_branch":
            return {
                "success": True,
                "tool_name": "git_tool",
                "action": "status_branch",
                "command": "git status --short --branch",
                "output": "## main...origin/main",
                "return_code": 0,
            }

        if tool_name == "git_tool" and action == "remote_info":
            return {
                "success": True,
                "tool_name": "git_tool",
                "action": "remote_info",
                "command": "git remote -v",
                "output": (
                    "origin https://github.com/example/repo.git (fetch)\n"
                    "origin https://github.com/example/repo.git (push)"
                ),
                "return_code": 0,
            }

        if tool_name == "git_tool" and action == "last_commit":
            return {
                "success": True,
                "tool_name": "git_tool",
                "action": "last_commit",
                "command": "git log -1 --oneline",
                "output": "abc1234 Mock latest commit",
                "return_code": 0,
            }

        if tool_name == "git_tool" and action == "recent_commits":
            return {
                "success": True,
                "tool_name": "git_tool",
                "action": "recent_commits",
                "command": "git log --oneline -3",
                "output": "abc1234 Mock latest commit",
                "return_code": 0,
            }

        if tool_name == "git_tool" and action == "push":
            return {
                "success": True,
                "tool_name": "git_tool",
                "action": "push",
                "command": "git push origin main",
                "output": "Everything up-to-date",
                "return_code": 0,
            }

        return {
            "success": False,
            "tool_name": tool_name,
            "action": action,
            "output": "",
            "error": f"Unexpected mocked tool call: {tool_name}.{action}",
            "return_code": 1,
        }

    try:
        aira_x_routes.ToolRouter.run = staticmethod(fake_tool_run)

        initial_response = await run_aira_x(AiraXRunRequest(goal="git push"))
        created_run_id = initial_response["run_id"]

        assert_equal(
            initial_response["status"],
            "requires_approval",
            "Double approval initial status",
        )

        first_approval = await approve_aira_x_action(
            AiraXApproveRequest(run_id=created_run_id)
        )

        assert_equal(
            first_approval["status"],
            "completed",
            "First approval should complete workflow",
        )

        second_approval = await approve_aira_x_action(
            AiraXApproveRequest(run_id=created_run_id)
        )

        assert_equal(
            second_approval["success"],
            False,
            "Second approval should be rejected safely",
        )

        assert_equal(
            second_approval["current_status"],
            "completed",
            "Second approval should report completed status",
        )

        assert_contains(
            second_approval["error"],
            "already be handled",
            "Second approval error should explain action is already handled",
        )

        push_calls = [
            call
            for call in tool_calls
            if call["tool_name"] == "git_tool" and call["action"] == "push"
        ]

        assert_equal(
            len(push_calls),
            1,
            "Double approval should not execute git push twice",
        )

    finally:
        aira_x_routes.ToolRouter.run = original_tool_run

        if created_run_id:
            WorkflowStore.delete(created_run_id)

    print("✅ Double approval block passed")

    return True


async def test_double_rejection_is_blocked_after_rejection():
    print("Testing double rejection is blocked after rejection...")

    initial_response = await run_aira_x(AiraXRunRequest(goal="git push"))
    run_id = initial_response["run_id"]

    try:
        assert_equal(
            initial_response["status"],
            "requires_approval",
            "Double rejection initial status",
        )

        first_rejection = await reject_aira_x_action(
            AiraXRejectRequest(run_id=run_id)
        )

        assert_equal(
            first_rejection["status"],
            "rejected",
            "First rejection should reject workflow",
        )

        second_rejection = await reject_aira_x_action(
            AiraXRejectRequest(run_id=run_id)
        )

        assert_equal(
            second_rejection["success"],
            False,
            "Second rejection should be rejected safely",
        )

        assert_equal(
            second_rejection["current_status"],
            "rejected",
            "Second rejection should report rejected status",
        )

        assert_contains(
            second_rejection["error"],
            "already be handled",
            "Second rejection error should explain action is already handled",
        )

        approval_after_rejection = await approve_aira_x_action(
            AiraXApproveRequest(run_id=run_id)
        )

        assert_equal(
            approval_after_rejection["success"],
            False,
            "Approval after rejection should be rejected safely",
        )

        assert_equal(
            approval_after_rejection["current_status"],
            "rejected",
            "Approval after rejection should report rejected status",
        )

    finally:
        WorkflowStore.delete(run_id)

    print("✅ Double rejection block passed")

    return True


async def test_concurrent_double_approval_uses_per_run_lock():
    print("Testing concurrent double approval uses per-run lock...")

    run_id = "test-concurrent-double-approval-lock"

    WorkflowStore.delete(run_id)

    state = AiraXState(
        user_goal="git push",
        run_id=run_id,
    )

    state.status = "requires_approval"
    state.decision = "stop_approval_required"
    state.current_step = 1
    state.final_answer = (
        "Approval required before executing: git_tool:push origin current_branch"
    )

    state.plan = [
        AiraXStep(
            id=1,
            title="Push Git changes",
            description="Push local commits to a remote Git repository.",
            assigned_agent="execution_agent",
            tool_name="git_tool",
            tool_action="push",
            tool_payload={"remote": "origin", "branch": None},
            status="blocked",
            error="This action requires user approval.",
        )
    ]

    state.memory["pending_action"] = "git_tool:push origin current_branch"
    state.memory["approval_context"] = {
        "type": "git_push_preflight",
        "tool_name": "git_tool",
        "tool_action": "push",
        "pending_action": "git_tool:push origin current_branch",
        "target_remote": "origin",
        "target_branch": "main",
        "branch": "main",
    }

    WorkflowStore.save(state)

    original_workflow_class = aira_x_routes.AiraXWorkflow
    resume_calls = []

    class FakeWorkflow:
        async def resume(self, approval_state):
            resume_calls.append(approval_state.run_id)

            await asyncio.sleep(0.05)

            current_step = next(
                (
                    step
                    for step in approval_state.plan
                    if step.id == approval_state.current_step
                ),
                None,
            )

            if current_step:
                current_step.status = "completed"
                current_step.error = None
                current_step.result = "Everything up-to-date"

            approval_state.status = "completed"
            approval_state.decision = "finish"
            approval_state.final_answer = "Workflow completed successfully."
            approval_state.execution_outputs.append(
                {
                    "step_id": 1,
                    "agent": "execution_agent",
                    "tool_used": "git_tool",
                    "tool_action": "push",
                    "tool_result": {
                        "success": True,
                        "output": "Everything up-to-date",
                    },
                }
            )

            return approval_state

    try:
        aira_x_routes.AiraXWorkflow = FakeWorkflow

        first_result, second_result = await asyncio.gather(
            approve_aira_x_action(AiraXApproveRequest(run_id=run_id)),
            approve_aira_x_action(AiraXApproveRequest(run_id=run_id)),
        )

        completed_results = [
            result
            for result in [first_result, second_result]
            if result.get("status") == "completed"
        ]

        blocked_results = [
            result
            for result in [first_result, second_result]
            if result.get("success") is False
        ]

        assert_equal(
            len(completed_results),
            1,
            "Exactly one concurrent approval should complete workflow",
        )

        assert_equal(
            len(blocked_results),
            1,
            "Exactly one concurrent approval should be blocked safely",
        )

        assert_equal(
            blocked_results[0]["current_status"],
            "completed",
            "Blocked concurrent approval should see completed workflow status",
        )

        assert_contains(
            blocked_results[0]["error"],
            "already be handled",
            "Blocked concurrent approval should explain approval was already handled",
        )

        assert_equal(
            len(resume_calls),
            1,
            "Concurrent double approval should call workflow.resume only once",
        )

        saved_state = WorkflowStore.get(run_id)

        assert_true(
            saved_state is not None,
            "Concurrent double approval saved state should exist",
        )

        assert_equal(
            saved_state.status,
            "completed",
            "Concurrent double approval final saved status",
        )

        assert_equal(
            saved_state.memory.get("approval_resolution", {}).get("status"),
            "approved",
            "Concurrent double approval should store approved resolution",
        )

        assert_true(
            saved_state.memory.get("approval_in_progress") is False,
            "Concurrent double approval should clear approval_in_progress",
        )

    finally:
        aira_x_routes.AiraXWorkflow = original_workflow_class
        WorkflowStore.delete(run_id)

        if hasattr(aira_x_routes, "_APPROVAL_LOCKS"):
            aira_x_routes._APPROVAL_LOCKS.pop(run_id, None)

    print("✅ Concurrent double approval lock passed")

    return True


async def test_concurrent_approve_reject_uses_per_run_lock():
    print("Testing concurrent approve/reject uses per-run lock...")

    run_id = "test-concurrent-approve-reject-lock"

    WorkflowStore.delete(run_id)

    state = AiraXState(
        user_goal="git push",
        run_id=run_id,
    )

    state.status = "requires_approval"
    state.decision = "stop_approval_required"
    state.current_step = 1
    state.final_answer = (
        "Approval required before executing: git_tool:push origin current_branch"
    )

    state.plan = [
        AiraXStep(
            id=1,
            title="Push Git changes",
            description="Push local commits to a remote Git repository.",
            assigned_agent="execution_agent",
            tool_name="git_tool",
            tool_action="push",
            tool_payload={"remote": "origin", "branch": None},
            status="blocked",
            error="This action requires user approval.",
        )
    ]

    state.memory["pending_action"] = "git_tool:push origin current_branch"
    state.memory["approval_context"] = {
        "type": "git_push_preflight",
        "tool_name": "git_tool",
        "tool_action": "push",
        "pending_action": "git_tool:push origin current_branch",
        "target_remote": "origin",
        "target_branch": "main",
        "branch": "main",
    }

    WorkflowStore.save(state)

    original_workflow_class = aira_x_routes.AiraXWorkflow
    resume_calls = []

    class FakeWorkflow:
        async def resume(self, approval_state):
            resume_calls.append(approval_state.run_id)

            await asyncio.sleep(0.05)

            current_step = next(
                (
                    step
                    for step in approval_state.plan
                    if step.id == approval_state.current_step
                ),
                None,
            )

            if current_step:
                current_step.status = "completed"
                current_step.error = None
                current_step.result = "Everything up-to-date"

            approval_state.status = "completed"
            approval_state.decision = "finish"
            approval_state.final_answer = "Workflow completed successfully."

            return approval_state

    try:
        aira_x_routes.AiraXWorkflow = FakeWorkflow

        approve_task = asyncio.create_task(
            approve_aira_x_action(AiraXApproveRequest(run_id=run_id))
        )

        await asyncio.sleep(0)

        reject_task = asyncio.create_task(
            reject_aira_x_action(AiraXRejectRequest(run_id=run_id))
        )

        approve_result, reject_result = await asyncio.gather(
            approve_task,
            reject_task,
        )

        assert_equal(
            approve_result["status"],
            "completed",
            "Concurrent approve/reject approval should complete workflow",
        )

        assert_equal(
            reject_result["success"],
            False,
            "Concurrent approve/reject rejection should be blocked safely",
        )

        assert_equal(
            reject_result["current_status"],
            "completed",
            "Concurrent reject should see completed workflow status",
        )

        assert_contains(
            reject_result["error"],
            "already be handled",
            "Concurrent reject should explain approval was already handled",
        )

        assert_equal(
            len(resume_calls),
            1,
            "Concurrent approve/reject should call workflow.resume only once",
        )

        saved_state = WorkflowStore.get(run_id)

        assert_true(
            saved_state is not None,
            "Concurrent approve/reject saved state should exist",
        )

        assert_equal(
            saved_state.status,
            "completed",
            "Concurrent approve/reject final saved status",
        )

        assert_equal(
            saved_state.memory.get("approval_resolution", {}).get("status"),
            "approved",
            "Concurrent approve/reject should store approved resolution",
        )

    finally:
        aira_x_routes.AiraXWorkflow = original_workflow_class
        WorkflowStore.delete(run_id)

        if hasattr(aira_x_routes, "_APPROVAL_LOCKS"):
            aira_x_routes._APPROVAL_LOCKS.pop(run_id, None)

    print("✅ Concurrent approve/reject lock passed")

    return True


async def test_git_push_failure_is_non_retryable():
    print("Testing Git push failure is non-retryable...")

    state = AiraXState(
        user_goal="git push",
        run_id="test-git-push-non-retryable-failure",
    )

    state.status = "failed"
    state.decision = "execution_failed"
    state.current_step = 1
    state.retry_count = 0
    state.max_retries = 3

    state.plan = [
        AiraXStep(
            id=1,
            title="Push Git changes",
            description="Push local commits to a remote Git repository.",
            assigned_agent="execution_agent",
            tool_name="git_tool",
            tool_action="push",
            tool_payload={"remote": "origin", "branch": "main"},
            status="failed",
            error="remote rejected push during test",
        )
    ]

    decision_agent = DecisionAgent()
    response_state = await decision_agent.run(state)

    assert_equal(
        response_state.decision,
        "stop_non_retryable_failure",
        "Git push failure should stop as non-retryable",
    )

    assert_equal(
        response_state.status,
        "failed",
        "Git push non-retryable failure status",
    )

    assert_contains(
        response_state.final_answer,
        "remote rejected push during test",
        "Git push non-retryable final answer should include real error",
    )

    assert_equal(
        response_state.retry_count,
        0,
        "Git push failure should not increment retry count",
    )

    print("✅ Git push non-retryable failure passed")

    return response_state


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


async def test_git_preflight_metrics_in_overview():
    print("Testing Git preflight metrics in Overview API...")

    write_run_id = "test-git-write-preflight-metrics"
    push_run_id = "test-git-push-preflight-metrics"

    WorkflowStore.delete(write_run_id)
    WorkflowStore.delete(push_run_id)

    write_state = AiraXState(
        user_goal='commit all changes with message "Metrics write preflight"',
        run_id=write_run_id,
    )
    write_state.status = "requires_approval"
    write_state.decision = "stop_approval_required"
    write_state.current_step = 1
    write_state.final_answer = "Approval required before executing: git_tool:stage_all"

    write_state.plan = [
        AiraXStep(
            id=1,
            title="Stage Git changes",
            description="Stage all current Git changes.",
            assigned_agent="execution_agent",
            tool_name="git_tool",
            tool_action="stage_all",
            tool_payload={},
            status="blocked",
            error="This action requires user approval.",
        ),
        AiraXStep(
            id=2,
            title="Commit Git changes",
            description="Create a local Git commit after staging.",
            assigned_agent="execution_agent",
            tool_name="git_tool",
            tool_action="commit",
            tool_payload={"message": "Metrics write preflight"},
            status="pending",
        ),
    ]
    write_state.memory["pending_action"] = "git_tool:stage_all"
    write_state.memory["approval_context"] = {
        "type": "git_write_preflight",
        "tool_name": "git_tool",
        "tool_action": "stage_all",
        "pending_action": "git_tool:stage_all",
        "commit_message": "Metrics write preflight",
        "branch": "main",
        "changed_files": "M backend/example.py",
        "diff_summary": "backend/example.py | 1 +",
    }

    push_state = AiraXState(
        user_goal="git push",
        run_id=push_run_id,
    )
    push_state.status = "requires_approval"
    push_state.decision = "stop_approval_required"
    push_state.current_step = 1
    push_state.final_answer = (
        "Approval required before executing: git_tool:push origin current_branch"
    )

    push_state.plan = [
        AiraXStep(
            id=1,
            title="Push Git changes",
            description="Push local commits to a remote Git repository.",
            assigned_agent="execution_agent",
            tool_name="git_tool",
            tool_action="push",
            tool_payload={"remote": "origin", "branch": None},
            status="blocked",
            error="This action requires user approval.",
        )
    ]
    push_state.memory["pending_action"] = "git_tool:push origin current_branch"
    push_state.memory["approval_context"] = {
        "type": "git_push_preflight",
        "tool_name": "git_tool",
        "tool_action": "push",
        "pending_action": "git_tool:push origin current_branch",
        "target_remote": "origin",
        "target_branch": "main",
        "branch": "main",
        "status_branch": "## main...origin/main",
        "remote_info": "origin https://github.com/example/repo.git (fetch)",
        "last_commit": "abc1234 Test commit",
        "recent_commits": "abc1234 Test commit",
    }

    try:
        WorkflowStore.save(write_state)
        WorkflowStore.save(push_state)

        overview_response = await get_aira_x_overview()
        metrics = overview_response["workflow_metrics"]

        assert_true(
            "git_preflight_runs" in metrics,
            "Overview metrics git_preflight_runs exists",
        )

        assert_true(
            "git_write_preflight_runs" in metrics,
            "Overview metrics git_write_preflight_runs exists",
        )

        assert_true(
            "git_push_preflight_runs" in metrics,
            "Overview metrics git_push_preflight_runs exists",
        )

        assert_true(
            metrics["git_write_preflight_runs"] >= 1,
            "Overview should count Git write preflight runs",
        )

        assert_true(
            metrics["git_push_preflight_runs"] >= 1,
            "Overview should count Git push preflight runs",
        )

        assert_true(
            metrics["git_preflight_runs"]
            >= metrics["git_write_preflight_runs"]
            + metrics["git_push_preflight_runs"],
            "Total Git preflight runs should include write and push preflights",
        )

        latest_runs = metrics["latest_runs"]

        latest_write_run = next(
            (
                run
                for run in latest_runs
                if run["run_id"] == write_run_id
            ),
            None,
        )

        latest_push_run = next(
            (
                run
                for run in latest_runs
                if run["run_id"] == push_run_id
            ),
            None,
        )

        assert_true(
            latest_write_run is not None,
            "Overview latest runs should include Git write preflight test run",
        )

        assert_true(
            latest_push_run is not None,
            "Overview latest runs should include Git push preflight test run",
        )

        assert_equal(
            latest_write_run["approval_context_type"],
            "git_write_preflight",
            "Latest write run should include git_write_preflight type",
        )

        assert_equal(
            latest_push_run["approval_context_type"],
            "git_push_preflight",
            "Latest push run should include git_push_preflight type",
        )

    finally:
        WorkflowStore.delete(write_run_id)
        WorkflowStore.delete(push_run_id)

    print("✅ Git preflight metrics in overview passed")

    return True


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



async def test_stale_approval_processing_recovered_in_detail_api():
    print("Testing stale approval processing recovery in detail API...")

    run_id = "test-stale-approval-detail-recovery"

    WorkflowStore.delete(run_id)

    try:
        WorkflowStore.save(build_stale_approval_processing_state(run_id))

        response = await get_aira_x_run(run_id)

        assert_equal(
            response["success"],
            True,
            "Stale approval detail response success",
        )

        run = response["run"]

        assert_equal(
            run["status"],
            "failed",
            "Stale approval detail recovered status",
        )

        assert_equal(
            run["decision"],
            "approval_processing_stale",
            "Stale approval detail recovered decision",
        )

        assert_equal(
            run["approval_in_progress"],
            False,
            "Stale approval detail should clear approval_in_progress",
        )

        assert_true(
            run["approval_stale_recovered"] is True,
            "Stale approval detail should mark stale recovery",
        )

        assert_equal(
            run["approval_resolution_status"],
            "stale_processing_recovered",
            "Stale approval detail resolution status",
        )

        assert_contains(
            run["final_answer"],
            "Approval processing became stale",
            "Stale approval detail final answer",
        )

        assert_equal(
            run["plan"][0]["status"],
            "failed",
            "Stale approval detail current step status",
        )

        assert_contains(
            run["plan"][0]["error"],
            "Approval processing became stale",
            "Stale approval detail current step error",
        )

        recovery_events = run["memory"].get("approval_recovery_events", [])

        assert_true(
            len(recovery_events) >= 1,
            "Stale approval detail should record recovery event",
        )

        assert_equal(
            recovery_events[-1]["reason"],
            "stale_approval_processing",
            "Stale approval detail recovery reason",
        )

        saved_state = WorkflowStore.get(run_id)

        assert_true(
            saved_state is not None,
            "Stale approval detail saved state should exist",
        )

        assert_equal(
            saved_state.status,
            "failed",
            "Stale approval detail saved status",
        )

        assert_true(
            saved_state.memory.get("approval_in_progress") is False,
            "Stale approval detail saved state should clear approval_in_progress",
        )

    finally:
        WorkflowStore.delete(run_id)

        if hasattr(aira_x_routes, "_APPROVAL_LOCKS"):
            aira_x_routes._APPROVAL_LOCKS.pop(run_id, None)

    print("✅ Stale approval detail recovery passed")

    return True


async def test_stale_approval_processing_recovered_in_runs_and_overview():
    print("Testing stale approval processing recovery in runs and overview...")

    run_id = "test-stale-approval-runs-overview-recovery"

    WorkflowStore.delete(run_id)

    try:
        WorkflowStore.save(build_stale_approval_processing_state(run_id))

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
            "Stale approval run should appear in workflow runs list",
        )

        assert_equal(
            matching_run["status"],
            "failed",
            "Stale approval runs summary recovered status",
        )

        assert_equal(
            matching_run["decision"],
            "approval_processing_stale",
            "Stale approval runs summary recovered decision",
        )

        assert_true(
            matching_run["approval_in_progress"] is False,
            "Stale approval runs summary should clear approval_in_progress",
        )

        assert_equal(
            matching_run["approval_resolution_status"],
            "stale_processing_recovered",
            "Stale approval runs summary resolution status",
        )

        overview_response = await get_aira_x_overview()
        latest_runs = overview_response["workflow_metrics"]["latest_runs"]

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
            "Stale approval run should appear in overview latest runs",
        )

        assert_equal(
            latest_matching_run["status"],
            "failed",
            "Stale approval overview recovered status",
        )

        assert_equal(
            latest_matching_run["decision"],
            "approval_processing_stale",
            "Stale approval overview recovered decision",
        )

        assert_true(
            latest_matching_run["approval_in_progress"] is False,
            "Stale approval overview should clear approval_in_progress",
        )

        assert_equal(
            latest_matching_run["approval_resolution_status"],
            "stale_processing_recovered",
            "Stale approval overview resolution status",
        )

    finally:
        WorkflowStore.delete(run_id)

        if hasattr(aira_x_routes, "_APPROVAL_LOCKS"):
            aira_x_routes._APPROVAL_LOCKS.pop(run_id, None)

    print("✅ Stale approval runs and overview recovery passed")

    return True


async def test_stale_approval_processing_blocks_late_approval_action():
    print("Testing stale approval processing blocks late approval action...")

    approve_run_id = "test-stale-approval-late-approve"
    reject_run_id = "test-stale-approval-late-reject"

    for run_id in [approve_run_id, reject_run_id]:
        WorkflowStore.delete(run_id)

    try:
        WorkflowStore.save(build_stale_approval_processing_state(approve_run_id))

        approval_response = await approve_aira_x_action(
            AiraXApproveRequest(run_id=approve_run_id)
        )

        assert_equal(
            approval_response["success"],
            False,
            "Late approval after stale recovery should fail safely",
        )

        assert_equal(
            approval_response["current_status"],
            "failed",
            "Late approval after stale recovery current status",
        )

        assert_equal(
            approval_response["decision"],
            "approval_processing_stale",
            "Late approval after stale recovery decision",
        )

        assert_true(
            approval_response["approval_in_progress"] is False,
            "Late approval after stale recovery should clear approval_in_progress",
        )

        assert_equal(
            approval_response["workflow"]["approval_resolution_status"],
            "stale_processing_recovered",
            "Late approval after stale recovery resolution status",
        )

        assert_contains(
            approval_response["workflow"]["final_answer"],
            "Approval processing became stale",
            "Late approval after stale recovery final answer",
        )

        WorkflowStore.save(build_stale_approval_processing_state(reject_run_id))

        rejection_response = await reject_aira_x_action(
            AiraXRejectRequest(run_id=reject_run_id)
        )

        assert_equal(
            rejection_response["success"],
            False,
            "Late rejection after stale recovery should fail safely",
        )

        assert_equal(
            rejection_response["current_status"],
            "failed",
            "Late rejection after stale recovery current status",
        )

        assert_equal(
            rejection_response["decision"],
            "approval_processing_stale",
            "Late rejection after stale recovery decision",
        )

        assert_true(
            rejection_response["approval_in_progress"] is False,
            "Late rejection after stale recovery should clear approval_in_progress",
        )

        assert_equal(
            rejection_response["workflow"]["approval_resolution_status"],
            "stale_processing_recovered",
            "Late rejection after stale recovery resolution status",
        )

    finally:
        for run_id in [approve_run_id, reject_run_id]:
            WorkflowStore.delete(run_id)

            if hasattr(aira_x_routes, "_APPROVAL_LOCKS"):
                aira_x_routes._APPROVAL_LOCKS.pop(run_id, None)

    print("✅ Stale approval late action block passed")

    return True


async def test_active_approval_lock_prevents_stale_recovery():
    print("Testing active approval lock prevents stale recovery...")

    run_id = "test-active-approval-lock-prevents-stale-recovery"

    WorkflowStore.delete(run_id)

    approval_lock = aira_x_routes._get_approval_lock(run_id)

    try:
        WorkflowStore.save(build_stale_approval_processing_state(run_id))

        await approval_lock.acquire()

        response = await get_aira_x_run(run_id)

        assert_equal(
            response["success"],
            True,
            "Active lock stale approval detail response success",
        )

        run = response["run"]

        assert_equal(
            run["status"],
            "requires_approval",
            "Active lock should prevent stale recovery status change",
        )

        assert_equal(
            run["decision"],
            "stop_approval_required",
            "Active lock should preserve decision",
        )

        assert_true(
            run["approval_in_progress"] is True,
            "Active lock should preserve approval_in_progress",
        )

        assert_equal(
            run["approval_resolution_status"],
            "approved",
            "Active lock should preserve original approval resolution",
        )

        assert_true(
            run.get("approval_stale_recovered") is False,
            "Active lock should not mark stale recovery",
        )

    finally:
        if approval_lock.locked():
            approval_lock.release()

        WorkflowStore.delete(run_id)

        if hasattr(aira_x_routes, "_APPROVAL_LOCKS"):
            aira_x_routes._APPROVAL_LOCKS.pop(run_id, None)

    print("✅ Active approval lock stale recovery guard passed")

    return True



async def test_stale_approval_recovery_metrics_in_runs_and_overview():
    print("Testing stale approval recovery metrics in runs and overview...")

    run_id = "test-stale-approval-recovery-metrics"

    WorkflowStore.delete(run_id)

    try:
        WorkflowStore.save(build_stale_approval_processing_state(run_id))

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
            "Stale approval metrics run should appear in workflow runs list",
        )

        assert_true(
            matching_run["approval_stale_recovered"] is True,
            "Workflow run summary should mark stale approval as recovered",
        )

        assert_true(
            matching_run["has_approval_recovery"] is True,
            "Workflow run summary should mark approval recovery as present",
        )

        assert_true(
            matching_run["approval_recovery_count"] >= 1,
            "Workflow run summary should include approval recovery count",
        )

        assert_true(
            isinstance(matching_run.get("approval_recovery_events"), list),
            "Workflow run summary should include approval recovery events list",
        )

        assert_equal(
            matching_run["approval_recovery_events"][-1]["reason"],
            "stale_approval_processing",
            "Workflow run summary should include stale approval recovery reason",
        )

        assert_equal(
            matching_run["approval_resolution_status"],
            "stale_processing_recovered",
            "Workflow run summary should include stale recovery resolution status",
        )

        overview_response = await get_aira_x_overview()
        metrics = overview_response["workflow_metrics"]

        assert_true(
            "stale_approval_recovery_runs" in metrics,
            "Overview metrics should include stale_approval_recovery_runs",
        )

        assert_true(
            "approval_stale_recovered_runs" in metrics,
            "Overview metrics should include approval_stale_recovered_runs",
        )

        assert_true(
            "total_approval_recovery_events" in metrics,
            "Overview metrics should include total_approval_recovery_events",
        )

        assert_true(
            metrics["stale_approval_recovery_runs"] >= 1,
            "Overview should count stale approval recovery runs",
        )

        assert_true(
            metrics["approval_stale_recovered_runs"] >= 1,
            "Overview should count approval stale recovered runs alias",
        )

        assert_true(
            metrics["total_approval_recovery_events"] >= 1,
            "Overview should count approval recovery events",
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
            "Stale approval metrics run should appear in overview latest runs",
        )

        assert_true(
            latest_matching_run["approval_stale_recovered"] is True,
            "Overview latest run should mark stale approval as recovered",
        )

        assert_true(
            latest_matching_run["has_approval_recovery"] is True,
            "Overview latest run should mark approval recovery as present",
        )

        assert_true(
            latest_matching_run["approval_recovery_count"] >= 1,
            "Overview latest run should include approval recovery count",
        )

        assert_equal(
            latest_matching_run["approval_resolution_status"],
            "stale_processing_recovered",
            "Overview latest run should include stale recovery resolution status",
        )

    finally:
        WorkflowStore.delete(run_id)

        if hasattr(aira_x_routes, "_APPROVAL_LOCKS"):
            aira_x_routes._APPROVAL_LOCKS.pop(run_id, None)

    print("✅ Stale approval recovery metrics passed")

    return True


async def test_approval_resolution_fields_in_runs_and_overview():
    print("Testing approval resolution fields in runs and overview...")

    approved_run_id = "test-approval-resolution-approved"
    rejected_run_id = "test-approval-resolution-rejected"
    failed_run_id = "test-approval-resolution-resume-failed"
    processing_run_id = "test-approval-resolution-processing"

    for run_id in [
        approved_run_id,
        rejected_run_id,
        failed_run_id,
        processing_run_id,
    ]:
        WorkflowStore.delete(run_id)

    approved_state = AiraXState(
        user_goal="git push",
        run_id=approved_run_id,
    )
    approved_state.status = "completed"
    approved_state.decision = "finish"
    approved_state.current_step = 1
    approved_state.final_answer = "Workflow completed successfully."
    approved_state.memory["pending_action"] = "git_tool:push origin main"
    approved_state.memory["approval_in_progress"] = False
    approved_state.memory["approval_resolution"] = {
        "status": "approved",
        "action": "git_tool:push origin main",
        "requested_at": "2026-01-01T00:00:00+00:00",
        "completed_at": "2026-01-01T00:00:01+00:00",
        "final_status": "completed",
        "final_decision": "finish",
    }
    approved_state.memory["approval_context"] = {
        "type": "git_push_preflight",
        "tool_name": "git_tool",
        "tool_action": "push",
        "pending_action": "git_tool:push origin main",
        "target_remote": "origin",
        "target_branch": "main",
        "branch": "main",
    }
    approved_state.plan = [
        AiraXStep(
            id=1,
            title="Push Git changes",
            description="Push local commits to a remote Git repository.",
            assigned_agent="execution_agent",
            tool_name="git_tool",
            tool_action="push",
            tool_payload={"remote": "origin", "branch": "main"},
            status="completed",
            result="Everything up-to-date",
        )
    ]

    rejected_state = AiraXState(
        user_goal="git push",
        run_id=rejected_run_id,
    )
    rejected_state.status = "rejected"
    rejected_state.decision = "approval_rejected"
    rejected_state.current_step = 1
    rejected_state.final_answer = (
        "User rejected the action: git_tool:push origin current_branch."
    )
    rejected_state.memory["pending_action"] = "git_tool:push origin current_branch"
    rejected_state.memory["approval_in_progress"] = False
    rejected_state.memory["approval_resolution"] = {
        "status": "rejected",
        "action": "git_tool:push origin current_branch",
        "requested_at": "2026-01-01T00:01:00+00:00",
        "completed_at": "2026-01-01T00:01:01+00:00",
        "final_status": "rejected",
        "final_decision": "approval_rejected",
    }
    rejected_state.memory["approval_context"] = {
        "type": "git_push_preflight",
        "tool_name": "git_tool",
        "tool_action": "push",
        "pending_action": "git_tool:push origin current_branch",
        "target_remote": "origin",
        "target_branch": "main",
        "branch": "main",
    }
    rejected_state.plan = [
        AiraXStep(
            id=1,
            title="Push Git changes",
            description="Push local commits to a remote Git repository.",
            assigned_agent="execution_agent",
            tool_name="git_tool",
            tool_action="push",
            tool_payload={"remote": "origin", "branch": None},
            status="rejected",
            error="User rejected the action.",
        )
    ]

    failed_state = AiraXState(
        user_goal="git push",
        run_id=failed_run_id,
    )
    failed_state.status = "failed"
    failed_state.decision = "approval_resume_failed"
    failed_state.current_step = 1
    failed_state.final_answer = "Workflow failed after approval: mocked failure"
    failed_state.memory["pending_action"] = "git_tool:push origin main"
    failed_state.memory["approval_in_progress"] = False
    failed_state.memory["approval_resolution"] = {
        "status": "approved_but_resume_failed",
        "action": "git_tool:push origin main",
        "completed_at": "2026-01-01T00:02:01+00:00",
        "error": "mocked failure",
    }
    failed_state.plan = [
        AiraXStep(
            id=1,
            title="Push Git changes",
            description="Push local commits to a remote Git repository.",
            assigned_agent="execution_agent",
            tool_name="git_tool",
            tool_action="push",
            tool_payload={"remote": "origin", "branch": "main"},
            status="failed",
            error="mocked failure",
        )
    ]

    processing_state = AiraXState(
        user_goal="git push",
        run_id=processing_run_id,
    )
    processing_state.status = "requires_approval"
    processing_state.decision = "stop_approval_required"
    processing_state.current_step = 1
    processing_state.final_answer = (
        "Approval required before executing: git_tool:push origin current_branch"
    )
    processing_state.memory["pending_action"] = "git_tool:push origin current_branch"
    processing_state.memory["approval_in_progress"] = True
    processing_state.memory["approval_context"] = {
        "type": "git_push_preflight",
        "tool_name": "git_tool",
        "tool_action": "push",
        "pending_action": "git_tool:push origin current_branch",
        "target_remote": "origin",
        "target_branch": "main",
        "branch": "main",
    }
    processing_state.plan = [
        AiraXStep(
            id=1,
            title="Push Git changes",
            description="Push local commits to a remote Git repository.",
            assigned_agent="execution_agent",
            tool_name="git_tool",
            tool_action="push",
            tool_payload={"remote": "origin", "branch": None},
            status="blocked",
            error="This action requires user approval.",
        )
    ]

    try:
        WorkflowStore.save(approved_state)
        WorkflowStore.save(rejected_state)
        WorkflowStore.save(failed_state)
        WorkflowStore.save(processing_state)

        runs_response = await list_aira_x_runs()

        runs_by_id = {
            run["run_id"]: run
            for run in runs_response["runs"]
            if run["run_id"]
            in {
                approved_run_id,
                rejected_run_id,
                failed_run_id,
                processing_run_id,
            }
        }

        assert_equal(
            len(runs_by_id),
            4,
            "Workflow runs summary should include all approval resolution test runs",
        )

        approved_summary = runs_by_id[approved_run_id]
        rejected_summary = runs_by_id[rejected_run_id]
        failed_summary = runs_by_id[failed_run_id]
        processing_summary = runs_by_id[processing_run_id]

        assert_true(
            approved_summary["approval_in_progress"] is False,
            "Approved summary should mark approval_in_progress false",
        )

        assert_equal(
            approved_summary["approval_resolution_status"],
            "approved",
            "Approved summary approval resolution status",
        )

        assert_equal(
            approved_summary["approval_resolution_action"],
            "git_tool:push origin main",
            "Approved summary approval resolution action",
        )

        assert_true(
            isinstance(approved_summary["approval_resolution"], dict),
            "Approved summary should include approval resolution object",
        )

        assert_equal(
            rejected_summary["approval_resolution_status"],
            "rejected",
            "Rejected summary approval resolution status",
        )

        assert_equal(
            rejected_summary["approval_resolution_action"],
            "git_tool:push origin current_branch",
            "Rejected summary approval resolution action",
        )

        assert_equal(
            failed_summary["approval_resolution_status"],
            "approved_but_resume_failed",
            "Failed summary approval resolution status",
        )

        assert_true(
            processing_summary["approval_in_progress"] is True,
            "Processing summary should mark approval_in_progress true",
        )

        assert_true(
            "approval_resolution" in processing_summary,
            "Processing summary should include approval_resolution key",
        )

        overview_response = await get_aira_x_overview()
        metrics = overview_response["workflow_metrics"]

        assert_true(
            "approval_in_progress_runs" in metrics,
            "Overview metrics should include approval_in_progress_runs",
        )

        assert_true(
            "approval_resolved_runs" in metrics,
            "Overview metrics should include approval_resolved_runs",
        )

        assert_true(
            "approval_approved_runs" in metrics,
            "Overview metrics should include approval_approved_runs",
        )

        assert_true(
            "approval_rejected_runs" in metrics,
            "Overview metrics should include approval_rejected_runs",
        )

        assert_true(
            "approval_resume_failed_runs" in metrics,
            "Overview metrics should include approval_resume_failed_runs",
        )

        assert_true(
            metrics["approval_in_progress_runs"] >= 1,
            "Overview should count approval_in_progress runs",
        )

        assert_true(
            metrics["approval_resolved_runs"] >= 3,
            "Overview should count approval resolution runs",
        )

        assert_true(
            metrics["approval_approved_runs"] >= 1,
            "Overview should count approved approval resolutions",
        )

        assert_true(
            metrics["approval_rejected_runs"] >= 1,
            "Overview should count rejected approval resolutions",
        )

        assert_true(
            metrics["approval_resume_failed_runs"] >= 1,
            "Overview should count approved-but-resume-failed resolutions",
        )

        latest_runs = metrics["latest_runs"]

        latest_by_id = {
            run["run_id"]: run
            for run in latest_runs
            if run["run_id"]
            in {
                approved_run_id,
                rejected_run_id,
                failed_run_id,
                processing_run_id,
            }
        }

        assert_equal(
            len(latest_by_id),
            4,
            "Overview latest runs should include approval resolution test runs",
        )

        assert_equal(
            latest_by_id[approved_run_id]["approval_resolution_status"],
            "approved",
            "Overview latest run should include approved resolution status",
        )

        assert_equal(
            latest_by_id[rejected_run_id]["approval_resolution_status"],
            "rejected",
            "Overview latest run should include rejected resolution status",
        )

        assert_equal(
            latest_by_id[failed_run_id]["approval_resolution_status"],
            "approved_but_resume_failed",
            "Overview latest run should include resume failed resolution status",
        )

        assert_true(
            latest_by_id[processing_run_id]["approval_in_progress"] is True,
            "Overview latest run should include approval_in_progress flag",
        )

    finally:
        for run_id in [
            approved_run_id,
            rejected_run_id,
            failed_run_id,
            processing_run_id,
        ]:
            WorkflowStore.delete(run_id)

    print("✅ Approval resolution fields in runs and overview passed")

    return True


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
    assert_true(
        "git_preflight_runs" in metrics,
        "Overview metrics git_preflight_runs exists",
    )
    assert_true(
        "git_write_preflight_runs" in metrics,
        "Overview metrics git_write_preflight_runs exists",
    )
    assert_true(
        "git_push_preflight_runs" in metrics,
        "Overview metrics git_push_preflight_runs exists",
    )
    assert_true(
        "stale_approval_recovery_runs" in metrics,
        "Overview metrics stale_approval_recovery_runs exists",
    )
    assert_true(
        "approval_stale_recovered_runs" in metrics,
        "Overview metrics approval_stale_recovered_runs exists",
    )
    assert_true(
        "total_approval_recovery_events" in metrics,
        "Overview metrics total_approval_recovery_events exists",
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
    await test_approved_git_push_success_uses_git_tool_without_real_push()
    await test_concurrent_double_approval_uses_per_run_lock()
    await test_concurrent_approve_reject_uses_per_run_lock()
    await test_double_approval_is_blocked_after_completion()
    await test_double_rejection_is_blocked_after_rejection()
    await test_stale_approval_processing_recovered_in_detail_api()
    await test_stale_approval_processing_recovered_in_runs_and_overview()
    await test_stale_approval_recovery_metrics_in_runs_and_overview()
    await test_stale_approval_processing_blocks_late_approval_action()
    await test_active_approval_lock_prevents_stale_recovery()
    await test_git_push_failure_is_non_retryable()
    await test_workflow_runs_include_git_preflight_summary()
    await test_overview_latest_runs_include_git_preflight_summary()
    await test_git_preflight_metrics_in_overview()
    await test_commit_rejection_triggers_unstage_cleanup()
    await test_approval_resolution_fields_in_runs_and_overview()
    await test_cleanup_metrics_in_runs_and_overview()

    await test_tool_registry_api()
    await test_agent_registry_api()
    await test_platform_overview_api()
    await test_workflow_runs_api(sample_run)
    await test_workflow_detail_api(sample_run)

    print("\n🎉 All AIRA-X regression tests passed successfully!\n")


if __name__ == "__main__":
    asyncio.run(main())
