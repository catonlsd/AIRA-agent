import { type Page, type Route, expect } from "@playwright/test";

/**
 * Deterministic API stubbing for the E2E suite.
 *
 * Every test seeds the backend at the network layer. Routes are registered LIFO in
 * Playwright (last wins), so a broad fallback is installed FIRST and specific routes
 * after — keeping each test free of "unhandled fetch → connection refused" noise while
 * still asserting against precise seeded responses.
 */

export const API = "http://localhost:8000";

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

/** Install a permissive fallback so any un-stubbed API call returns an empty 200. */
export async function seedFallback(page: Page) {
  await page.route(`${API}/**`, (route) => json(route, {}));
}

// ── seeded incident-sync target (operator readiness flow) ────────────────────

export function seedTarget(over: Partial<Record<string, unknown>> = {}) {
  return {
    id: "tgt-1", name: "PagerDuty (prod)", kind: "pagerduty",
    profile: "pagerduty", profile_label: "PagerDuty", url: "https://hooks.example.com/pd",
    enabled: true, sync_actions: null, has_secret: true, consecutive_failures: 0,
    capabilities: {
      refresh: true, push_outward: true, relink_validation: true, status_sync: true,
      apply_resolved: true, apply_missing: true, external_resolve: true, external_reopen: true,
      external_acknowledge: true,
      inbound_fields: { assignee: true, severity: true, updated_at: true, comment_count: true },
      support_level: "rich",
    },
    policy_overrides: {},
    readiness: { state: "unverified", source: "none", reason: "not yet validated or tested" },
    readiness_facts: {
      last_validated_at: null, last_test_at: null, last_success_at: null,
      last_failure_at: null, last_check_error: null, last_check_kind: null,
    },
    created_at: "2026-06-20T00:00:00Z",
    ...over,
  };
}

function readyReadiness() {
  return { state: "ready", source: "connectivity", reason: "last check succeeded" };
}

// ── seeded incident (operator incident-sync flow) ────────────────────────────

export function seedIncident(over: Partial<Record<string, unknown>> = {}) {
  return {
    id: "inc-1", signal: "stuck:job-7", classification: "stuck", subject: "job-7",
    source: "alert", state: "open", severity: "critical", occurrences: 3, note: null,
    assignee: null, assigned_at: null, acknowledged: false, acknowledged_at: null,
    silenced_until: null, recovered_at: null,
    first_seen: "2026-06-20T00:00:00Z", last_seen: "2026-06-20T01:00:00Z",
    ...over,
  };
}

function seedSyncStatus(incidentId: string, checkedAt: string | null = null) {
  return {
    linked: true,
    links: [{
      target_id: "tgt-1", target_name: "PagerDuty (prod)", target_kind: "pagerduty",
      profile: "pagerduty", external_ref: "PD-123", external_url: "https://pd.example.com/i/PD-123",
      last_action: "opened", last_synced_at: "2026-06-20T01:00:00Z", last_checked_at: checkedAt,
      external_status: null, external_exists: null, external_assignee: null, external_severity: null,
      external_updated_at: null, external_comment_count: null,
      inbound_visibility: { assignee: true, severity: true, updated_at: true, comment_count: true },
      suggestions_allowed: true, detached: false, detached_at: null,
      capabilities: seedTarget().capabilities, policy_overrides: {},
      refresh_supported: true, link_status: "linked", reason: "linked",
    }],
    records: [{
      id: "rec-1", target_id: "tgt-1", target_name: "PagerDuty (prod)", target_kind: "pagerduty",
      incident_id: incidentId, signal: "stuck:job-7", action: "opened", actor: null, state: "open",
      severity: "critical", classification: "stuck", subject: "job-7", assignee: null, note: null,
      status: "synced", attempts: 1, last_error: null, external_ref: "PD-123",
      external_url: "https://pd.example.com/i/PD-123", redrive_of: null, is_redrive: false,
      created_at: "2026-06-20T01:00:00Z",
    }],
    reconciliation: [],
    summary: {
      linked: true, synced: true, behind: false, last_synced_at: "2026-06-20T01:00:00Z",
      last_failed_at: null, last_error: null, recovered_after_redrive: false,
      link_status: "linked", reason: "linked", refresh_supported: true,
      last_checked_at: null,
      actions: { can_refresh: true, can_redrive: false, can_detach: true, can_relink: true,
                 can_apply: false, apply_action: null, can_push: true },
      available_actions: [], support_level: "rich", suggestions: [],
    },
  };
}

/**
 * Stub every operator endpoint the console touches, so /operator works end-to-end
 * with zero backend. `targets` and `incidents` let a test seed specific states.
 */
export async function mockOperator(page: Page, opts: {
  targets?: unknown[]; incidents?: unknown[];
  validatedReadiness?: Record<string, unknown>;
} = {}) {
  const targets = opts.targets ?? [seedTarget()];
  const incidents = opts.incidents ?? [seedIncident()];

  await page.route(`${API}/operator/overview`, (r) => json(r, { ok: true }));
  await page.route(`${API}/operator/delivery/analytics**`, (r) => json(r, {
    window_minutes: 60, totals: { attempted: 0, delivered: 0, failed: 0, pending: 0, redriven: 0 },
    routing: { routed: 0, suppressed: 0, skipped: 0, escalation_destinations: 0 }, by_kind: {}, by_destination: [],
  }));
  await page.route(`${API}/operator/delivery/health`, (r) => json(r, []));
  await page.route(`${API}/operator/deliveries/dead-letters**`, (r) => json(r, { dead_letters: [] }));
  await page.route(`${API}/operator/incidents`, (r) => json(r, { incidents }));
  await page.route(`${API}/operator/incident-targets`, (r) => json(r, { targets }));
  await page.route(`${API}/operator/incident-sync**`, (r) => json(r, { records: [] }));

  // Per-incident sync status + refresh.
  await page.route(`${API}/operator/incidents/*/sync`, (r) => json(r, seedSyncStatus("inc-1")));
  await page.route(`${API}/operator/incidents/*/sync/refresh`, (r) =>
    json(r, seedSyncStatus("inc-1", "2026-06-20T02:00:00Z")));
  await page.route(`${API}/operator/incidents/*/history`, (r) => json(r, { history: [] }));

  // Validate / test-send flip readiness to ready.
  await page.route(`${API}/operator/incident-targets/*/validate`, (r) => json(r, {
    ok: true,
    checks: [
      { name: "config", status: "pass", detail: "configuration is valid" },
      { name: "profile", status: "pass", detail: "profile matches kind" },
      { name: "policy", status: "pass", detail: "policy overrides are within capability" },
      { name: "secret", status: "pass", detail: "requests are HMAC-signed" },
      { name: "connectivity", status: "pass", detail: "endpoint reachable" },
    ],
    readiness: opts.validatedReadiness ?? readyReadiness(),
    readiness_facts: { last_validated_at: "2026-06-20T03:00:00Z", last_test_at: null,
      last_success_at: "2026-06-20T03:00:00Z", last_failure_at: null,
      last_check_error: null, last_check_kind: "connectivity" },
  }));
  await page.route(`${API}/operator/incident-targets/*/test`, (r) => json(r, {
    ok: true, status_code: 202, error: null, message: "Synthetic test event sent.",
    readiness: readyReadiness(),
    readiness_facts: { last_validated_at: "2026-06-20T03:00:00Z", last_test_at: "2026-06-20T03:05:00Z",
      last_success_at: "2026-06-20T03:05:00Z", last_failure_at: null, last_check_error: null, last_check_kind: "test" },
  }));
  await page.route(`${API}/operator/incident-targets/attention`, (r) => json(r, { targets: [] }));
}

/** Connect the operator console with a seeded key (overview must already be stubbed). */
export async function connectOperator(page: Page) {
  await page.goto("/operator");
  await page.getByPlaceholder("Service key").fill("seed-operator-key");
  await page.getByRole("button", { name: "Connect" }).click();
  // Console header appears once verifyOperator() succeeds.
  await expect(page.getByRole("heading", { name: "Delivery console" })).toBeVisible();
}

// ── streaming chat stub ──────────────────────────────────────────────────────

/** Build an SSE body the frontend's parser (event:/data:, blank-line separated) reads. */
function sseBody(tokens: string[], final: Record<string, unknown>) {
  const blocks = tokens.map((t) => `event: token\ndata: ${JSON.stringify({ text: t })}\n\n`);
  blocks.push(`event: final\ndata: ${JSON.stringify(final)}\n\n`);
  return blocks.join("");
}

/** Stub POST /aira-x/stream with a deterministic token stream + final response. */
export async function mockStream(page: Page, opts: { tokens: string[]; final: Record<string, unknown> }) {
  await page.route(`${API}/aira-x/stream`, (route) =>
    route.fulfill({ status: 200, contentType: "text/event-stream", body: sseBody(opts.tokens, opts.final) }));
}

/** A minimal completed direct-answer final (the answer card reads `citations`). */
export function answerFinal(answer: string, metadata: Record<string, unknown> = {}, over: Record<string, unknown> = {}) {
  return { run_id: "run-1", status: "completed", mode: "direct_answer", answer, citations: [],
           metadata: { turn_status: "completed", ...metadata }, ...over };
}

/** A completed turn that produced a downloadable artifact (renders the artifact card). */
export function artifactFinal(answer: string) {
  const artifact = {
    type: "pptx", title: "Quarterly Review Deck", filename: "quarterly-review.pptx",
    download_url: "/artifacts/quarterly-review.pptx", summary: "6 slides",
    size_bytes: 524288, validation: { valid: true }, location: "local", theme: "midnight",
  };
  // `metadata.artifact` drives the answer-card ArtifactCard; `meta.artifact` keeps the
  // turn router in the answer card (not the workflow card).
  return answerFinal(answer, { artifact }, { meta: { artifact } });
}

/** A plan-ready turn awaiting the operator's go-ahead (renders the approval buttons).
 * The chat rebuilds `turn.response.metadata` from `final.meta`, so the plan data lives
 * in `meta` (not `metadata`). */
export function planFinal(answer: string) {
  return answerFinal(answer, {}, {
    status: "plan_ready",
    meta: { approval_required: true, plan_steps: ["Generate the deck", "Validate the output"] },
  });
}
