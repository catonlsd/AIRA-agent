// Operator delivery-console client — OPERATOR-ONLY, never used by the normal
// product. Every call is gated by the service api-key (X-API-Key), entered by an
// operator and kept in sessionStorage (a secret, cleared when the tab closes —
// never localStorage, never mixed with the user's account token). Talks only to
// the existing, already-gated /operator/* APIs; returns their curated payloads
// (no secrets, no raw internals). Dependency-free so the pure helpers unit-test.

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY_STORAGE = "aira_operator_key";

// ── types (mirror the curated operator API payloads) ────────────────────────

export type DeliveryAnalytics = {
  window_minutes: number;
  totals: { attempted: number; delivered: number; failed: number; pending: number; redriven: number };
  routing: { routed: number; suppressed: number; skipped: number; escalation_destinations: number };
  by_kind: Record<string, { delivered: number; failed: number; pending: number }>;
  by_destination: { destination_id: string; name: string | null; kind: string; delivered: number; failed: number; pending: number }[];
};

export type DestinationHealth = {
  destination_id: string;
  name: string | null;
  kind: string;
  enabled: boolean;
  is_escalation: boolean;
  delivered: number;
  failed_terminal: number;
  pending: number;
  redrive_resolved: number;
  routed: number;
  suppressed: number;
  skipped: number;
  consecutive_failures: number;
  cooling_down: boolean;
  cooldown_until: string | null;
  escalation_eligible: boolean;
  last_error: string | null;
  health: "healthy" | "degraded" | "failing" | "cooling_down" | "disabled";
  reason: string;
};

export type DeadLetter = {
  id: string;
  destination_id: string;
  source_type: string;
  source_id: string | null;
  event_type: string | null;
  severity: string | null;
  status: string;
  attempts: number;
  last_error: string | null;
  redrive_of: string | null;
  dead_letter_state: "redrive_candidate" | "redriven" | "resolved" | "exhausted";
  redrive_count: number;
  redrive_ids: string[];
  created_at: string | null;
};

export type RoutingDecision = {
  classification: string | null;
  severity: string | null;
  job_id: string | null;
  occurrences: number;
  decision: "route" | "suppress" | "skip";
  reason: string;
};

export type RoutingPreview = {
  destination: Record<string, unknown>;
  effective_window_seconds: number;
  decisions: RoutingDecision[];
};

export type DestinationPolicy = {
  destination_id: string;
  kind: string;
  payload_shape: string;
  backoff: string;
  max_attempts: number;
  max_attempts_source: "destination" | "adapter" | "global";
  cooldown_threshold: number;
  cooldown_seconds: number;
  consecutive_failures: number;
  cooling_down: boolean;
  cooldown_until: string | null;
};

export type Delivery = {
  id: string;
  destination_id: string;
  destination_name?: string | null;
  source_type: string;
  source_id: string | null;
  event_type: string | null;
  severity: string | null;
  status: string;
  attempts: number;
  response_code: number | null;
  last_error: string | null;
  redrive_of: string | null;
  is_redrive: boolean;
  created_at: string | null;
  updated_at: string | null;
};

export type DeliveryLineage = {
  root_id: string;
  destination_id: string;
  destination_name: string | null;
  destination_kind: string | null;
  source_type: string;
  source_id: string | null;
  event_type: string | null;
  state: string;
  attempts: Delivery[];
};

/** Tunable destination policy fields an operator may edit (never the secret). */
export type DestinationTuning = {
  enabled?: boolean;
  min_severity?: string;
  event_filter?: string;
  alert_filter?: string;
  origin_filter?: string;
  suppress_seconds?: number;
  escalate_after?: number;
  max_attempts?: number;
};

export type IncidentState = "open" | "acknowledged" | "silenced" | "recovered";

export type Incident = {
  id: string;
  signal: string;
  classification: string | null;
  subject: string | null;
  source: string;
  state: IncidentState;
  severity: string | null;
  occurrences: number;
  note: string | null;
  assignee: string | null;
  assigned_at: string | null;
  acknowledged: boolean;
  acknowledged_at: string | null;
  silenced_until: string | null;
  recovered_at: string | null;
  first_seen: string | null;
  last_seen: string | null;
};

export type IncidentEvent = {
  action: string;
  actor: string | null;
  detail: string | null;
  state: string | null;
  at: string | null;
};

export type SyncStatus = "pending" | "synced" | "failed";

export type IncidentTarget = {
  id: string;
  name: string;
  kind: string;
  url: string;
  enabled: boolean;
  sync_actions: string | null;
  has_secret: boolean;
  consecutive_failures: number;
  created_at: string | null;
};

export type IncidentSyncRecord = {
  id: string;
  target_id: string;
  target_name: string | null;
  target_kind: string | null;
  incident_id: string;
  signal: string | null;
  action: string;
  actor: string | null;
  state: string | null;
  severity: string | null;
  classification: string | null;
  subject: string | null;
  assignee: string | null;
  note: string | null;
  status: SyncStatus;
  attempts: number;
  last_error: string | null;
  external_ref: string | null;
  external_url: string | null;
  redrive_of: string | null;
  is_redrive: boolean;
  created_at: string | null;
};

export type LinkStatus = "linked" | "never_linked" | "stale" | "missing_external" | "drifted" | "refreshed" | "detached";

export type SupportLevel = "rich" | "refresh" | "outbound_only" | "none";

export type AdapterCapabilities = {
  refresh: boolean; push_outward: boolean; relink_validation: boolean;
  status_sync: boolean; support_level: SupportLevel;
};

export type ExternalStateSuggestion = { code: string; tone: Tone; text: string };

export type IncidentExternalLink = {
  target_id: string;
  target_name: string | null;
  target_kind: string | null;
  external_ref: string | null;
  external_url: string | null;
  last_action: string | null;
  last_synced_at: string | null;
  last_checked_at: string | null;
  external_status: string | null;
  external_exists: boolean | null;
  external_assignee: string | null;
  external_severity: string | null;
  external_updated_at: string | null;
  external_comment_count: number | null;
  detached: boolean;
  detached_at: string | null;
  capabilities: AdapterCapabilities;
  refresh_supported: boolean;
  link_status: LinkStatus;
  reason: string;
  incident_id?: string;
};

export type ReconciliationEvent = {
  action: string;
  outcome: string;
  actor: string | null;
  detail: string | null;
  at: string | null;
};

export type IncidentSyncStatus = {
  linked: boolean;
  links: IncidentExternalLink[];
  records: IncidentSyncRecord[];
  reconciliation: ReconciliationEvent[];
  summary: {
    linked: boolean;
    synced: boolean;
    behind: boolean;
    last_synced_at: string | null;
    last_failed_at: string | null;
    last_error: string | null;
    recovered_after_redrive: boolean;
    link_status: LinkStatus;
    reason: string;
    refresh_supported: boolean;
    last_checked_at: string | null;
    actions: {
      can_refresh: boolean; can_redrive: boolean; can_detach: boolean; can_relink: boolean;
      can_apply: boolean; apply_action: "accept_resolved" | "accept_missing" | null; can_push: boolean;
    };
    support_level: SupportLevel;
    suggestions: ExternalStateSuggestion[];
  };
};

/** Tone for an external-sync record status (pure; unit-tested). */
export function syncStatusTone(status: string): Tone {
  if (status === "synced") return "good";
  if (status === "pending") return "warn";
  if (status === "failed") return "bad";
  return "muted";
}

/** Human label for an apply-from-external action (pure; unit-tested). Honest about
 * whether it changes local state vs only linkage. */
export function applyActionLabel(action: "accept_resolved" | "accept_missing" | null): string {
  if (action === "accept_resolved") return "Apply external resolution (recover locally)";
  if (action === "accept_missing") return "Detach (external missing)";
  return "";
}

/** Human label for an adapter support level (pure; unit-tested). Honest about how
 * much external insight a target's adapter actually provides. */
export function supportLevelLabel(level: SupportLevel): string {
  if (level === "rich") return "Rich status sync";
  if (level === "refresh") return "Refresh-capable";
  if (level === "outbound_only") return "Outbound only";
  return "Not linked";
}

/** Tone for a reconciliation link status (pure; unit-tested). */
export function linkStatusTone(status: LinkStatus): Tone {
  if (status === "missing_external" || status === "drifted") return "bad";
  if (status === "stale") return "warn";
  if (status === "linked" || status === "refreshed") return "good";
  return "muted"; // never_linked / detached
}

/** Honest one-line linkage summary for an incident's external sync (pure;
 * unit-tested). Reconciliation drift/staleness wins over plain outbound health;
 * outbound stays primary and AIRA-X never claims it owns external truth. */
export function incidentSyncSummary(s: IncidentSyncStatus["summary"]): { label: string; tone: Tone } {
  if (s.link_status === "detached") return { label: "Link detached", tone: "muted" };
  // Reconciliation verdicts (require a real link / refresh) come first.
  if (s.link_status === "missing_external") return { label: "External incident missing", tone: "bad" };
  if (s.link_status === "drifted") return { label: s.reason || "Drifted from external", tone: "bad" };
  if (s.link_status === "stale") return { label: "External link stale", tone: "warn" };
  if (s.last_error && s.behind) return { label: `Last sync failed: ${s.last_error}`, tone: "bad" };
  if (s.recovered_after_redrive) return { label: "Recovered after redrive", tone: "good" };
  if (s.behind) return { label: "Sync behind current state", tone: "warn" };
  if (s.link_status === "refreshed") return { label: "Checked · aligned", tone: "good" };
  if (s.linked) return { label: "Externally linked", tone: "good" };
  if (s.synced) return { label: "Synced", tone: "good" };
  return { label: "Not synced", tone: "muted" };
}

/** Human-friendly label for an action-trail entry (pure; unit-tested). */
export function incidentEventLabel(action: string): string {
  const labels: Record<string, string> = {
    opened: "Opened",
    acknowledged: "Acknowledged",
    silenced: "Silenced",
    unsilenced: "Unsilenced",
    recovered: "Recovered",
    reopened: "Reopened",
    assigned: "Assigned",
    reassigned: "Reassigned",
    unassigned: "Unassigned",
    note_updated: "Note updated",
  };
  return labels[action] ?? action;
}

export type Tone = "good" | "warn" | "bad" | "muted";

// ── pure helpers (unit-tested) ───────────────────────────────────────────────

const _HEALTH_TONE: Record<DestinationHealth["health"], Tone> = {
  healthy: "good",
  degraded: "warn",
  failing: "bad",
  cooling_down: "warn",
  disabled: "muted",
};

export function healthTone(health: DestinationHealth["health"]): Tone {
  return _HEALTH_TONE[health] ?? "muted";
}

const _DL: Record<DeadLetter["dead_letter_state"], { label: string; tone: Tone }> = {
  redrive_candidate: { label: "Needs redrive", tone: "bad" },
  redriven: { label: "Redrive in flight", tone: "warn" },
  resolved: { label: "Resolved", tone: "good" },
  exhausted: { label: "Exhausted", tone: "bad" },
};

export function deadLetterLabel(state: DeadLetter["dead_letter_state"]): string {
  return _DL[state]?.label ?? state;
}

export function deadLetterTone(state: DeadLetter["dead_letter_state"]): Tone {
  return _DL[state]?.tone ?? "muted";
}

/** Only a candidate can be redriven; everything else explains why not. */
export function canRedrive(dl: Pick<DeadLetter, "dead_letter_state">): boolean {
  return dl.dead_letter_state === "redrive_candidate";
}

export function redriveBlockedReason(state: DeadLetter["dead_letter_state"]): string | null {
  if (state === "redrive_candidate") return null;
  if (state === "redriven") return "A redrive is already in flight.";
  if (state === "resolved") return "A redrive already succeeded.";
  return "Redrive limit reached — investigate the destination.";
}

const _STATUS_TONE: Record<string, Tone> = {
  delivered: "good",
  pending: "warn",
  failed: "bad",
};

/** Tone for a delivery status in the history table. */
export function deliveryStatusTone(status: string): Tone {
  return _STATUS_TONE[status] ?? "muted";
}

const _INCIDENT_TONE: Record<IncidentState, Tone> = {
  open: "bad",
  acknowledged: "warn",
  silenced: "muted",
  recovered: "good",
};

/** Tone for an incident's workflow state. */
export function incidentTone(state: IncidentState): Tone {
  return _INCIDENT_TONE[state] ?? "muted";
}

export function hasOperatorKey(): boolean {
  return Boolean(getOperatorKey());
}

// ── operator-key management (sessionStorage; never localStorage) ─────────────

export function getOperatorKey(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(KEY_STORAGE);
  } catch {
    return null;
  }
}

export function setOperatorKey(key: string): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(KEY_STORAGE, key.trim());
  } catch {
    /* best-effort */
  }
}

export function clearOperatorKey(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(KEY_STORAGE);
    window.sessionStorage.removeItem(NAME_STORAGE);
  } catch {
    /* best-effort */
  }
}

// ── operator handle (self-declared; recorded as the actor on incident actions) ─

const NAME_STORAGE = "aira_operator_name";

export function getOperatorName(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(NAME_STORAGE);
  } catch {
    return null;
  }
}

export function setOperatorName(name: string): void {
  if (typeof window === "undefined") return;
  try {
    const trimmed = name.trim().slice(0, 80);
    if (trimmed) window.sessionStorage.setItem(NAME_STORAGE, trimmed);
    else window.sessionStorage.removeItem(NAME_STORAGE);
  } catch {
    /* best-effort */
  }
}

// ── API client (every request carries the operator key) ──────────────────────

function opHeaders(json = false): Record<string, string> {
  const headers: Record<string, string> = json ? { "Content-Type": "application/json" } : {};
  const key = getOperatorKey();
  if (key) headers["X-API-Key"] = key;
  const name = getOperatorName();
  if (name) headers["X-Operator-Name"] = name;
  return headers;
}

/** Validate the entered key by hitting a gated, side-effect-free endpoint. */
export async function verifyOperator(): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/operator/overview`, { cache: "no-store", headers: opHeaders() });
    return res.ok;
  } catch {
    return false;
  }
}

export async function fetchAnalytics(sinceMinutes = 60): Promise<DeliveryAnalytics | null> {
  const res = await fetch(`${API_URL}/operator/delivery/analytics?since_minutes=${sinceMinutes}`, {
    cache: "no-store", headers: opHeaders(),
  });
  if (!res.ok) return null;
  return res.json();
}

export async function fetchDestinationHealth(): Promise<DestinationHealth[]> {
  const res = await fetch(`${API_URL}/operator/delivery/health`, { cache: "no-store", headers: opHeaders() });
  if (!res.ok) return [];
  const body = await res.json();
  return Array.isArray(body?.destinations) ? body.destinations : [];
}

export async function fetchDeadLetters(): Promise<DeadLetter[]> {
  const res = await fetch(`${API_URL}/operator/deliveries/dead-letters`, { cache: "no-store", headers: opHeaders() });
  if (!res.ok) return [];
  const body = await res.json();
  return Array.isArray(body?.dead_letters) ? body.dead_letters : [];
}

export async function fetchRoutingPreview(destId: string): Promise<RoutingPreview | null> {
  const res = await fetch(`${API_URL}/operator/destinations/${encodeURIComponent(destId)}/routing`, {
    cache: "no-store", headers: opHeaders(),
  });
  if (!res.ok) return null;
  return res.json();
}

export async function fetchDestinationPolicy(destId: string): Promise<DestinationPolicy | null> {
  const res = await fetch(`${API_URL}/operator/destinations/${encodeURIComponent(destId)}/policy`, {
    cache: "no-store", headers: opHeaders(),
  });
  if (!res.ok) return null;
  const body = await res.json();
  return (body?.policy as DestinationPolicy) ?? null;
}

export async function redriveDelivery(deliveryId: string): Promise<{ ok: boolean; message?: string }> {
  const res = await fetch(`${API_URL}/operator/deliveries/${encodeURIComponent(deliveryId)}/redrive`, {
    method: "POST", cache: "no-store", headers: opHeaders(),
  });
  if (res.ok) return { ok: true };
  const body = await res.json().catch(() => ({}));
  return { ok: false, message: body?.detail };
}

export async function clearCooldown(destId: string): Promise<boolean> {
  const res = await fetch(`${API_URL}/operator/destinations/${encodeURIComponent(destId)}/cooldown/clear`, {
    method: "POST", cache: "no-store", headers: opHeaders(),
  });
  return res.ok;
}

export async function runSweep(): Promise<Record<string, number> | null> {
  const res = await fetch(`${API_URL}/operator/deliveries/sweep`, {
    method: "POST", cache: "no-store", headers: opHeaders(true),
  });
  if (!res.ok) return null;
  return res.json();
}

export async function fetchDeliveries(opts: { status?: string; destinationId?: string; redrives?: boolean; limit?: number } = {}): Promise<Delivery[]> {
  const params = new URLSearchParams();
  if (opts.status) params.set("status", opts.status);
  if (opts.destinationId) params.set("destination_id", opts.destinationId);
  if (opts.redrives !== undefined) params.set("redrives", String(opts.redrives));
  params.set("limit", String(opts.limit ?? 50));
  const res = await fetch(`${API_URL}/operator/deliveries?${params.toString()}`, { cache: "no-store", headers: opHeaders() });
  if (!res.ok) return [];
  const body = await res.json();
  return Array.isArray(body?.deliveries) ? body.deliveries : [];
}

export async function fetchLineage(deliveryId: string): Promise<DeliveryLineage | null> {
  const res = await fetch(`${API_URL}/operator/deliveries/${encodeURIComponent(deliveryId)}/lineage`, {
    cache: "no-store", headers: opHeaders(),
  });
  if (!res.ok) return null;
  const body = await res.json();
  return (body?.lineage as DeliveryLineage) ?? null;
}

/** Tune a destination's policy (never the secret). Returns the updated record. */
export async function patchDestination(destId: string, fields: DestinationTuning): Promise<{ ok: boolean; message?: string }> {
  const res = await fetch(`${API_URL}/operator/destinations/${encodeURIComponent(destId)}`, {
    method: "PATCH", cache: "no-store", headers: opHeaders(true), body: JSON.stringify(fields),
  });
  if (res.ok) return { ok: true };
  const body = await res.json().catch(() => ({}));
  return { ok: false, message: body?.detail };
}

// ── incident workflow ────────────────────────────────────────────────────────

export async function fetchIncidents(): Promise<Incident[]> {
  const res = await fetch(`${API_URL}/operator/incidents`, { cache: "no-store", headers: opHeaders() });
  if (!res.ok) return [];
  const body = await res.json();
  return Array.isArray(body?.incidents) ? body.incidents : [];
}

export async function ackIncident(id: string): Promise<boolean> {
  const res = await fetch(`${API_URL}/operator/incidents/${encodeURIComponent(id)}/ack`, { method: "POST", cache: "no-store", headers: opHeaders() });
  return res.ok;
}

export async function silenceIncident(id: string, seconds?: number): Promise<boolean> {
  const res = await fetch(`${API_URL}/operator/incidents/${encodeURIComponent(id)}/silence`, {
    method: "POST", cache: "no-store", headers: opHeaders(true), body: JSON.stringify({ seconds }),
  });
  return res.ok;
}

export async function unsilenceIncident(id: string): Promise<boolean> {
  const res = await fetch(`${API_URL}/operator/incidents/${encodeURIComponent(id)}/unsilence`, { method: "POST", cache: "no-store", headers: opHeaders() });
  return res.ok;
}

export async function noteIncident(id: string, note: string): Promise<boolean> {
  const res = await fetch(`${API_URL}/operator/incidents/${encodeURIComponent(id)}`, {
    method: "PATCH", cache: "no-store", headers: opHeaders(true), body: JSON.stringify({ note }),
  });
  return res.ok;
}

export async function assignIncident(id: string, assignee: string): Promise<boolean> {
  const res = await fetch(`${API_URL}/operator/incidents/${encodeURIComponent(id)}/assign`, {
    method: "POST", cache: "no-store", headers: opHeaders(true), body: JSON.stringify({ assignee }),
  });
  return res.ok;
}

export async function unassignIncident(id: string): Promise<boolean> {
  const res = await fetch(`${API_URL}/operator/incidents/${encodeURIComponent(id)}/unassign`, { method: "POST", cache: "no-store", headers: opHeaders() });
  return res.ok;
}

export async function fetchIncidentHistory(id: string): Promise<IncidentEvent[]> {
  const res = await fetch(`${API_URL}/operator/incidents/${encodeURIComponent(id)}/history`, { cache: "no-store", headers: opHeaders() });
  if (!res.ok) return [];
  const body = await res.json();
  return Array.isArray(body?.history) ? body.history : [];
}

// ── external incident sync (operator-only outbound export) ───────────────────

export async function fetchIncidentTargets(): Promise<IncidentTarget[]> {
  const res = await fetch(`${API_URL}/operator/incident-targets`, { cache: "no-store", headers: opHeaders() });
  if (!res.ok) return [];
  const body = await res.json();
  return Array.isArray(body?.targets) ? body.targets : [];
}

export async function fetchIncidentSync(opts: { status?: string; incidentId?: string; limit?: number } = {}): Promise<IncidentSyncRecord[]> {
  const params = new URLSearchParams();
  if (opts.status) params.set("status", opts.status);
  if (opts.incidentId) params.set("incident_id", opts.incidentId);
  if (opts.limit) params.set("limit", String(opts.limit));
  const qs = params.toString();
  const res = await fetch(`${API_URL}/operator/incident-sync${qs ? `?${qs}` : ""}`, { cache: "no-store", headers: opHeaders() });
  if (!res.ok) return [];
  const body = await res.json();
  return Array.isArray(body?.records) ? body.records : [];
}

export async function redriveIncidentSync(id: string): Promise<{ ok: boolean; message?: string }> {
  const res = await fetch(`${API_URL}/operator/incident-sync/${encodeURIComponent(id)}/redrive`, { method: "POST", cache: "no-store", headers: opHeaders() });
  const body = await res.json().catch(() => null);
  if (res.ok) return { ok: true, message: body?.message };
  return { ok: false, message: body?.detail };
}

export async function fetchIncidentSyncStatus(incidentId: string): Promise<IncidentSyncStatus | null> {
  const res = await fetch(`${API_URL}/operator/incidents/${encodeURIComponent(incidentId)}/sync`, { cache: "no-store", headers: opHeaders() });
  if (!res.ok) return null;
  return res.json();
}

export async function refreshIncidentSync(incidentId: string): Promise<IncidentSyncStatus | null> {
  const res = await fetch(`${API_URL}/operator/incidents/${encodeURIComponent(incidentId)}/sync/refresh`, { method: "POST", cache: "no-store", headers: opHeaders() });
  if (!res.ok) return null;
  return res.json();
}

export async function redriveIncidentSyncContext(incidentId: string): Promise<{ ok: boolean; message?: string }> {
  const res = await fetch(`${API_URL}/operator/incidents/${encodeURIComponent(incidentId)}/sync/redrive`, { method: "POST", cache: "no-store", headers: opHeaders() });
  const body = await res.json().catch(() => null);
  return res.ok ? { ok: true, message: body?.message } : { ok: false, message: body?.detail };
}

export async function detachIncidentLink(incidentId: string, targetId: string): Promise<IncidentSyncStatus | null> {
  const res = await fetch(`${API_URL}/operator/incidents/${encodeURIComponent(incidentId)}/sync/detach`, {
    method: "POST", cache: "no-store", headers: opHeaders(true), body: JSON.stringify({ target_id: targetId }),
  });
  if (!res.ok) return null;
  return res.json();
}

export async function relinkIncident(incidentId: string, targetId: string, externalRef: string, externalUrl?: string): Promise<{ ok: boolean; message?: string }> {
  const res = await fetch(`${API_URL}/operator/incidents/${encodeURIComponent(incidentId)}/sync/relink`, {
    method: "POST", cache: "no-store", headers: opHeaders(true),
    body: JSON.stringify({ target_id: targetId, external_ref: externalRef, external_url: externalUrl }),
  });
  const body = await res.json().catch(() => null);
  return res.ok ? { ok: true, message: body?.message } : { ok: false, message: body?.detail };
}

export async function reconcileIncidentSync(): Promise<Record<string, number> | null> {
  const res = await fetch(`${API_URL}/operator/incident-sync/reconcile`, { method: "POST", cache: "no-store", headers: opHeaders() });
  if (!res.ok) return null;
  const body = await res.json();
  return body?.reconciled ?? null;
}

export async function applyExternalState(incidentId: string, action: "accept_resolved" | "accept_missing"): Promise<{ ok: boolean; message?: string; changed_local?: boolean }> {
  const res = await fetch(`${API_URL}/operator/incidents/${encodeURIComponent(incidentId)}/sync/apply`, {
    method: "POST", cache: "no-store", headers: opHeaders(true), body: JSON.stringify({ action }),
  });
  const body = await res.json().catch(() => null);
  return res.ok ? { ok: true, changed_local: body?.changed_local, message: body?.message } : { ok: false, message: body?.detail };
}

export async function pushIncidentOutward(incidentId: string, targetId?: string): Promise<{ ok: boolean; message?: string }> {
  const res = await fetch(`${API_URL}/operator/incidents/${encodeURIComponent(incidentId)}/sync/push`, {
    method: "POST", cache: "no-store", headers: opHeaders(true), body: JSON.stringify({ target_id: targetId }),
  });
  const body = await res.json().catch(() => null);
  return res.ok ? { ok: true, message: body?.message } : { ok: false, message: body?.detail };
}
