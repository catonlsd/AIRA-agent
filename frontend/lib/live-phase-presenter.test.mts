// Presenter / live-state tests for the streaming phase model.
// Runs on Node's built-in test runner with native TypeScript stripping — no
// extra dependencies, no bundler. Run with `npm test`.
//   node --test "lib/**/*.test.mts"
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  finalLivePhase,
  livePhaseForMode,
  livePhaseForStage,
  reduceLivePhase,
  type SSELiteEvent,
} from "./live-phase-presenter.ts";

const traceStage = (stage: string): SSELiteEvent => ({ type: "trace", data: { event: "stage", stage } });
const traceMode = (mode: string): SSELiteEvent => ({ type: "trace", data: { event: "classified", mode } });

// ── Stage → phase mapping (no raw enum leakage) ──────────────────────────────

test("execution stage events map to the correct live phases", () => {
  assert.equal(livePhaseForStage("planning")?.key, "planning");
  assert.equal(livePhaseForStage("executing_workflow")?.key, "executing");
  assert.equal(livePhaseForStage("executing_step")?.key, "executing");
  assert.equal(livePhaseForStage("validation")?.key, "validating");
});

test("startup validation events map cleanly", () => {
  assert.equal(livePhaseForStage("startup_validation_started")?.key, "starting_app");
  assert.equal(livePhaseForStage("waiting_for_ready")?.key, "readiness");
  assert.equal(livePhaseForStage("healthcheck_probing")?.key, "healthcheck");
});

test("repair and retry events map cleanly", () => {
  assert.equal(livePhaseForStage("repairing")?.key, "repairing");
  assert.equal(livePhaseForStage("step_repairing")?.key, "repairing");
  assert.equal(livePhaseForStage("retrying")?.key, "retrying");
});

test("approval-gate stages surface as a waiting phase", () => {
  assert.equal(livePhaseForStage("plan_ready")?.key, "awaiting_approval");
  assert.equal(livePhaseForStage("awaiting_action_approval")?.key, "awaiting_approval");
  assert.equal(livePhaseForStage("plan_ready")?.tone, "warn");
});

test("labels are user-facing and never the raw backend name", () => {
  const phase = livePhaseForStage("startup_validation_started")!;
  assert.equal(phase.label, "Starting the generated app");
  assert.ok(!/startup_validation_started/.test(phase.label));
});

test("an unknown stage returns null so the caller keeps the prior phase", () => {
  assert.equal(livePhaseForStage("some_future_internal_stage"), null);
  assert.equal(livePhaseForStage(""), null);
  assert.equal(livePhaseForStage(undefined), null);
});

test("mode classification produces a sensible opening phase", () => {
  assert.equal(livePhaseForMode("web_research")?.key, "researching");
  assert.equal(livePhaseForMode("document_qa")?.key, "reading");
  assert.equal(livePhaseForMode("execution")?.key, "executing");
  assert.equal(livePhaseForMode("nonsense"), null);
});

// ── Final reconciliation overrides live state ────────────────────────────────

test("final completion / failure overrides the live phase", () => {
  assert.equal(finalLivePhase("completed", "runtime_validated").key, "completed");
  assert.equal(finalLivePhase("failed", "runtime_validation_failed").key, "failed");
  assert.equal(finalLivePhase("completed", "artifact_generation_failed").key, "failed");
});

test("skipped startup / rejected artifact resolve honestly, not as failures", () => {
  assert.equal(finalLivePhase("completed", "plan_executed").key, "skipped");
  assert.equal(finalLivePhase("completed", "artifact_rejected").key, "skipped");
});

test("approval-required final status resolves to the waiting phase", () => {
  assert.equal(finalLivePhase("plan_ready", "needs_plan_approval").key, "awaiting_approval");
  assert.equal(finalLivePhase("awaiting_action_approval", "").key, "awaiting_approval");
});

// ── Reducer: a streaming turn updates in place, final overrides ──────────────

test("reducer advances the phase as SSE events arrive, ignoring non-trace events", () => {
  let phase = reduceLivePhase(null, traceMode("execution"));
  assert.equal(phase?.key, "executing");

  // Tokens/sources must not move the phase.
  phase = reduceLivePhase(phase, { type: "token", data: { text: "hi" } });
  assert.equal(phase?.key, "executing");
  phase = reduceLivePhase(phase, { type: "source", data: {} });
  assert.equal(phase?.key, "executing");

  // The recorded phase journey advances live.
  const journey = ["planning", "executing_workflow", "validation", "startup_validation_started", "waiting_for_ready", "healthcheck_probing"];
  for (const stage of journey) phase = reduceLivePhase(phase, traceStage(stage));
  assert.equal(phase?.key, "healthcheck");
});

test("an unknown stage in the stream keeps the current phase (no flicker, no leak)", () => {
  let phase = reduceLivePhase(null, traceStage("validation"));
  assert.equal(phase?.key, "validating");
  phase = reduceLivePhase(phase, traceStage("brand_new_backend_stage"));
  assert.equal(phase?.key, "validating"); // unchanged
});

test("a repair-then-retry sequence is reflected, then final completion wins", () => {
  let phase = reduceLivePhase(null, traceStage("validation"));
  phase = reduceLivePhase(phase, traceStage("repairing"));
  assert.equal(phase?.key, "repairing");
  phase = reduceLivePhase(phase, traceStage("retrying"));
  assert.equal(phase?.key, "retrying");
  // Final event reconciles to a single honest end state.
  assert.equal(finalLivePhase("completed", "runtime_validated").key, "completed");
});
