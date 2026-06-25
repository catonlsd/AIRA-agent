// Pure-logic tests for the search/pins helpers. Node's built-in runner, no deps.
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  canPin,
  hasResults,
  isResumable,
  pinRefFor,
  resultActionLabel,
  type SearchResult,
  type SearchResults,
} from "./search.ts";

const result = (over: Partial<SearchResult> = {}): SearchResult => ({
  result_type: "artifact",
  title: "Q3 plan",
  summary: "PPTX artifact",
  status: "completed",
  created_at: null,
  download_url: "/artifacts/tok/q3.pptx",
  ref_type: "artifact",
  ref_id: "q3.pptx",
  ...over,
});

test("resultActionLabel is honest per result type", () => {
  assert.equal(resultActionLabel(result({ result_type: "artifact" })), "Download");
  assert.equal(resultActionLabel(result({ result_type: "run", action: "Resume" })), "Resume");
  assert.equal(resultActionLabel(result({ result_type: "run", action: "Retry" })), "Retry");
  assert.equal(resultActionLabel(result({ result_type: "document" })), "Open");
  assert.equal(resultActionLabel(result({ result_type: "activity", ref_type: undefined, ref_id: undefined })), null);
});

test("only resource-backed results are pinnable", () => {
  assert.equal(canPin(result()), true);
  assert.equal(canPin(result({ result_type: "activity", ref_type: undefined, ref_id: undefined })), false);
});

test("pinRefFor builds a clean ref or null", () => {
  assert.deepEqual(pinRefFor(result()), {
    ref_type: "artifact",
    ref_id: "q3.pptx",
    title: "Q3 plan",
    subtitle: "PPTX artifact",
  });
  assert.equal(pinRefFor(result({ ref_type: undefined, ref_id: undefined })), null);
});

test("isResumable is true only for genuinely pending runs", () => {
  assert.equal(isResumable({ run_kind: "resume", resumable: true }), true);
  assert.equal(isResumable({ run_kind: "continue", resumable: false }), false);
  assert.equal(isResumable({ run_kind: "continue", resumable: true }), false);
});

test("hasResults reflects whether there are results", () => {
  const base: SearchResults = { scope: { kind: "workspace", label: "Team", is_workspace: true }, results: [] };
  assert.equal(hasResults(base), false);
  assert.equal(hasResults(null), false);
  assert.equal(hasResults({ ...base, results: [result()] }), true);
});
