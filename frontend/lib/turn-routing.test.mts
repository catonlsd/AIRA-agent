// Routing tests: which finalized turns become a workflow card vs an answer card.
import { test } from "node:test";
import assert from "node:assert/strict";

import { isWorkflowResult } from "./turn-routing.ts";

// ── Awaiting-approval turns stay in the answer card (Approve button lives there) ─

test("an artifact plan awaiting approval is NOT a workflow card", () => {
  // Regression: "make a PPT" classifies as research_then_execution, but a
  // plan_ready/artifact_pending turn must render its Approve control, not a
  // 'workflow result' shell that hides it and looks like a failure.
  assert.equal(
    isWorkflowResult({
      mode: "research_then_execution",
      status: "plan_ready",
      meta: { artifact_pending: true, approval_required: true },
    }),
    false
  );
});

test("a code plan awaiting approval is NOT a workflow card", () => {
  assert.equal(
    isWorkflowResult({ mode: "execution_planning", status: "plan_ready", meta: { approval_required: true } }),
    false
  );
});

test("a runtime-validation approval gate is NOT a workflow card", () => {
  assert.equal(isWorkflowResult({ mode: "execution", status: "awaiting_action_approval" }), false);
});

test("a clarification turn is NOT a workflow card", () => {
  assert.equal(isWorkflowResult({ mode: "clarification", status: "completed" }), false);
});

// ── Real runs / workflow-level approval DO render as a workflow card ──────────

test("a completed execution run IS a workflow card", () => {
  assert.equal(isWorkflowResult({ mode: "execution", status: "completed" }), true);
  assert.equal(isWorkflowResult({ mode: "research_then_execution", status: "completed" }), true);
});

test("a git-preflight workflow approval IS a workflow card", () => {
  assert.equal(
    isWorkflowResult({ mode: "execution", status: "requires_approval", requires_approval: true }),
    true
  );
});

// ── Plain answers never become workflow cards ────────────────────────────────

test("general chat / document answers are NOT workflow cards", () => {
  assert.equal(isWorkflowResult({ mode: "general_chat", status: "completed" }), false);
  assert.equal(isWorkflowResult({ mode: "document_qa", status: "completed" }), false);
  assert.equal(isWorkflowResult({}), false);
});
