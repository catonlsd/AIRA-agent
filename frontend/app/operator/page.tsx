"use client";

// Operator delivery console — OPERATOR-ONLY. Renders outside the product nav
// (see AppShell) and is never linked from the user UI. Backed entirely by the
// already-gated /operator/* APIs; the service key is entered here and kept in
// sessionStorage. Three focused tabs — Overview (summary + destination health +
// in-console tuning + routing explainability), History (delivery attempts with
// filters + redrive lineage), and Recovery (dead-letters + redrive + lineage).
// Secrets are never shown; payloads are never rendered.

import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  BellOff,
  BellRing,
  Check,
  CheckCheck,
  CheckCircle2,
  ChevronDown,
  ExternalLink,
  Flame,
  GitBranch,
  History,
  LayoutGrid,
  Link2,
  LockKeyhole,
  MessageSquarePlus,
  RefreshCw,
  Unlink,
  Send,
  Share2,
  ShieldCheck,
  SlidersHorizontal,
  Snowflake,
  Upload,
  User,
  UserMinus,
  UserPlus,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { TONE_DOT, TONE_TEXT, Badge, Stat, INC_BTN, PANEL, SECTION_LABEL } from "@/components/ui";
import {
  ackIncident,
  assignIncident,
  canRedrive,
  clearCooldown,
  clearOperatorKey,
  deadLetterLabel,
  deadLetterTone,
  deliveryStatusTone,
  fetchAnalytics,
  fetchDeadLetters,
  fetchDeliveries,
  fetchDestinationHealth,
  fetchIncidentHistory,
  fetchIncidentSync,
  fetchIncidentSyncStatus,
  fetchIncidentTargets,
  fetchIncidentMetrics,
  fetchDemoStatus,
  seedDemo,
  resetDemo,
  demoSeedSummary,
  fetchIncidents,
  fetchLineage,
  fetchRoutingPreview,
  getOperatorKey,
  getOperatorName,
  healthTone,
  actionEffectLabel,
  applyActionLabel,
  applyExternalState,
  detachIncidentLink,
  hiddenInboundFields,
  invokeExternalAction,
  incidentEventLabel,
  incidentSyncSummary,
  incidentTone,
  noteIncident,
  pushIncidentOutward,
  readinessLabel,
  readinessTone,
  recommendedActionLabel,
  attentionRollupRows,
  readinessDashboardRows,
  sloRows,
  alertSeverityTone,
  trendWindowLabel,
  formatMetricPct,
  formatAgeSeconds,
  redriveIncidentSyncContext,
  refreshIncidentSync,
  relinkIncident,
  supportLevelLabel,
  testTarget,
  validateTarget,
  patchDestination,
  redriveBlockedReason,
  redriveDelivery,
  redriveIncidentSync,
  runSweep,
  setOperatorKey,
  setOperatorName,
  silenceIncident,
  syncStatusTone,
  unassignIncident,
  unsilenceIncident,
  verifyOperator,
  type DeadLetter,
  type Delivery,
  type DeliveryAnalytics,
  type DeliveryLineage,
  type DestinationHealth,
  type DestinationTuning,
  type Incident,
  type IncidentEvent,
  type IncidentSyncRecord,
  type IncidentSyncStatus,
  type IncidentTarget,
  type IncidentMetrics,
  type MetricCategory,
  type DemoStatus,
  type RoutingPreview,
  type Tone,
} from "@/lib/operator";

// Status colors (TONE_DOT/TONE_TEXT), Badge, and Stat now come from the shared
// design system (@/components/ui) — see the import above. No visual change.

function relTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso).getTime();
  if (Number.isNaN(d)) return "";
  const s = Math.max(0, Math.round((Date.now() - d) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

type Tab = "overview" | "incidents" | "history" | "recovery";

function relTimeUntil(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso).getTime();
  if (Number.isNaN(d)) return "";
  const s = Math.max(0, Math.round((d - Date.now()) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  return `${Math.round(s / 3600)}h`;
}

// ── external incident sync (Incidents tab) — targets + recent attempts ────────
// INC_BTN now comes from @/components/ui (shared button base).

const METRIC_LABELS: Record<MetricCategory, string> = {
  validation: "Validation", reconciliation: "Reconciliation", refresh: "Refresh",
  apply: "Apply", external_action: "External action", sync: "Sync",
};

// Observability panel (Phase 5): bounded, deterministic operational metrics computed
// server-side from existing audit/history. Observe-only — no actions live here.
function MetricsPanel({ metrics, window }: { metrics: IncidentMetrics | null; window: "24h" | "7d" | "30d" }) {
  if (!metrics) return null;
  const { readiness, slo, drift, alerts } = metrics;
  if (readiness.total === 0) return null;
  const healthRows = readinessDashboardRows(readiness);
  const indicators = sloRows(slo);
  // Per-category pass rate for the selected trend window.
  const windowRows = (Object.keys(METRIC_LABELS) as MetricCategory[]).map((cat) => {
    const w = metrics.windows[cat]?.[window];
    return { cat, label: METRIC_LABELS[cat], pass_pct: w?.pass_pct ?? null, total: w?.total ?? 0 };
  });
  return (
    <section className={PANEL}>
      <div className="mb-3 flex items-baseline gap-2">
        <p className={SECTION_LABEL}>
          <Activity className="h-3.5 w-3.5" /> Sync observability
        </p>
        <span className="text-[11px] text-[var(--text-muted)]">· deterministic, computed from audit history</span>
      </div>

      {/* SLO indicators */}
      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {indicators.map((s) => (
          <div key={s.key} className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-2">
            <p className="text-[11px] uppercase tracking-wide text-[var(--text-subtle)]">{s.label}</p>
            <p className={cn("text-lg font-black", TONE_TEXT[s.tone])}>{s.value}</p>
          </div>
        ))}
      </div>

      {/* Targets by state */}
      <div className="mb-3 flex flex-wrap items-center gap-1.5" aria-label="Targets by state">
        {healthRows.map((r) => (
          <span key={r.key} className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-2 py-0.5 text-[11px]">
            <Badge tone={r.tone}>{r.count}</Badge>
            <span className="font-black text-[var(--text-strong)]">{r.label}</span>
          </span>
        ))}
      </div>

      {/* Trend window: per-category pass rate */}
      <div className="mb-1 flex flex-wrap items-center gap-2 text-[11px]">
        <span className="font-black text-[var(--text-subtle)]">{trendWindowLabel(window)} pass rate:</span>
        {windowRows.map((w) => (
          <span key={w.cat} className="inline-flex items-center gap-1 text-[var(--text-muted)]" title={`${w.total} events`}>
            {w.label} <span className="font-black text-[var(--text-strong)]">{formatMetricPct(w.pass_pct)}</span>
          </span>
        ))}
      </div>

      {/* Drift backlog */}
      {drift.backlog > 0 ? (
        <p className="mt-2 text-[11px] text-[var(--text-muted)]">
          <span className="font-black text-[var(--warning)]">Drift backlog: {drift.backlog}</span>
          {drift.oldest ? <span> · oldest {drift.oldest.link_status} on {drift.oldest.target}, {formatAgeSeconds(drift.oldest.age_seconds)}</span> : null}
        </p>
      ) : null}

      {/* Candidate alerts (observations only — no actions, no paging) */}
      {alerts.length > 0 ? (
        <div className="mt-3 grid gap-1.5">
          {alerts.map((a, i) => (
            <div key={`${a.code}-${a.subject}-${i}`} className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-muted)] px-2.5 py-1.5 text-[11px]">
              <AlertTriangle className={cn("h-3.5 w-3.5", TONE_TEXT[alertSeverityTone(a.severity)])} />
              <span className={cn("font-black uppercase tracking-wide", TONE_TEXT[alertSeverityTone(a.severity)])}>{a.severity}</span>
              <span className="font-black text-[var(--text-strong)]">{a.subject}</span>
              <span className="text-[var(--text-muted)]">{a.detail}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-2 text-[11px] text-[var(--text-subtle)]">No candidate alerts — all signals within thresholds.</p>
      )}
    </section>
  );
}

// Demo seed (Phase 6): one-click deterministic showcase data + a guided walkthrough.
// Operator-only; namespaced; never touches real data or the chat product.
function DemoPanel({ demo, busy, onSeed, onReset }: {
  demo: DemoStatus | null; busy: boolean;
  onSeed: () => void; onReset: () => void;
}) {
  if (!demo || !demo.enabled) return null;
  return (
    <section className="sarvam-card rounded-[1.5rem] border border-dashed border-[var(--border-strong)] p-5">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <p className={SECTION_LABEL}>
          <LayoutGrid className="h-3.5 w-3.5" /> Demo data
        </p>
        <span className="text-[11px] text-[var(--text-muted)]">
          · deterministic showcase in the <code>{demo.namespace}</code> namespace · never touches real data
        </span>
        <span className="ml-auto flex items-center gap-2">
          <button type="button" disabled={busy} onClick={onSeed} className={INC_BTN}>
            <Zap className="h-3 w-3" /> {demo.present ? "Re-seed" : "Seed demo data"}
          </button>
          {demo.present ? (
            <button type="button" disabled={busy} onClick={onReset} className={INC_BTN}>
              <Unlink className="h-3 w-3" /> Reset
            </button>
          ) : null}
        </span>
      </div>
      {demo.present && demo.tour.length > 0 ? (
        <ol className="mt-2 grid gap-1.5">
          {demo.tour.map((s) => (
            <li key={s.step} className="flex gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-muted)] px-2.5 py-1.5 text-[11px]">
              <span className="font-black text-[var(--accent)]">{s.step}</span>
              <span>
                <span className="font-black text-[var(--text-strong)]">{s.area}</span>
                <span className="text-[var(--text-subtle)]"> — {s.look_at}</span>
                <span className="block text-[var(--text-muted)]">{s.shows}</span>
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="mt-1 text-[11px] text-[var(--text-muted)]">
          Populate targets across every readiness state, drifted/missing incidents, a live SLO dashboard, and a candidate alert — for demos & evaluation.
        </p>
      )}
    </section>
  );
}

function SyncPanel({ targets, records, onRedrive, onValidate, onTest, busyId, flash }: {
  targets: IncidentTarget[]; records: IncidentSyncRecord[];
  onRedrive: (id: string) => void; onValidate: (id: string) => void; onTest: (id: string) => void;
  busyId: string | null; flash: Record<string, string>;
}) {
  if (targets.length === 0 && records.length === 0) return null;
  const failed = records.filter((r) => r.status === "failed");
  const attention = targets.filter((t) => t.enabled && t.readiness.state !== "ready");
  // Deterministic triage rollup from already-loaded targets — grouped by readiness
  // state, hard failures first, each labeled with the action that clears it.
  const byState = attention.reduce<Record<string, number>>((acc, t) => {
    acc[t.readiness.state] = (acc[t.readiness.state] ?? 0) + 1; return acc;
  }, {});
  const rollup = attentionRollupRows({ by_state: byState });
  return (
    <section className={PANEL}>
      <div className="mb-3 flex items-baseline gap-2">
        <p className={SECTION_LABEL}>
          <Share2 className="h-3.5 w-3.5" /> External sync
        </p>
        <span className="text-[11px] text-[var(--text-muted)]">· outbound incident export</span>
        {attention.length > 0 ? <span className="rounded-full border border-[var(--warning)] px-1.5 text-[11px] font-black text-[var(--warning)]">{attention.length} need{attention.length === 1 ? "s" : ""} attention</span> : null}
        {failed.length > 0 ? <span className="ml-auto rounded-full bg-[var(--danger)] px-1.5 text-[11px] font-black text-white">{failed.length} failed</span> : null}
      </div>

      {rollup.length > 0 ? (
        <div className="mb-3 flex flex-wrap items-center gap-1.5" aria-label="Attention rollup">
          {rollup.map((r) => (
            <span key={r.state} className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-2 py-0.5 text-[11px]">
              <Badge tone={r.tone}>{r.count}</Badge>
              <span className="font-black text-[var(--text-strong)]">{r.label}</span>
              {r.action ? <span className="text-[var(--text-subtle)]">→ {r.action}</span> : null}
            </span>
          ))}
        </div>
      ) : null}

      {targets.length > 0 ? (
        <div className="mb-3 grid gap-1.5">
          {targets.map((t) => (
            <div key={t.id} className="flex flex-wrap items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] px-2.5 py-1.5 text-[11px]">
              <span className={cn("h-1.5 w-1.5 rounded-full", t.enabled ? "bg-[var(--success)]" : "bg-[var(--text-subtle)]")} aria-hidden="true" />
              <span className={cn("font-black", t.enabled ? "text-[var(--text-strong)]" : "text-[var(--text-subtle)] line-through")}>{t.name}</span>
              <span className="text-[var(--text-subtle)]">· {t.kind}</span>
              {t.profile && t.profile !== t.kind ? <span className="rounded-full border border-[var(--border)] px-1.5 text-[11px] uppercase tracking-wide text-[var(--text-subtle)]">{t.profile}</span> : null}
              <Badge tone={readinessTone(t.readiness.state)}>{readinessLabel(t.readiness.state)}</Badge>
              {t.readiness_facts.last_validated_at ? <span className="text-[var(--text-subtle)]">checked {relTime(t.readiness_facts.last_validated_at)}</span> : null}
              {t.readiness.state !== "ready" && t.readiness.reason ? <span className="text-[var(--text-subtle)]">· {t.readiness.reason}</span> : null}
              {recommendedActionLabel(t.readiness.recommended_action) ? (
                <span className="rounded-full border border-[var(--warning)] px-1.5 text-[11px] font-black text-[var(--warning)]" title={t.readiness.next_step ?? undefined}>→ {recommendedActionLabel(t.readiness.recommended_action)}</span>
              ) : null}
              {t.consecutive_failures > 0 ? <span className="text-[var(--danger)]">⚠ {t.consecutive_failures}</span> : null}
              <span className="ml-auto flex items-center gap-1.5">
                {flash[t.id] ? <span className="text-[var(--success)]">{flash[t.id]}</span> : null}
                <button type="button" disabled={busyId === t.id} onClick={() => onValidate(t.id)} className={INC_BTN}>
                  <ShieldCheck className="h-3 w-3" /> Validate
                </button>
                <button type="button" disabled={busyId === t.id || !t.enabled} onClick={() => onTest(t.id)} className={INC_BTN}
                  title={t.enabled ? "Send a synthetic, no-op test event" : "Target is disabled"}>
                  <Send className="h-3 w-3" /> Test
                </button>
              </span>
            </div>
          ))}
        </div>
      ) : (
        <p className="mb-2 text-[11px] text-[var(--text-muted)]">No sync targets configured — incident transitions stay local.</p>
      )}

      {records.length > 0 ? (
        <div className="grid gap-1">
          {records.slice(0, 8).map((r) => (
            <div key={r.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-muted)] px-2.5 py-1.5 text-[11px]">
              <Badge tone={syncStatusTone(r.status)}>{r.status}</Badge>
              <span className="font-black text-[var(--text-strong)]">{incidentEventLabel(r.action)}</span>
              <span className="text-[var(--text-muted)]">{r.classification ?? r.signal} → {r.target_name ?? r.target_kind}{r.is_redrive ? " (redrive)" : ""}</span>
              {r.last_error ? <span className="text-[var(--danger)]">· {r.last_error}</span> : null}
              {r.external_url ? (
                <a href={r.external_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-black text-[var(--accent)] hover:underline">
                  <ExternalLink className="h-3 w-3" /> Open
                </a>
              ) : null}
              <span className="ml-auto text-[var(--text-subtle)]">{relTime(r.created_at)}</span>
              {r.status === "failed" ? (
                <button type="button" disabled={busyId === r.id} onClick={() => onRedrive(r.id)} className={INC_BTN}>
                  <RefreshCw className="h-3 w-3" /> Redrive
                </button>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

// ── incident row (Incidents tab) — state + assignment + notes + action trail ──

function IncidentRow({ inc, operatorName, onChanged }: {
  inc: Incident; operatorName: string | null; onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [history, setHistory] = useState<IncidentEvent[] | null>(null);
  const [sync, setSync] = useState<IncidentSyncStatus | null>(null);
  const [editingNote, setEditingNote] = useState(false);
  const [noteDraft, setNoteDraft] = useState(inc.note ?? "");
  const silenceLeft = inc.state === "silenced" ? relTimeUntil(inc.silenced_until) : "";
  const ownedByMe = Boolean(operatorName) && inc.assignee === operatorName;

  const act = useCallback(async (fn: () => Promise<boolean>) => {
    setBusy(true);
    try { await fn(); onChanged(); } finally { setBusy(false); }
  }, [onChanged]);

  const toggleHistory = useCallback(async () => {
    const next = !expanded;
    setExpanded(next);
    if (next) {
      const [h, s] = await Promise.all([fetchIncidentHistory(inc.id), fetchIncidentSyncStatus(inc.id)]);
      setHistory(h);
      setSync(s);
    }
  }, [expanded, inc.id]);

  const [relinking, setRelinking] = useState(false);
  const [refDraft, setRefDraft] = useState("");

  const onRefreshSync = useCallback(async () => {
    setBusy(true);
    try {
      const s = await refreshIncidentSync(inc.id);
      if (s) setSync(s);
    } finally { setBusy(false); }
  }, [inc.id]);

  const syncLine = sync ? incidentSyncSummary(sync.summary) : null;
  const link = sync?.links.find((l) => l.external_url) ?? sync?.links[0];
  const actions = sync?.summary.actions;

  const onSyncRepair = useCallback(async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try { await fn(); setSync(await fetchIncidentSyncStatus(inc.id)); } finally { setBusy(false); }
  }, [inc.id]);

  const onDetach = useCallback(() => {
    if (!link) return;
    void onSyncRepair(() => detachIncidentLink(inc.id, link.target_id));
  }, [inc.id, link, onSyncRepair]);

  const onRelink = useCallback(() => {
    if (!link || !refDraft.trim()) return;
    void onSyncRepair(async () => { await relinkIncident(inc.id, link.target_id, refDraft.trim()); setRelinking(false); setRefDraft(""); });
  }, [inc.id, link, refDraft, onSyncRepair]);

  const onRedriveSyncCtx = useCallback(() => {
    void onSyncRepair(() => redriveIncidentSyncContext(inc.id));
  }, [inc.id, onSyncRepair]);

  const onApply = useCallback(() => {
    const action = sync?.summary.actions.apply_action;
    if (!action) return;
    setBusy(true);
    void (async () => {
      try {
        const res = await applyExternalState(inc.id, action);
        setSync(await fetchIncidentSyncStatus(inc.id));
        if (res.ok && res.changed_local) onChanged(); // local incident state changed
      } finally { setBusy(false); }
    })();
  }, [inc.id, sync, onChanged]);

  const onPush = useCallback(() => {
    void onSyncRepair(() => pushIncidentOutward(inc.id));
  }, [inc.id, onSyncRepair]);

  // Vendor-typed external actions surfaced from the backend's available_actions list
  // (only the ones that are actually available — capability + per-target policy).
  const externalActions = (sync?.summary.available_actions ?? []).filter(
    (a) => a.available && (a.action === "external_resolve" || a.action === "external_reopen" || a.action === "external_acknowledge"));
  const onExternalAction = useCallback((action: "external_resolve" | "external_reopen" | "external_acknowledge") => {
    void onSyncRepair(() => invokeExternalAction(inc.id, action));
  }, [inc.id, onSyncRepair]);

  const saveNote = useCallback(async () => {
    setBusy(true);
    try { if (await noteIncident(inc.id, noteDraft.slice(0, 280))) { setEditingNote(false); onChanged(); } }
    finally { setBusy(false); }
  }, [inc.id, noteDraft, onChanged]);

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-3.5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={incidentTone(inc.state)}>{inc.state}</Badge>
        <span className="text-sm font-black text-[var(--text-strong)]">{inc.classification}</span>
        <span className="text-xs text-[var(--text-muted)]">· {inc.subject}</span>
        {inc.severity ? <span className="text-[11px] font-bold uppercase tracking-wide text-[var(--text-subtle)]">{inc.severity}</span> : null}
        <span className="ml-auto text-[11px] text-[var(--text-subtle)]">×{inc.occurrences} · last {relTime(inc.last_seen)}</span>
      </div>

      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-[var(--text-muted)]">
        <span className="inline-flex items-center gap-1 font-semibold text-[var(--text-strong)]">
          <User className="h-3 w-3" />
          {inc.assignee ? `Owned by ${inc.assignee}${ownedByMe ? " (you)" : ""}` : "Unassigned"}
        </span>
        {inc.acknowledged_at ? <span>acknowledged {relTime(inc.acknowledged_at)}</span> : null}
        {inc.state === "silenced" && silenceLeft ? <span className="font-semibold text-[var(--text-strong)]">silenced · {silenceLeft} left</span> : null}
        {inc.state === "recovered" && inc.recovered_at ? <span className="font-semibold text-[var(--success)]">recovered {relTime(inc.recovered_at)}</span> : null}
      </div>

      {inc.note && !editingNote ? (
        <p className="mt-2 rounded-lg border border-[var(--border)] bg-[var(--surface-muted)] px-2.5 py-1.5 text-[11px] text-[var(--text-muted)]">📝 {inc.note}</p>
      ) : null}

      {editingNote ? (
        <div className="mt-2 flex flex-col gap-1.5">
          <textarea value={noteDraft} maxLength={280} onChange={(e) => setNoteDraft(e.target.value)}
            placeholder="Short note for the next operator…" rows={2}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-muted)] px-2.5 py-1.5 text-[11px] text-[var(--text-strong)] outline-none focus:border-[var(--border-strong)]" />
          <div className="flex gap-1.5">
            <button type="button" disabled={busy} onClick={() => void saveNote()} className={INC_BTN}>Save note</button>
            <button type="button" onClick={() => { setEditingNote(false); setNoteDraft(inc.note ?? ""); }} className={INC_BTN}>Cancel</button>
          </div>
        </div>
      ) : null}

      <div className="mt-2.5 flex flex-wrap gap-1.5">
        {inc.state !== "recovered" ? (
          <>
            {!inc.acknowledged ? (
              <button type="button" disabled={busy} onClick={() => void act(() => ackIncident(inc.id))} className={INC_BTN}>
                <Check className="h-3 w-3" /> Acknowledge
              </button>
            ) : null}
            {inc.state === "silenced" ? (
              <button type="button" disabled={busy} onClick={() => void act(() => unsilenceIncident(inc.id))} className={INC_BTN}>
                <BellRing className="h-3 w-3" /> Unsilence
              </button>
            ) : (
              <button type="button" disabled={busy} onClick={() => void act(() => silenceIncident(inc.id))} className={INC_BTN}>
                <BellOff className="h-3 w-3" /> Silence
              </button>
            )}
            {!ownedByMe ? (
              <button type="button" disabled={busy || !operatorName} title={operatorName ? "" : "Set your operator name when connecting to claim"}
                onClick={() => operatorName && void act(() => assignIncident(inc.id, operatorName))} className={INC_BTN}>
                <UserPlus className="h-3 w-3" /> Claim
              </button>
            ) : null}
            {inc.assignee ? (
              <button type="button" disabled={busy} onClick={() => void act(() => unassignIncident(inc.id))} className={INC_BTN}>
                <UserMinus className="h-3 w-3" /> Release
              </button>
            ) : null}
            <button type="button" disabled={busy} onClick={() => { setEditingNote(true); setNoteDraft(inc.note ?? ""); }} className={INC_BTN}>
              <MessageSquarePlus className="h-3 w-3" /> Note
            </button>
          </>
        ) : null}
        <button type="button" onClick={() => void toggleHistory()} className={INC_BTN}>
          <ChevronDown className={cn("h-3 w-3 transition", expanded ? "rotate-180" : "")} /> History
        </button>
      </div>

      {expanded ? (
        <div className="mt-2 rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3">
          <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-black uppercase tracking-wide text-[var(--text-subtle)]">
            <History className="h-3 w-3" /> Action trail
          </p>
          {history === null ? (
            <p className="text-[11px] text-[var(--text-muted)]">Loading…</p>
          ) : history.length === 0 ? (
            <p className="text-[11px] text-[var(--text-muted)]">No recorded actions yet.</p>
          ) : (
            <ol className="grid gap-1">
              {history.map((e, i) => (
                <li key={i} className="flex flex-wrap items-baseline gap-x-2 text-[11px] text-[var(--text-muted)]">
                  <span className="font-black text-[var(--text-strong)]">{incidentEventLabel(e.action)}</span>
                  {e.actor ? <span>by {e.actor}</span> : null}
                  {e.detail ? <span className="text-[var(--text-subtle)]">· {e.detail}</span> : null}
                  <span className="ml-auto text-[var(--text-subtle)]">{relTime(e.at)}</span>
                </li>
              ))}
            </ol>
          )}

          {syncLine ? (
            <div className="mt-2.5 border-t border-[var(--border)] pt-2">
              <p className="mb-1 flex items-center gap-1.5 text-[11px] font-black uppercase tracking-wide text-[var(--text-subtle)]">
                <Share2 className="h-3 w-3" /> External sync
                {sync ? <span className="ml-1 rounded-full border border-[var(--border)] px-1.5 py-0.5 text-[9px] font-bold normal-case tracking-normal text-[var(--text-muted)]">{supportLevelLabel(sync.summary.support_level)}</span> : null}
              </p>

              {sync && sync.summary.suggestions.length > 0 ? (
                <ul className="mb-1.5 grid gap-0.5">
                  {sync.summary.suggestions.map((s, i) => (
                    <li key={i} className="flex items-center gap-1.5 text-[11px]">
                      <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", TONE_DOT[s.tone])} aria-hidden="true" />
                      <span className={TONE_TEXT[s.tone]}>{s.text}</span>
                    </li>
                  ))}
                </ul>
              ) : null}

              {link && (link.external_assignee || link.external_severity || link.external_comment_count != null) ? (
                <div className="mb-1.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-[var(--text-subtle)]">
                  {link.external_assignee ? <span>external owner: {link.external_assignee}</span> : null}
                  {link.external_severity ? <span>severity: {link.external_severity}</span> : null}
                  {link.external_comment_count != null ? <span>{link.external_comment_count} note{link.external_comment_count === 1 ? "" : "s"}</span> : null}
                  {link.external_updated_at ? <span>updated {link.external_updated_at}</span> : null}
                </div>
              ) : null}

              {link && hiddenInboundFields(link).length > 0 ? (
                <p className="mb-1.5 text-[11px] text-[var(--text-subtle)]">
                  Hidden by target policy: {hiddenInboundFields(link).join(", ")}
                </p>
              ) : null}
              {link && !link.suggestions_allowed ? (
                <p className="mb-1.5 text-[11px] text-[var(--text-subtle)]">Suggestions disabled for this target.</p>
              ) : null}

              <div className="flex flex-wrap items-center gap-2 text-[11px]">
                <Badge tone={syncLine.tone}>{syncLine.label}</Badge>
                {link?.target_name ? <span className="text-[var(--text-muted)]">{link.target_name}{link.target_kind ? ` · ${link.target_kind}` : ""}</span> : null}
                {link?.profile && link.profile !== link.target_kind ? (
                  <span className="rounded-full border border-[var(--border)] px-1.5 py-0.5 text-[11px] font-bold uppercase tracking-wide text-[var(--text-subtle)]">{link.profile}</span>
                ) : null}
                {link?.external_ref ? <span className="text-[var(--text-subtle)]">ref {link.external_ref}</span> : null}
                {link?.external_url ? (
                  <a href={link.external_url} target="_blank" rel="noreferrer"
                    className="inline-flex items-center gap-1 font-black text-[var(--accent)] hover:underline">
                    <ExternalLink className="h-3 w-3" /> Open
                  </a>
                ) : null}
                {actions?.can_refresh ? (
                  <button type="button" disabled={busy} onClick={() => void onRefreshSync()} className={INC_BTN}>
                    <RefreshCw className="h-3 w-3" /> Refresh
                  </button>
                ) : null}
                {actions?.can_redrive ? (
                  <button type="button" disabled={busy} onClick={onRedriveSyncCtx} className={INC_BTN}>
                    <RefreshCw className="h-3 w-3" /> Redrive
                  </button>
                ) : null}
                {actions?.can_detach ? (
                  <button type="button" disabled={busy} onClick={onDetach} className={INC_BTN}>
                    <Unlink className="h-3 w-3" /> Detach
                  </button>
                ) : null}
                {actions?.can_relink ? (
                  <button type="button" disabled={busy} onClick={() => setRelinking((v) => !v)} className={INC_BTN}>
                    <Link2 className="h-3 w-3" /> Relink
                  </button>
                ) : null}
                {actions?.can_apply && actions.apply_action ? (
                  <button type="button" disabled={busy} onClick={onApply} title={applyActionLabel(actions.apply_action)}
                    className={cn(INC_BTN, "border-[var(--accent)] text-[var(--accent)]")}>
                    <CheckCheck className="h-3 w-3" /> {actions.apply_action === "accept_resolved" ? "Apply resolution" : "Accept missing"}
                  </button>
                ) : null}
                {actions?.can_push ? (
                  <button type="button" disabled={busy} onClick={onPush} className={INC_BTN}>
                    <Upload className="h-3 w-3" /> Push outward
                  </button>
                ) : null}
                {externalActions.map((a) => (
                  <button key={a.action} type="button" disabled={busy}
                    onClick={() => onExternalAction(a.action as "external_resolve" | "external_reopen" | "external_acknowledge")}
                    title={`${a.label} · ${actionEffectLabel(a.effect)}`} className={INC_BTN}>
                    <Upload className="h-3 w-3" /> {a.label}
                  </button>
                ))}
              </div>
              {actions?.can_apply && actions.apply_action ? (
                <p className="mt-1 text-[11px] text-[var(--text-subtle)]">
                  {applyActionLabel(actions.apply_action)}
                  {" · "}
                  <span className="font-bold">{actionEffectLabel(actions.apply_action === "accept_resolved" ? "local" : "linkage")}</span>
                </p>
              ) : null}

              {relinking ? (
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                  <input value={refDraft} onChange={(e) => setRefDraft(e.target.value)} placeholder="External reference (verified via adapter)"
                    className="min-w-[12rem] flex-1 rounded-lg border border-[var(--border)] bg-[var(--surface-muted)] px-2.5 py-1 text-[11px] text-[var(--text-strong)] outline-none focus:border-[var(--border-strong)]" />
                  <button type="button" disabled={busy || !refDraft.trim()} onClick={onRelink} className={INC_BTN}>Verify &amp; relink</button>
                </div>
              ) : null}

              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-[var(--text-subtle)]">
                {sync?.summary.reason ? <span>{sync.summary.reason}</span> : null}
                {link?.external_status ? <span>external: {link.external_status}</span> : null}
                {sync?.summary.last_synced_at ? <span>synced {relTime(sync.summary.last_synced_at)}</span> : null}
                {sync?.summary.last_checked_at ? <span>checked {relTime(sync.summary.last_checked_at)}</span> : (
                  sync?.summary.refresh_supported ? <span>never checked</span> : <span>refresh unsupported</span>
                )}
                {sync && sync.reconciliation.length > 0 ? (
                  <span>· last action: {sync.reconciliation[0].action} ({sync.reconciliation[0].outcome})</span>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

// ── delivery-lineage drill-down (shared by History + Recovery) ────────────────
function LineageChain({ lineage }: { lineage: DeliveryLineage }) {
  return (
    <div className="mt-2 rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3">
      <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-black uppercase tracking-wide text-[var(--text-subtle)]">
        <GitBranch className="h-3 w-3" /> Redrive lineage · {lineage.attempts.length} attempt{lineage.attempts.length === 1 ? "" : "s"}
      </p>
      <div className="grid gap-1">
        {lineage.attempts.map((a, i) => (
          <p key={a.id} className="flex items-center gap-2 text-[11px] text-[var(--text-muted)]">
            <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", TONE_DOT[deliveryStatusTone(a.status)])} aria-hidden="true" />
            <span className="font-semibold text-[var(--text-strong)]">{i === 0 ? "Original" : `Redrive ${i}`}</span>
            <span>· {a.status}</span>
            <span>· {a.attempts} attempt(s)</span>
            {a.last_error ? <span className="text-[var(--danger)]">· {a.last_error}</span> : null}
            <span className="text-[var(--text-subtle)]">· {relTime(a.created_at)}</span>
          </p>
        ))}
      </div>
    </div>
  );
}

export default function OperatorConsole() {
  const [status, setStatus] = useState<"checking" | "needs_key" | "ready">("checking");
  const [keyInput, setKeyInput] = useState("");
  const [nameInput, setNameInput] = useState("");
  const [keyError, setKeyError] = useState("");
  const [tab, setTab] = useState<Tab>("overview");
  const [operatorName, setOperatorNameState] = useState<string | null>(null);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [syncTargets, setSyncTargets] = useState<IncidentTarget[]>([]);
  const [targetFlash, setTargetFlash] = useState<Record<string, string>>({});
  const [syncRecords, setSyncRecords] = useState<IncidentSyncRecord[]>([]);
  const [metrics, setMetrics] = useState<IncidentMetrics | null>(null);
  const [demo, setDemo] = useState<DemoStatus | null>(null);
  const [analytics, setAnalytics] = useState<DeliveryAnalytics | null>(null);
  const [destinations, setDestinations] = useState<DestinationHealth[]>([]);
  const [deadLetters, setDeadLetters] = useState<DeadLetter[]>([]);
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [filter, setFilter] = useState<{ status: string; destinationId: string }>({ status: "", destinationId: "" });
  const [busy, setBusy] = useState<string | null>(null);
  const [flash, setFlash] = useState<string>("");
  const [preview, setPreview] = useState<Record<string, RoutingPreview | null>>({});
  const [lineage, setLineage] = useState<Record<string, DeliveryLineage | null>>({});
  const [editing, setEditing] = useState<string | null>(null);
  const [tuneForm, setTuneForm] = useState<DestinationTuning>({});

  const load = useCallback(async () => {
    const [a, d, dl] = await Promise.all([fetchAnalytics(), fetchDestinationHealth(), fetchDeadLetters()]);
    setAnalytics(a);
    setDestinations(d);
    setDeadLetters(dl);
  }, []);

  const loadHistory = useCallback(async () => {
    setDeliveries(await fetchDeliveries({ status: filter.status || undefined, destinationId: filter.destinationId || undefined, limit: 60 }));
  }, [filter]);

  const loadIncidents = useCallback(async () => {
    const [inc, targets, records, m, d] = await Promise.all([
      fetchIncidents(), fetchIncidentTargets(), fetchIncidentSync({ limit: 30 }), fetchIncidentMetrics(), fetchDemoStatus()]);
    setIncidents(inc);
    setSyncTargets(targets);
    setSyncRecords(records);
    setMetrics(m);
    setDemo(d);
  }, []);

  useEffect(() => {
    setOperatorNameState(getOperatorName());
    if (!getOperatorKey()) { setStatus("needs_key"); return; }
    verifyOperator().then((ok) => {
      if (ok) { setStatus("ready"); void load(); void loadIncidents(); } else { setStatus("needs_key"); }
    });
  }, [load, loadIncidents]);

  useEffect(() => {
    if (status === "ready" && tab === "history") void loadHistory();
    if (status === "ready" && tab === "incidents") void loadIncidents();
  }, [status, tab, loadHistory, loadIncidents]);

  const connect = useCallback(async () => {
    setKeyError("");
    setOperatorKey(keyInput);
    setOperatorName(nameInput);            // self-declared handle (optional)
    setOperatorNameState(getOperatorName());
    if (await verifyOperator()) { setStatus("ready"); void load(); void loadIncidents(); }
    else { clearOperatorKey(); setKeyError("That service key was not accepted."); }
  }, [keyInput, nameInput, load, loadIncidents]);

  const disconnect = useCallback(() => {
    clearOperatorKey();
    setOperatorNameState(null);
    setStatus("needs_key");
    setAnalytics(null); setDestinations([]); setDeadLetters([]); setDeliveries([]); setIncidents([]);
    setSyncTargets([]); setSyncRecords([]); setMetrics(null); setDemo(null);
  }, []);

  const flashMsg = (msg: string) => { setFlash(msg); window.setTimeout(() => setFlash(""), 3000); };

  const onRedrive = useCallback(async (id: string) => {
    setBusy(id);
    try {
      const res = await redriveDelivery(id);
      flashMsg(res.ok ? "Redrive scheduled." : res.message || "Could not redrive.");
      await load();
    } finally { setBusy(null); }
  }, [load]);

  const onClearCooldown = useCallback(async (destId: string) => {
    setBusy(destId);
    try { if (await clearCooldown(destId)) flashMsg("Cooldown cleared."); await load(); }
    finally { setBusy(null); }
  }, [load]);

  const onPreview = useCallback(async (destId: string) => {
    if (preview[destId]) { setPreview((p) => ({ ...p, [destId]: null })); return; }
    const data = await fetchRoutingPreview(destId);
    setPreview((p) => ({ ...p, [destId]: data }));
  }, [preview]);

  const onLineage = useCallback(async (deliveryId: string) => {
    if (lineage[deliveryId]) { setLineage((l) => ({ ...l, [deliveryId]: null })); return; }
    const data = await fetchLineage(deliveryId);
    setLineage((l) => ({ ...l, [deliveryId]: data }));
  }, [lineage]);

  const onRedriveSync = useCallback(async (id: string) => {
    setBusy(id);
    try {
      const res = await redriveIncidentSync(id);
      flashMsg(res.ok ? "Sync redriven." : res.message || "Could not redrive sync.");
      await loadIncidents();
    } finally { setBusy(null); }
  }, [loadIncidents]);

  const onSeedDemo = useCallback(async () => {
    setBusy("demo");
    try {
      const m = await seedDemo();
      flashMsg(m ? demoSeedSummary(m) : "Could not seed demo data.");
      await loadIncidents();
    } finally { setBusy(null); }
  }, [loadIncidents]);

  const onResetDemo = useCallback(async () => {
    setBusy("demo");
    try {
      flashMsg((await resetDemo()) ? "Demo data cleared." : "Could not reset demo data.");
      await loadIncidents();
    } finally { setBusy(null); }
  }, [loadIncidents]);

  const flashTarget = useCallback((id: string, msg: string) => {
    setTargetFlash((f) => ({ ...f, [id]: msg }));
    window.setTimeout(() => setTargetFlash((f) => { const n = { ...f }; delete n[id]; return n; }), 4000);
  }, []);

  const onValidateTarget = useCallback(async (id: string) => {
    setBusy(id);
    try {
      const res = await validateTarget(id);
      flashTarget(id, res ? `${readinessLabel(res.readiness.state)}${res.ok ? "" : " — " + res.readiness.reason}` : "Validate failed.");
      await loadIncidents();
    } finally { setBusy(null); }
  }, [loadIncidents, flashTarget]);

  const onTestTarget = useCallback(async (id: string) => {
    setBusy(id);
    try {
      const res = await testTarget(id);
      flashTarget(id, res?.ok ? "Test event sent." : (res && "message" in res && res.message) || "Test failed.");
      await loadIncidents();
    } finally { setBusy(null); }
  }, [loadIncidents, flashTarget]);

  const startEdit = useCallback((d: DestinationHealth) => {
    setEditing(d.destination_id);
    setTuneForm({}); // tuning fields default to "unchanged" — only edited fields are sent
  }, []);

  const onSaveTuning = useCallback(async (destId: string) => {
    setBusy(destId);
    try {
      const res = await patchDestination(destId, tuneForm);
      flashMsg(res.ok ? "Destination updated." : res.message || "Update rejected.");
      if (res.ok) { setEditing(null); await load(); }
    } finally { setBusy(null); }
  }, [tuneForm, load]);

  const onSweep = useCallback(async () => {
    setBusy("sweep");
    try {
      const r = await runSweep();
      flashMsg(r ? `Swept — routed ${r.routed ?? 0}, suppressed ${r.suppressed ?? 0}, delivered ${r.delivered ?? 0}.` : "Sweep failed.");
      await load();
      if (tab === "history") await loadHistory();
    } finally { setBusy(null); }
  }, [load, loadHistory, tab]);

  // ── key gate ────────────────────────────────────────────────────────────────
  if (status !== "ready") {
    return (
      <div className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center px-6">
        <div className="sarvam-card w-full rounded-[1.5rem] p-6 text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--accent-soft)] text-[var(--accent)]">
            <LockKeyhole className="h-6 w-6" />
          </div>
          <h1 className="text-lg font-black tracking-tight text-[var(--text-strong)]">Operator console</h1>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            Delivery operations. Enter your service key — this area is operator-only and never shown in the product.
          </p>
          <input
            type="password" value={keyInput} onChange={(e) => setKeyInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && keyInput.trim()) void connect(); }}
            placeholder="Service key"
            className="mt-5 w-full rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-2.5 text-sm text-[var(--text-strong)] outline-none transition focus:border-[var(--border-strong)]"
          />
          <input
            type="text" value={nameInput} maxLength={80} onChange={(e) => setNameInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && keyInput.trim()) void connect(); }}
            placeholder="Your operator name (optional — for handoff)"
            className="mt-2.5 w-full rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-2.5 text-sm text-[var(--text-strong)] outline-none transition focus:border-[var(--border-strong)]"
          />
          {keyError ? <p className="mt-2 text-xs font-semibold text-[var(--danger)]">{keyError}</p> : null}
          <button type="button" onClick={() => void connect()} disabled={!keyInput.trim() || status === "checking"}
            className="mt-4 w-full rounded-full border border-transparent bg-[var(--accent)] px-4 py-2.5 text-sm font-black text-[var(--accent-contrast,#fff)] transition hover:opacity-90 disabled:opacity-60">
            {status === "checking" ? "Checking…" : "Connect"}
          </button>
        </div>
      </div>
    );
  }

  const openIncidentCount = incidents.filter((i) => i.state === "open").length;
  const TABS: { id: Tab; label: string; icon: typeof LayoutGrid; badge?: number }[] = [
    { id: "overview", label: "Overview", icon: LayoutGrid },
    { id: "incidents", label: "Incidents", icon: Flame, badge: openIncidentCount },
    { id: "history", label: "History", icon: History },
    { id: "recovery", label: "Recovery", icon: AlertTriangle },
  ];

  // ── console ──────────────────────────────────────────────────────────────────
  return (
    <div className="mx-auto min-h-screen w-full max-w-5xl px-4 py-6 sm:px-6">
      <header className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--accent-soft)] text-[var(--accent)]">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-lg font-black tracking-tight text-[var(--text-strong)]">Delivery console</h1>
            <p className="text-xs text-[var(--text-muted)]">
              Operator-only · health, history, tuning, and recovery
              {operatorName ? <span className="ml-1 font-semibold text-[var(--text-strong)]">· acting as {operatorName}</span> : null}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {flash ? <span className="text-xs font-semibold text-[var(--success)]">{flash}</span> : null}
          <button type="button" onClick={() => void onSweep()} disabled={busy === "sweep"}
            className="inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-1.5 text-xs font-black text-[var(--text-muted)] transition hover:text-[var(--text-strong)] disabled:opacity-60">
            <Zap className="h-3.5 w-3.5" /> {busy === "sweep" ? "Sweeping…" : "Sweep"}
          </button>
          <button type="button" onClick={() => { void load(); if (tab === "history") void loadHistory(); }}
            className="inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-1.5 text-xs font-black text-[var(--text-muted)] transition hover:text-[var(--text-strong)]">
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </button>
          <button type="button" onClick={disconnect}
            className="rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-1.5 text-xs font-black text-[var(--text-muted)] transition hover:text-[var(--danger)]">
            Disconnect
          </button>
        </div>
      </header>

      {/* Tabs */}
      <div className="mb-5 flex gap-1.5">
        {TABS.map((t) => (
          <button key={t.id} type="button" onClick={() => setTab(t.id)}
            className={cn("inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-xs font-black transition",
              tab === t.id ? "bg-[var(--accent)] text-[var(--accent-contrast,#fff)]" : "border border-[var(--border)] bg-[var(--surface-muted)] text-[var(--text-muted)] hover:text-[var(--text-strong)]")}>
            <t.icon className="h-3.5 w-3.5" /> {t.label}
            {t.id === "recovery" && deadLetters.length > 0 ? <span className="ml-0.5 rounded-full bg-[var(--danger)] px-1.5 text-[11px] text-white">{deadLetters.length}</span> : null}
            {t.id === "incidents" && t.badge ? <span className="ml-0.5 rounded-full bg-[var(--danger)] px-1.5 text-[11px] text-white">{t.badge}</span> : null}
          </button>
        ))}
      </div>

      {/* ── Overview ── */}
      {tab === "overview" ? (
        <div className="grid gap-5">
          {analytics ? (
            <section className={PANEL}>
              <p className="mb-3 text-xs font-bold uppercase tracking-[0.16em] text-[var(--text-muted)]">Delivery summary · last {analytics.window_minutes}m</p>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                <Stat label="Attempted" value={analytics.totals.attempted} />
                <Stat label="Delivered" value={analytics.totals.delivered} />
                <Stat label="Failed" value={analytics.totals.failed} />
                <Stat label="Redriven" value={analytics.totals.redriven} />
                <Stat label="Pending" value={analytics.totals.pending} />
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Stat label="Routed" value={analytics.routing.routed} />
                <Stat label="Suppressed" value={analytics.routing.suppressed} />
                <Stat label="Skipped" value={analytics.routing.skipped} />
                <Stat label="Escalation dests" value={analytics.routing.escalation_destinations} />
              </div>
            </section>
          ) : null}

          <section className={PANEL}>
            <p className="mb-3 text-xs font-bold uppercase tracking-[0.16em] text-[var(--text-muted)]">Destinations</p>
            {destinations.length === 0 ? (
              <p className="text-sm text-[var(--text-muted)]">No destinations configured.</p>
            ) : (
              <div className="grid gap-2.5">
                {destinations.map((d) => (
                  <div key={d.destination_id} className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-black text-[var(--text-strong)]">
                          {d.name || "Destination"}
                          <span className="ml-2 rounded-md border border-[var(--border)] bg-[var(--surface-muted)] px-1.5 py-0.5 text-[11px] font-black uppercase text-[var(--text-subtle)]">{d.kind}</span>
                          {d.is_escalation ? <span className="ml-1.5 text-[11px] font-black uppercase text-[var(--secondary)]">escalation</span> : null}
                          {!d.enabled ? <span className="ml-1.5 text-[11px] font-black uppercase text-[var(--text-subtle)]">disabled</span> : null}
                        </p>
                        <p className="mt-0.5 truncate text-xs text-[var(--text-muted)]">{d.reason}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        {d.cooling_down ? <Badge tone="warn"><Snowflake className="h-3 w-3" />cooling</Badge> : null}
                        <Badge tone={healthTone(d.health)}>{d.health}</Badge>
                      </div>
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[var(--text-muted)]">
                      <span><b className="text-[var(--text-strong)]">{d.delivered}</b> delivered</span>
                      <span><b className="text-[var(--text-strong)]">{d.failed_terminal}</b> failed</span>
                      <span><b className="text-[var(--text-strong)]">{d.pending}</b> pending</span>
                      <span>routed {d.routed} · suppressed {d.suppressed} · skipped {d.skipped}</span>
                      {d.is_escalation ? <span>escalation: {d.escalation_eligible ? "eligible" : "ineligible"}</span> : null}
                      {d.last_error ? <span className="text-[var(--danger)]">last error: {d.last_error}</span> : null}
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-1.5">
                      <button type="button" onClick={() => void onPreview(d.destination_id)}
                        className="rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-1 text-[11px] font-black text-[var(--text-muted)] transition hover:text-[var(--text-strong)]">
                        Why routed?
                      </button>
                      <button type="button" onClick={() => (editing === d.destination_id ? setEditing(null) : startEdit(d))}
                        className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-1 text-[11px] font-black text-[var(--text-muted)] transition hover:text-[var(--text-strong)]">
                        <SlidersHorizontal className="h-3 w-3" /> Tune
                      </button>
                      {d.cooling_down ? (
                        <button type="button" onClick={() => void onClearCooldown(d.destination_id)} disabled={busy === d.destination_id}
                          className="rounded-full border border-transparent bg-[var(--accent)] px-3 py-1 text-[11px] font-black text-[var(--accent-contrast,#fff)] transition hover:opacity-90 disabled:opacity-60">
                          {busy === d.destination_id ? "…" : "Clear cooldown"}
                        </button>
                      ) : null}
                    </div>

                    {editing === d.destination_id ? (
                      <div className="mt-3 grid gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3 sm:grid-cols-2">
                        <label className="text-[11px] font-bold text-[var(--text-muted)]">Min severity
                          <select defaultValue={d.health === "disabled" ? "" : undefined} onChange={(e) => setTuneForm((f) => ({ ...f, min_severity: e.target.value }))}
                            className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-soft)] px-2 py-1 text-xs text-[var(--text-strong)]">
                            <option value="">unchanged</option><option value="warning">warning</option><option value="critical">critical</option>
                          </select>
                        </label>
                        <label className="text-[11px] font-bold text-[var(--text-muted)]">Alert filter (csv)
                          <input onChange={(e) => setTuneForm((f) => ({ ...f, alert_filter: e.target.value }))} placeholder="stuck,retry_exhausted"
                            className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-soft)] px-2 py-1 text-xs text-[var(--text-strong)]" />
                        </label>
                        <label className="text-[11px] font-bold text-[var(--text-muted)]">Suppress seconds
                          <input type="number" onChange={(e) => setTuneForm((f) => ({ ...f, suppress_seconds: Number(e.target.value) }))}
                            className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-soft)] px-2 py-1 text-xs text-[var(--text-strong)]" />
                        </label>
                        <label className="text-[11px] font-bold text-[var(--text-muted)]">Escalate after
                          <input type="number" onChange={(e) => setTuneForm((f) => ({ ...f, escalate_after: Number(e.target.value) }))}
                            className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-soft)] px-2 py-1 text-xs text-[var(--text-strong)]" />
                        </label>
                        <label className="text-[11px] font-bold text-[var(--text-muted)]">Max attempts
                          <input type="number" onChange={(e) => setTuneForm((f) => ({ ...f, max_attempts: Number(e.target.value) }))}
                            className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-soft)] px-2 py-1 text-xs text-[var(--text-strong)]" />
                        </label>
                        <label className="flex items-center gap-2 self-end text-[11px] font-bold text-[var(--text-muted)]">
                          <input type="checkbox" defaultChecked={d.enabled} onChange={(e) => setTuneForm((f) => ({ ...f, enabled: e.target.checked }))} /> Enabled
                        </label>
                        <div className="flex items-center gap-2 sm:col-span-2">
                          <button type="button" onClick={() => void onSaveTuning(d.destination_id)} disabled={busy === d.destination_id}
                            className="rounded-full border border-transparent bg-[var(--accent)] px-3 py-1 text-[11px] font-black text-[var(--accent-contrast,#fff)] transition hover:opacity-90 disabled:opacity-60">
                            {busy === d.destination_id ? "Saving…" : "Save"}
                          </button>
                          <button type="button" onClick={() => setEditing(null)}
                            className="rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-1 text-[11px] font-black text-[var(--text-muted)]">Cancel</button>
                          <span className="text-[11px] text-[var(--text-subtle)]">Secrets are not editable here.</span>
                        </div>
                      </div>
                    ) : null}

                    {preview[d.destination_id] ? (
                      <div className="mt-3 rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3">
                        <p className="mb-1.5 text-[11px] font-black uppercase tracking-wide text-[var(--text-subtle)]">Routing decisions (live alerts)</p>
                        {preview[d.destination_id]!.decisions.length === 0 ? (
                          <p className="text-xs text-[var(--text-muted)]">No current alerts for this destination.</p>
                        ) : (
                          <div className="grid gap-1">
                            {preview[d.destination_id]!.decisions.map((dec, i) => (
                              <p key={i} className="flex items-center gap-2 text-[11px] text-[var(--text-muted)]">
                                <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", dec.decision === "route" ? "bg-[var(--success)]" : dec.decision === "suppress" ? "bg-[var(--warning)]" : "bg-[var(--text-subtle)]")} aria-hidden="true" />
                                <span className="font-semibold text-[var(--text-strong)]">{dec.classification}</span>
                                <span>({dec.severity}, ×{dec.occurrences})</span>
                                <span>→ <b>{dec.decision}</b>: {dec.reason}</span>
                              </p>
                            ))}
                          </div>
                        )}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      ) : null}

      {/* ── Incidents ── */}
      {tab === "incidents" ? (
        <div className="grid gap-5">
          <DemoPanel demo={demo} busy={busy === "demo"} onSeed={() => void onSeedDemo()} onReset={() => void onResetDemo()} />
          <MetricsPanel metrics={metrics} window="24h" />
          <SyncPanel targets={syncTargets} records={syncRecords} onRedrive={(id) => void onRedriveSync(id)}
            onValidate={(id) => void onValidateTarget(id)} onTest={(id) => void onTestTarget(id)}
            busyId={busy} flash={targetFlash} />
          {incidents.length === 0 ? (
            <section className="sarvam-card rounded-[1.5rem] p-8 text-center">
              <CheckCircle2 className="mx-auto mb-2 h-7 w-7 text-[var(--success)]" />
              <p className="text-sm font-black text-[var(--text-strong)]">No incidents.</p>
              <p className="mt-1 text-xs text-[var(--text-muted)]">Recurring alert conditions appear here for acknowledge / silence / recovery.</p>
            </section>
          ) : (
            <>
              {([
                { state: "open", title: "Unresolved", hint: "Active conditions needing attention" },
                { state: "acknowledged", title: "Acknowledged", hint: "Being worked — still active" },
                { state: "silenced", title: "Silenced", hint: "Muted for a bounded window — still exists" },
                { state: "recovered", title: "Recovered", hint: "Condition cleared" },
              ] as const).map(({ state, title, hint }) => {
                const rows = incidents.filter((i) => i.state === state);
                if (rows.length === 0) return null;
                return (
                  <section key={state} className={PANEL}>
                    <div className="mb-3 flex items-baseline gap-2">
                      <p className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--text-muted)]">{title}</p>
                      <span className="text-[11px] text-[var(--text-muted)]">· {hint}</span>
                      <span className="ml-auto text-[11px] font-black text-[var(--text-muted)]">{rows.length}</span>
                    </div>
                    <div className="grid gap-2">
                      {rows.map((inc) => (
                        <IncidentRow key={inc.id} inc={inc} operatorName={operatorName} onChanged={() => void loadIncidents()} />
                      ))}
                    </div>
                  </section>
                );
              })}
            </>
          )}
        </div>
      ) : null}

      {/* ── History ── */}
      {tab === "history" ? (
        <section className={PANEL}>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <p className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--text-muted)]">Delivery history</p>
            <div className="ml-auto flex flex-wrap items-center gap-1.5">
              {["", "failed", "pending", "delivered"].map((s) => (
                <button key={s || "all"} type="button" onClick={() => setFilter((f) => ({ ...f, status: s }))}
                  className={cn("rounded-full px-3 py-1 text-[11px] font-black transition",
                    filter.status === s ? "bg-[var(--accent)] text-[var(--accent-contrast,#fff)]" : "border border-[var(--border)] bg-[var(--surface-muted)] text-[var(--text-muted)] hover:text-[var(--text-strong)]")}>
                  {s || "all"}
                </button>
              ))}
              <select value={filter.destinationId} onChange={(e) => setFilter((f) => ({ ...f, destinationId: e.target.value }))}
                className="rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-2.5 py-1 text-[11px] font-bold text-[var(--text-muted)]">
                <option value="">all destinations</option>
                {destinations.map((d) => <option key={d.destination_id} value={d.destination_id}>{d.name || d.destination_id.slice(0, 8)}</option>)}
              </select>
            </div>
          </div>
          {deliveries.length === 0 ? (
            <p className="text-sm text-[var(--text-muted)]">No delivery attempts match.</p>
          ) : (
            <div className="grid gap-1.5">
              {deliveries.map((d) => (
                <div key={d.id}>
                  <button type="button" onClick={() => void onLineage(d.id)}
                    className="flex w-full flex-wrap items-center justify-between gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface-soft)] px-3.5 py-2.5 text-left transition hover:border-[var(--border-strong)]">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", TONE_DOT[deliveryStatusTone(d.status)])} aria-hidden="true" />
                      <span className="truncate text-xs">
                        <b className="text-[var(--text-strong)]">{d.event_type || d.source_type}</b>
                        <span className="text-[var(--text-muted)]"> · {d.destination_name || d.destination_id.slice(0, 8)}</span>
                        {d.is_redrive ? <span className="text-[var(--secondary)]"> · redrive</span> : null}
                      </span>
                    </div>
                    <span className="flex shrink-0 items-center gap-2 text-[11px] text-[var(--text-muted)]">
                      <span className={TONE_TEXT[deliveryStatusTone(d.status)]}>{d.status}</span>
                      <span>· {d.attempts}×</span>
                      {d.last_error ? <span className="text-[var(--danger)]">· {d.last_error}</span> : null}
                      <span className="text-[var(--text-subtle)]">· {relTime(d.created_at)}</span>
                    </span>
                  </button>
                  {lineage[d.id] ? <LineageChain lineage={lineage[d.id]!} /> : null}
                </div>
              ))}
            </div>
          )}
        </section>
      ) : null}

      {/* ── Recovery (dead-letters) ── */}
      {tab === "recovery" ? (
        <section className={PANEL}>
          <p className="mb-3 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-[var(--text-muted)]">
            <AlertTriangle className="h-3.5 w-3.5 text-[var(--warning)]" /> Dead-letter recovery
          </p>
          {deadLetters.length === 0 ? (
            <p className="inline-flex items-center gap-1.5 text-sm text-[var(--text-muted)]">
              <CheckCircle2 className="h-4 w-4 text-[var(--success)]" /> No failed deliveries needing attention.
            </p>
          ) : (
            <div className="grid gap-2">
              {deadLetters.map((dl) => (
                <div key={dl.id}>
                  <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-3.5">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-[var(--text-strong)]">
                        {dl.event_type || dl.source_type}
                        {dl.severity ? <span className="ml-2 text-[11px] font-bold uppercase text-[var(--text-subtle)]">{dl.severity}</span> : null}
                      </p>
                      <p className="truncate text-xs text-[var(--text-muted)]">
                        {dl.source_id || dl.id} · {dl.attempts} attempts{dl.last_error ? ` · ${dl.last_error}` : ""}{dl.redrive_count ? ` · ${dl.redrive_count} redrive(s)` : ""}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <button type="button" onClick={() => void onLineage(dl.id)}
                        className="rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-2.5 py-1 text-[11px] font-black text-[var(--text-muted)] transition hover:text-[var(--text-strong)]">Lineage</button>
                      <Badge tone={deadLetterTone(dl.dead_letter_state)}>{deadLetterLabel(dl.dead_letter_state)}</Badge>
                      {canRedrive(dl) ? (
                        <button type="button" onClick={() => void onRedrive(dl.id)} disabled={busy === dl.id}
                          className="inline-flex items-center gap-1.5 rounded-full border border-transparent bg-[var(--accent)] px-3 py-1.5 text-xs font-black text-[var(--accent-contrast,#fff)] transition hover:opacity-90 disabled:opacity-60">
                          <Send className="h-3 w-3" /> {busy === dl.id ? "…" : "Redrive"}
                        </button>
                      ) : (
                        <span className="text-[11px] text-[var(--text-subtle)]" title={redriveBlockedReason(dl.dead_letter_state) ?? ""}>
                          {redriveBlockedReason(dl.dead_letter_state)}
                        </span>
                      )}
                    </div>
                  </div>
                  {lineage[dl.id] ? <LineageChain lineage={lineage[dl.id]!} /> : null}
                </div>
              ))}
            </div>
          )}
        </section>
      ) : null}
    </div>
  );
}
