// Pure-logic tests for the operator-console helpers. Node's built-in runner, no deps.
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  actionEffectLabel,
  applyActionLabel,
  canRedrive,
  deadLetterLabel,
  deadLetterTone,
  deliveryStatusTone,
  healthTone,
  incidentEventLabel,
  incidentSyncSummary,
  hiddenInboundFields,
  incidentTone,
  linkStatusTone,
  policyOverrideLabel,
  policySourceLabel,
  readinessLabel,
  readinessTone,
  recommendedActionLabel,
  readinessGuidanceAction,
  attentionRollupRows,
  oldestAttentionLabel,
  formatMetricPct,
  sloTone,
  alertSeverityTone,
  trendWindowLabel,
  formatAgeSeconds,
  readinessDashboardRows,
  sloRows,
  demoSeedSummary,
  redriveBlockedReason,
  supportLevelLabel,
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
  assert.equal(incidentSyncSummary({ ...base, linked: true, link_status: "drifted", reason: "external resolved but incident still open" }).tone, "alert");
  assert.equal(incidentSyncSummary({ ...base, linked: true, link_status: "stale" }).label, "External link stale");
  assert.deepEqual(incidentSyncSummary({ ...base, link_status: "detached" }), { label: "Link detached", tone: "muted" });
});

test("linkStatusTone maps each reconciliation status to a tone", () => {
  assert.equal(linkStatusTone("drifted"), "alert");
  assert.equal(linkStatusTone("missing_external"), "bad");
  assert.equal(linkStatusTone("stale"), "warn");
  assert.equal(linkStatusTone("linked"), "good");
  assert.equal(linkStatusTone("refreshed"), "good");
  assert.equal(linkStatusTone("never_linked"), "muted");
  assert.equal(linkStatusTone("detached"), "muted");
});

test("applyActionLabel is explicit about local-vs-linkage effect", () => {
  assert.match(applyActionLabel("accept_resolved"), /recover locally/);
  assert.match(applyActionLabel("accept_missing"), /Detach/);
  assert.equal(applyActionLabel(null), "");
});

test("supportLevelLabel states adapter insight honestly", () => {
  assert.equal(supportLevelLabel("rich"), "Rich status sync");
  assert.equal(supportLevelLabel("refresh"), "Refresh-capable");
  assert.equal(supportLevelLabel("outbound_only"), "Outbound only");
  assert.equal(supportLevelLabel("none"), "Not linked");
});

test("actionEffectLabel is explicit about each action's blast radius", () => {
  assert.equal(actionEffectLabel("local"), "changes local state");
  assert.equal(actionEffectLabel("external"), "changes external state");
  assert.equal(actionEffectLabel("linkage"), "linkage only");
  assert.equal(actionEffectLabel("none"), "observation only");
});

test("policyOverrideLabel distinguishes default from explicit allow/deny", () => {
  assert.equal(policyOverrideLabel(null), "Default");
  assert.equal(policyOverrideLabel(true), "Allowed");
  assert.equal(policyOverrideLabel(false), "Denied");
});

test("readinessTone + readinessLabel are honest about verification state", () => {
  assert.equal(readinessTone("ready"), "good");
  assert.equal(readinessTone("unverified"), "info");
  assert.equal(readinessTone("degraded"), "warn");
  assert.equal(readinessTone("stale"), "warn");
  assert.equal(readinessTone("auth_failed"), "bad");
  assert.equal(readinessTone("invalid_config"), "bad");
  assert.equal(readinessTone("disabled"), "muted");
  assert.equal(readinessLabel("test_failed"), "Test failed");
  assert.equal(readinessLabel("stale"), "Stale");
  assert.equal(readinessLabel("unverified"), "Unverified");
});

test("policySourceLabel names where a decision came from", () => {
  assert.equal(policySourceLabel("capability"), "Adapter limit");
  assert.equal(policySourceLabel("profile"), "Profile default");
  assert.equal(policySourceLabel("override"), "Target override");
  assert.equal(policySourceLabel("default"), "Default");
});

test("hiddenInboundFields lists only capable-but-policy-hidden fields", () => {
  const link = {
    capabilities: { inbound_fields: { assignee: true, severity: true, updated_at: true, comment_count: false } },
    inbound_visibility: { assignee: false, severity: true, updated_at: true, comment_count: false },
  } as Parameters<typeof hiddenInboundFields>[0];
  // assignee: capable + hidden → listed. severity/updated_at: visible → not listed.
  // comment_count: not capable → not listed (nothing to hide).
  assert.deepEqual(hiddenInboundFields(link), ["assignee"]);
});

// ── Phase 4: operator-runbook metadata + triage rollups ───────────────────────

test("recommendedActionLabel gives a short imperative per action; null passes through", () => {
  assert.equal(recommendedActionLabel("rotate_secret"), "Rotate secret");
  assert.equal(recommendedActionLabel("validate"), "Validate");
  assert.equal(recommendedActionLabel("apply_resolved"), "Apply resolution");
  assert.equal(recommendedActionLabel(null), null);
  assert.equal(recommendedActionLabel(undefined), null);
});

test("readinessGuidanceAction mirrors the backend table deterministically", () => {
  assert.equal(readinessGuidanceAction("ready"), null);
  assert.equal(readinessGuidanceAction("unverified"), "validate");
  assert.equal(readinessGuidanceAction("stale"), "validate");
  assert.equal(readinessGuidanceAction("auth_failed"), "rotate_secret");
  assert.equal(readinessGuidanceAction("invalid_config"), "fix_config");
  assert.equal(readinessGuidanceAction("test_failed"), "test");
  assert.equal(readinessGuidanceAction("disabled"), "enable");
});

test("attentionRollupRows orders hard failures first, with count/label/tone/action", () => {
  const rows = attentionRollupRows({
    by_state: { unverified: 2, auth_failed: 1, stale: 3 },
  });
  // Severity order: auth_failed (bad) before stale/unverified (warn).
  assert.deepEqual(rows.map((r) => r.state), ["auth_failed", "stale", "unverified"]);
  const auth = rows[0];
  assert.equal(auth.count, 1);
  assert.equal(auth.label, "Auth failed");
  assert.equal(auth.tone, "bad");
  assert.equal(auth.action, "Rotate secret");
  // Zero-count states never appear.
  assert.equal(rows.find((r) => r.state === "degraded"), undefined);
});

test("attentionRollupRows is empty when nothing needs attention", () => {
  assert.deepEqual(attentionRollupRows({ by_state: {} }), []);
});

test("oldestAttentionLabel summarizes the longest-waiting item, or null", () => {
  assert.equal(
    oldestAttentionLabel({ oldest: { id: "t1", name: "pagerduty-prod", state: "auth_failed", recommended_action: "rotate_secret", since: "2026-06-01T00:00:00Z" } }),
    "pagerduty-prod — Auth failed",
  );
  assert.equal(oldestAttentionLabel({ oldest: null }), null);
});

// ── Phase 5: observability formatting + dashboard helpers ─────────────────────

test("formatMetricPct is honest about no-data (em dash, not 0%)", () => {
  assert.equal(formatMetricPct(null), "—");
  assert.equal(formatMetricPct(undefined), "—");
  assert.equal(formatMetricPct(0), "0%");
  assert.equal(formatMetricPct(99.5), "99.5%");
});

test("sloTone uses fixed deterministic bands; null is muted not alarming", () => {
  assert.equal(sloTone(null), "muted");
  assert.equal(sloTone(99), "good");
  assert.equal(sloTone(100), "good");
  assert.equal(sloTone(95), "warn");
  assert.equal(sloTone(90), "warn");
  assert.equal(sloTone(89.9), "bad");
  assert.equal(sloTone(0), "bad");
});

test("alertSeverityTone maps severity to tone (observation only)", () => {
  assert.equal(alertSeverityTone("critical"), "bad");
  assert.equal(alertSeverityTone("warning"), "warn");
});

test("trendWindowLabel humanizes each bounded window", () => {
  assert.equal(trendWindowLabel("24h"), "Last 24h");
  assert.equal(trendWindowLabel("7d"), "Last 7d");
  assert.equal(trendWindowLabel("30d"), "Last 30d");
});

test("formatAgeSeconds gives compact bounded units", () => {
  assert.equal(formatAgeSeconds(null), "—");
  assert.equal(formatAgeSeconds(-5), "—");
  assert.equal(formatAgeSeconds(30), "just now");
  assert.equal(formatAgeSeconds(300), "5m");
  assert.equal(formatAgeSeconds(7200), "2h");
  assert.equal(formatAgeSeconds(172800), "2d");
});

test("readinessDashboardRows renders every bucket with a deterministic tone", () => {
  const rows = readinessDashboardRows({ ready: 3, attention: 2, stale: 1, auth_failed: 1, disabled: 4 });
  assert.deepEqual(rows.map((r) => r.key), ["ready", "attention", "stale", "auth_failed", "disabled"]);
  assert.equal(rows[0].tone, "good");        // ready
  assert.equal(rows[3].tone, "bad");         // auth_failed > 0 → bad
  // Zero-count attention/stale relax to muted (no false alarm).
  const calm = readinessDashboardRows({ ready: 5, attention: 0, stale: 0, auth_failed: 0, disabled: 0 });
  assert.equal(calm[1].tone, "muted");
  assert.equal(calm[3].tone, "muted");
});

test("sloRows pairs each indicator with formatted value + tone, stable order", () => {
  const rows = sloRows({
    target_readiness_pct: 100, validation_pass_pct_24h: 92,
    reconciliation_success_pct_24h: null, sync_success_pct_24h: 80,
  });
  assert.deepEqual(rows.map((r) => r.label), [
    "Target readiness", "Validation pass (24h)", "Reconciliation (24h)", "Sync success (24h)",
  ]);
  assert.equal(rows[0].value, "100%");
  assert.equal(rows[0].tone, "good");
  assert.equal(rows[1].tone, "warn");
  assert.equal(rows[2].value, "—");          // null → no data
  assert.equal(rows[2].tone, "muted");
  assert.equal(rows[3].tone, "bad");
});

test("demoSeedSummary summarizes manifest counts deterministically", () => {
  const summary = demoSeedSummary({
    counts: { targets: 6, incidents: 5, links: 5, check_events: 11, reconciliation_events: 8, sync_records: 6 },
  });
  assert.equal(summary, "Seeded 6 targets, 5 incidents, 5 links, 25 events.");
});
