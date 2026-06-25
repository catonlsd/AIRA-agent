// Pure-logic tests for the active-scope helpers. Node's built-in runner, no deps.
import { test } from "node:test";
import assert from "node:assert/strict";

import { PERSONAL_SCOPE_LABEL, scopeLabel, workspaceHeaders } from "./scope.ts";

test("workspaceHeaders attaches the workspace header when active", () => {
  assert.deepEqual(workspaceHeaders("ws-1"), { "X-Workspace-Id": "ws-1" });
});

test("workspaceHeaders is empty (Personal) when no workspace is active", () => {
  assert.deepEqual(workspaceHeaders(null), {});
  assert.deepEqual(workspaceHeaders(undefined), {});
  assert.deepEqual(workspaceHeaders(""), {});
});

test("scopeLabel reads the workspace name, else Personal", () => {
  assert.equal(scopeLabel("Team Alpha"), "Team Alpha");
  assert.equal(scopeLabel(null), PERSONAL_SCOPE_LABEL);
  assert.equal(scopeLabel("   "), PERSONAL_SCOPE_LABEL);
});
