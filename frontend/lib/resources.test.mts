// Pure-logic tests for the shared-resource helpers. Node's built-in runner, no deps.
import { test } from "node:test";
import assert from "node:assert/strict";

import { isEmpty, relativeTime, type RecentResources } from "./resources.ts";

const base: RecentResources = {
  scope: { kind: "workspace", label: "Team", is_workspace: true },
  artifacts: [],
  documents: [],
  runs: [],
};

test("relativeTime renders calm, human values", () => {
  const now = new Date();
  assert.equal(relativeTime(now.toISOString()), "just now");
  assert.equal(relativeTime(new Date(now.getTime() - 5 * 60_000).toISOString()), "5m ago");
  assert.equal(relativeTime(new Date(now.getTime() - 3 * 3_600_000).toISOString()), "3h ago");
  assert.equal(relativeTime(new Date(now.getTime() - 2 * 86_400_000).toISOString()), "2d ago");
});

test("relativeTime is safe on missing/invalid input", () => {
  assert.equal(relativeTime(null), "");
  assert.equal(relativeTime(undefined), "");
  assert.equal(relativeTime("not-a-date"), "");
});

test("isEmpty reflects whether the scope has anything to show", () => {
  assert.equal(isEmpty(base), true);
  assert.equal(isEmpty(null), true);
  assert.equal(isEmpty({ ...base, documents: [{ name: "x.pdf", type: "PDF", chunks: 3, created_at: null }] }), false);
  assert.equal(
    isEmpty({ ...base, artifacts: [{ title: "Deck", filename: "d.pptx", type: "PPTX", size: "1 KB", created_at: "", download_url: "/artifacts/t/d.pptx" }] }),
    false
  );
});
