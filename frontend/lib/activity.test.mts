// Pure-logic tests for the activity helpers. Node's built-in runner, no deps.
import { test } from "node:test";
import assert from "node:assert/strict";

import { eventLine, hasActivity, isWarn, type ActivityEvent, type RecentActivity } from "./activity.ts";

const ev = (over: Partial<ActivityEvent> = {}): ActivityEvent => ({
  type: "artifact_created",
  title: "Created “Roadmap” (PPTX)",
  actor: "Ada",
  status: "completed",
  severity: "info",
  resource_type: "artifact",
  created_at: null,
  ...over,
});

test("eventLine attributes to the actor when present", () => {
  assert.equal(eventLine(ev()), "Ada · Created “Roadmap” (PPTX)");
  assert.equal(eventLine(ev({ actor: null })), "Created “Roadmap” (PPTX)");
});

test("isWarn flags failures only", () => {
  assert.equal(isWarn(ev({ severity: "warn" })), true);
  assert.equal(isWarn(ev({ severity: "info" })), false);
});

test("hasActivity reflects whether there are events", () => {
  const base: RecentActivity = { scope: { kind: "workspace", label: "Team", is_workspace: true }, events: [] };
  assert.equal(hasActivity(base), false);
  assert.equal(hasActivity(null), false);
  assert.equal(hasActivity({ ...base, events: [ev()] }), true);
});
