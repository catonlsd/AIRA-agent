// Presenter tests for the artifact card view model. Node's built-in runner with
// native TypeScript stripping — no deps. `npm test`.
import { test } from "node:test";
import assert from "node:assert/strict";

import { presentArtifact } from "./execution-presenter.ts";

const meta = (artifact: Record<string, unknown>) => ({ artifact });

// ── Richer metadata renders cleanly ──────────────────────────────────────────

test("presentArtifact surfaces the human theme name", () => {
  const view = presentArtifact(
    meta({ type: "pptx", title: "Solar", theme: "Professional Clean", validation: { valid: true } })
  );
  assert.equal(view?.theme, "Professional Clean");
  assert.equal(view?.type, "PPTX");
  assert.equal(view?.validated, true);
});

test("imageNote appears only when images were actually inserted", () => {
  const none = presentArtifact(meta({ type: "pptx", title: "X", image_count: 0 }));
  assert.equal(none?.imageNote, null); // never a fake "rich visuals" badge

  const two = presentArtifact(meta({ type: "pptx", title: "X", image_count: 2 }));
  assert.equal(two?.imageNote, "2 images");

  const one = presentArtifact(meta({ type: "pptx", title: "X", image_count: 1 }));
  assert.equal(one?.imageNote, "1 image"); // singular
});

test("theme is null when the backend didn't provide one (no clutter)", () => {
  const view = presentArtifact(meta({ type: "docx", title: "Report" }));
  assert.equal(view?.theme, null);
  assert.equal(view?.imageNote, null);
});

test("no raw validation internals leak into the view model", () => {
  const view = presentArtifact(
    meta({ type: "xlsx", title: "Sales", validation: { valid: true, details: { rows: 9 } }, summary: "9 rows × 2 columns" })
  );
  // The view exposes a clean summary, not raw detail objects.
  assert.equal(view?.summary, "9 rows × 2 columns");
  assert.ok(!("details" in (view ?? {})));
  assert.ok(!("validation" in (view ?? {})));
});

test("returns null for a non-artifact turn", () => {
  assert.equal(presentArtifact({}), null);
  assert.equal(presentArtifact(undefined), null);
});
