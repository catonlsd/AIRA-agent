// Pure-logic tests for the preferences surface data layer. Runs on Node's
// built-in test runner with native TypeScript stripping — no deps. `npm test`.
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  isSet,
  sanitizeItems,
  savedCount,
  selectedLabel,
  type PreferenceItem,
} from "./preferences.ts";

const item = (over: Partial<PreferenceItem> = {}): PreferenceItem => ({
  key: "answer_length",
  label: "Answer length",
  description: "How long answers should be.",
  options: [
    { value: "concise", label: "Concise" },
    { value: "detailed", label: "Detailed" },
  ],
  value: null,
  ...over,
});

// ── Human-friendly labels ────────────────────────────────────────────────────

test("selectedLabel reads the option label, not the raw value", () => {
  assert.equal(selectedLabel(item({ value: "concise" })), "Concise");
  assert.equal(selectedLabel(item({ value: "detailed" })), "Detailed");
});

test("an unset preference reads as a calm 'Not set' (never null/internal)", () => {
  assert.equal(selectedLabel(item({ value: null })), "Not set");
});

test("isSet / savedCount reflect only saved values", () => {
  assert.equal(isSet(item({ value: null })), false);
  assert.equal(isSet(item({ value: "concise" })), true);
  assert.equal(
    savedCount([item({ value: "concise" }), item({ key: "headings", value: null })]),
    1
  );
});

// ── Defensive sanitisation: no raw/internal payload reaches the UI ───────────

test("sanitizeItems drops malformed entries and non-arrays", () => {
  assert.deepEqual(sanitizeItems(null), []);
  assert.deepEqual(sanitizeItems("nope"), []);
  const cleaned = sanitizeItems([
    item(),
    { key: 123, label: "bad" }, // malformed
    { not: "a preference" }, // junk
  ]);
  assert.equal(cleaned.length, 1);
  assert.equal(cleaned[0].key, "answer_length");
});

test("a single-option (toggle) preference still labels cleanly", () => {
  const codeFirst = item({
    key: "answer_style",
    label: "Code-first answers",
    options: [{ value: "code_first", label: "Enabled" }],
    value: "code_first",
  });
  assert.equal(selectedLabel(codeFirst), "Enabled");
  assert.equal(isSet(codeFirst), true);
});
