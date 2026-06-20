// Pure-logic tests for the operator-console helpers. Node's built-in runner, no deps.
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  canRedrive,
  deadLetterLabel,
  deadLetterTone,
  deliveryStatusTone,
  healthTone,
  incidentEventLabel,
  incidentSyncSummary,
  incidentTone,
  linkStatusTone,
  redriveBlockedReason,
  syncStatusTone,
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

test("incidentTone maps each workflow state to a tone", () => {
  assert.equal(incidentTone("open"), "bad");
  assert.equal(incidentTone("acknowledged"), "warn");
  assert.equal(incidentTone("silenced"), "muted");
  assert.equal(incidentTone("recovered"), "good");
});

test("incidentEventLabel humanizes each trail action; unknown passes through", () => {
  assert.equal(incidentEventLabel("opened"), "Opened");
  assert.equal(incidentEventLabel("acknowledged"), "Acknowledged");
  assert.equal(incidentEventLabel("reassigned"), "Reassigned");
  assert.equal(incidentEventLabel("note_updated"), "Note updated");
  assert.equal(incidentEventLabel("recovered"), "Recovered");
  assert.equal(incidentEventLabel("mystery"), "mystery");
});

test("syncStatusTone maps each sync status to a tone", () => {
  assert.equal(syncStatusTone("synced"), "good");
  assert.equal(syncStatusTone("pending"), "warn");
  assert.equal(syncStatusTone("failed"), "bad");
  assert.equal(syncStatusTone("weird"), "muted");
});

test("incidentSyncSummary states each linkage honestly, drift first", () => {
  const base = { linked: false, synced: false, behind: false, last_synced_at: null, last_failed_at: null, last_error: null, recovered_after_redrive: false, link_status: "never_linked" as const, reason: "never linked", refresh_supported: false, last_checked_at: null, actions: { can_refresh: false, can_redrive: false, can_detach: false, can_relink: false } };
  assert.deepEqual(incidentSyncSummary(base), { label: "Not synced", tone: "muted" });
  assert.equal(incidentSyncSummary({ ...base, synced: true, linked: true, link_status: "linked" }).label, "Externally linked");
  assert.equal(incidentSyncSummary({ ...base, behind: true }).tone, "warn");
  assert.equal(incidentSyncSummary({ ...base, behind: true, last_failed_at: "t", last_error: "HTTP500" }).tone, "bad");
  assert.equal(incidentSyncSummary({ ...base, synced: true, linked: true, recovered_after_redrive: true }).label, "Recovered after redrive");
  // Reconciliation verdicts take priority over plain outbound health.
  assert.equal(incidentSyncSummary({ ...base, linked: true, link_status: "missing_external" }).label, "External incident missing");
  assert.equal(incidentSyncSummary({ ...base, linked: true, link_status: "drifted", reason: "external resolved but incident still open" }).tone, "bad");
  assert.equal(incidentSyncSummary({ ...base, linked: true, link_status: "stale" }).label, "External link stale");
  assert.deepEqual(incidentSyncSummary({ ...base, link_status: "detached" }), { label: "Link detached", tone: "muted" });
});

test("linkStatusTone maps each reconciliation status to a tone", () => {
  assert.equal(linkStatusTone("drifted"), "bad");
  assert.equal(linkStatusTone("missing_external"), "bad");
  assert.equal(linkStatusTone("stale"), "warn");
  assert.equal(linkStatusTone("linked"), "good");
  assert.equal(linkStatusTone("refreshed"), "good");
  assert.equal(linkStatusTone("never_linked"), "muted");
  assert.equal(linkStatusTone("detached"), "muted");
});
