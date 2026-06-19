// Pure-logic tests for the operator-console helpers. Node's built-in runner, no deps.
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  canRedrive,
  deadLetterLabel,
  deadLetterTone,
  deliveryStatusTone,
  healthTone,
  redriveBlockedReason,
} from "./operator.ts";

test("healthTone maps each health label to a calm tone", () => {
  assert.equal(healthTone("healthy"), "good");
  assert.equal(healthTone("degraded"), "warn");
  assert.equal(healthTone("failing"), "bad");
  assert.equal(healthTone("cooling_down"), "warn");
  assert.equal(healthTone("disabled"), "muted");
});

test("dead-letter label + tone are honest per state", () => {
  assert.equal(deadLetterLabel("redrive_candidate"), "Needs redrive");
  assert.equal(deadLetterTone("redrive_candidate"), "bad");
  assert.equal(deadLetterLabel("resolved"), "Resolved");
  assert.equal(deadLetterTone("resolved"), "good");
  assert.equal(deadLetterLabel("redriven"), "Redrive in flight");
  assert.equal(deadLetterLabel("exhausted"), "Exhausted");
});

test("only a candidate is redrivable; others explain why not", () => {
  assert.equal(canRedrive({ dead_letter_state: "redrive_candidate" }), true);
  assert.equal(canRedrive({ dead_letter_state: "redriven" }), false);
  assert.equal(canRedrive({ dead_letter_state: "resolved" }), false);
  assert.equal(canRedrive({ dead_letter_state: "exhausted" }), false);

  assert.equal(redriveBlockedReason("redrive_candidate"), null);
  assert.match(redriveBlockedReason("redriven") ?? "", /in flight/);
  assert.match(redriveBlockedReason("resolved") ?? "", /already succeeded/);
  assert.match(redriveBlockedReason("exhausted") ?? "", /limit reached/);
});

test("deliveryStatusTone maps a delivery status to a tone", () => {
  assert.equal(deliveryStatusTone("delivered"), "good");
  assert.equal(deliveryStatusTone("pending"), "warn");
  assert.equal(deliveryStatusTone("failed"), "bad");
  assert.equal(deliveryStatusTone("weird"), "muted");
});
