// Pure-logic tests for the run-history helpers. Node's built-in runner, no deps.
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  actionLabel,
  hasRuns,
  isResumable,
  runTone,
  type RecentRuns,
  type RunItem,
} from "./runs.ts";

const run = (over: Partial<RunItem> = {}): RunItem => ({
  id: "artifact:deck.pptx",
  kind: "continue",
  title: "Roadmap",
  status: "completed",
  summary: "Finished PPTX — continue to build on it.",
  resumable: false,
  action: "Continue",
  download_url: "/artifacts/tok/deck.pptx",
  created_at: null,
  ...over,
});

test("actionLabel is honest per kind", () => {
  assert.equal(actionLabel(run({ kind: "resume", action: "Resume" })), "Resume");
  assert.equal(actionLabel(run({ kind: "continue", action: "Continue" })), "Continue");
  assert.equal(actionLabel(run({ kind: "retry", action: "Retry" })), "Retry");
  // Falls back to the kind when the server omits a label.
  assert.equal(actionLabel(run({ kind: "resume", action: "" })), "Resume");
});

test("isResumable is true only for genuinely pending runs", () => {
  assert.equal(isResumable(run({ kind: "resume", resumable: true })), true);
  assert.equal(isResumable(run({ kind: "continue", resumable: false })), false);
  // A completed run flagged resumable by mistake is still not resumed.
  assert.equal(isResumable(run({ kind: "continue", resumable: true })), false);
});

test("runTone warns on failures only", () => {
  assert.equal(runTone(run({ status: "failed" })), "warn");
  assert.equal(runTone(run({ status: "completed" })), "accent");
  assert.equal(runTone(run({ status: "requires_approval" })), "accent");
});

test("hasRuns reflects whether there are runs", () => {
  const base: RecentRuns = { scope: { kind: "workspace", label: "Team", is_workspace: true }, runs: [] };
  assert.equal(hasRuns(base), false);
  assert.equal(hasRuns(null), false);
  assert.equal(hasRuns({ ...base, runs: [run()] }), true);
});
