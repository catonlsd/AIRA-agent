// Pure-logic tests for the workspace/scope helpers. Node's built-in runner, no deps.
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  activeWorkspace,
  canEdit,
  canManage,
  reconcileActiveId,
  roleLabel,
  type Workspace,
} from "./workspaces.ts";

const ws = (id: string, over: Partial<Workspace> = {}): Workspace => ({
  id, name: `W${id}`, owner_account_id: "a", role: "owner", created_at: null, ...over,
});

test("role capabilities map correctly", () => {
  assert.equal(canManage("owner"), true);
  assert.equal(canManage("editor"), false);
  assert.equal(canEdit("editor"), true);
  assert.equal(canEdit("viewer"), false);
  assert.equal(canManage(null), false);
});

test("roleLabel is human and falls back cleanly", () => {
  assert.equal(roleLabel("owner"), "Owner");
  assert.equal(roleLabel("viewer"), "Viewer");
  assert.equal(roleLabel(undefined), "Member");
});

test("activeWorkspace resolves the selection, null for Personal", () => {
  const list = [ws("1"), ws("2")];
  assert.equal(activeWorkspace(list, "2")?.id, "2");
  assert.equal(activeWorkspace(list, ""), null); // Personal
  assert.equal(activeWorkspace(list, "missing"), null);
});

test("reconcileActiveId drops a stale selection (e.g. removed) -> Personal", () => {
  const list = [ws("1")];
  assert.equal(reconcileActiveId(list, "1"), "1"); // still a member
  assert.equal(reconcileActiveId(list, "gone"), ""); // no longer a member -> Personal
  assert.equal(reconcileActiveId(list, null), ""); // already Personal
  assert.equal(reconcileActiveId([], "1"), ""); // not in any workspace
});
