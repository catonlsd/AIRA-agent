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
  AlertTriangle,
  BellOff,
  BellRing,
  Check,
  CheckCircle2,
  Flame,
  GitBranch,
  History,
  LayoutGrid,
  LockKeyhole,
  RefreshCw,
  Send,
  ShieldCheck,
  SlidersHorizontal,
  Snowflake,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  ackIncident,
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
  fetchIncidents,
  fetchLineage,
  fetchRoutingPreview,
  getOperatorKey,
  healthTone,
  incidentTone,
  patchDestination,
  redriveBlockedReason,
  redriveDelivery,
  runSweep,
  setOperatorKey,
  silenceIncident,
  unsilenceIncident,
  verifyOperator,
  type DeadLetter,
  type Delivery,
  type DeliveryAnalytics,
  type DeliveryLineage,
  type DestinationHealth,
  type DestinationTuning,
  type Incident,
  type RoutingPreview,
  type Tone,
} from "@/lib/operator";

const TONE_DOT: Record<Tone, string> = {
  good: "bg-[var(--success)]",
  warn: "bg-[var(--warning)]",
  bad: "bg-[var(--danger)]",
  muted: "bg-[var(--text-subtle)]",
};
const TONE_TEXT: Record<Tone, string> = {
  good: "text-[var(--success)]",
  warn: "text-[var(--warning)]",
  bad: "text-[var(--danger)]",
  muted: "text-[var(--text-subtle)]",
};

function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-2.5 py-0.5 text-[11px] font-black uppercase tracking-wide", TONE_TEXT[tone])}>
      <span className={cn("h-1.5 w-1.5 rounded-full", TONE_DOT[tone])} aria-hidden="true" />
      {children}
    </span>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-2">
      <p className="text-lg font-black text-[var(--text-strong)]">{value}</p>
      <p className="text-[11px] font-bold uppercase tracking-wide text-[var(--text-subtle)]">{label}</p>
    </div>
  );
}

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

// ── incident row (Incidents tab) ─────────────────────────────────────────────
function IncidentRow({ inc, busy, onAck, onSilence, onUnsilence }: {
  inc: Incident; busy: boolean;
  onAck: () => void; onSilence: () => void; onUnsilence: () => void;
}) {
  const silenceLeft = inc.state === "silenced" ? relTimeUntil(inc.silenced_until) : "";
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
        <span>source: {inc.source}</span>
        {inc.acknowledged_at ? <span>acknowledged {relTime(inc.acknowledged_at)}</span> : null}
        {inc.state === "silenced" && silenceLeft ? <span className="font-semibold text-[var(--text-strong)]">silenced · {silenceLeft} left</span> : null}
        {inc.state === "recovered" && inc.recovered_at ? <span className="font-semibold text-[var(--success)]">recovered {relTime(inc.recovered_at)}</span> : null}
      </div>
      {inc.note ? <p className="mt-2 rounded-lg border border-[var(--border)] bg-[var(--surface-muted)] px-2.5 py-1.5 text-[11px] text-[var(--text-muted)]">📝 {inc.note}</p> : null}
      {inc.state !== "recovered" ? (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {!inc.acknowledged ? (
            <button type="button" disabled={busy} onClick={onAck}
              className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-1 text-[11px] font-black text-[var(--text-strong)] transition hover:border-[var(--border-strong)] disabled:opacity-50">
              <Check className="h-3 w-3" /> Acknowledge
            </button>
          ) : null}
          {inc.state === "silenced" ? (
            <button type="button" disabled={busy} onClick={onUnsilence}
              className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-1 text-[11px] font-black text-[var(--text-strong)] transition hover:border-[var(--border-strong)] disabled:opacity-50">
              <BellRing className="h-3 w-3" /> Unsilence
            </button>
          ) : (
            <button type="button" disabled={busy} onClick={onSilence}
              className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-1 text-[11px] font-black text-[var(--text-strong)] transition hover:border-[var(--border-strong)] disabled:opacity-50">
              <BellOff className="h-3 w-3" /> Silence
            </button>
          )}
        </div>
      ) : null}
    </div>
  );
}

// ── delivery-lineage drill-down (shared by History + Recovery) ────────────────
function LineageChain({ lineage }: { lineage: DeliveryLineage }) {
  return (
    <div className="mt-2 rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3">
      <p className="mb-1.5 flex items-center gap-1.5 text-[10px] font-black uppercase tracking-wide text-[var(--text-subtle)]">
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
  const [keyError, setKeyError] = useState("");
  const [tab, setTab] = useState<Tab>("overview");
  const [incidents, setIncidents] = useState<Incident[]>([]);
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

  const loadIncidents = useCallback(async () => { setIncidents(await fetchIncidents()); }, []);

  useEffect(() => {
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
    if (await verifyOperator()) { setStatus("ready"); void load(); }
    else { clearOperatorKey(); setKeyError("That service key was not accepted."); }
  }, [keyInput, load]);

  const disconnect = useCallback(() => {
    clearOperatorKey();
    setStatus("needs_key");
    setAnalytics(null); setDestinations([]); setDeadLetters([]); setDeliveries([]);
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

  const startEdit = useCallback((d: DestinationHealth) => {
    setEditing(d.destination_id);
    setTuneForm({}); // tuning fields default to "unchanged" — only edited fields are sent
  }, []);

  const onAck = useCallback(async (id: string) => {
    setBusy(id);
    try { if (await ackIncident(id)) flashMsg("Acknowledged."); await loadIncidents(); }
    finally { setBusy(null); }
  }, [loadIncidents]);

  const onSilence = useCallback(async (id: string) => {
    setBusy(id);
    try { if (await silenceIncident(id)) flashMsg("Silenced (bounded)."); await loadIncidents(); }
    finally { setBusy(null); }
  }, [loadIncidents]);

  const onUnsilence = useCallback(async (id: string) => {
    setBusy(id);
    try { if (await unsilenceIncident(id)) flashMsg("Unsilenced."); await loadIncidents(); }
    finally { setBusy(null); }
  }, [loadIncidents]);

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
            <p className="text-xs text-[var(--text-muted)]">Operator-only · health, history, tuning, and recovery</p>
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
            {t.id === "recovery" && deadLetters.length > 0 ? <span className="ml-0.5 rounded-full bg-[var(--danger)] px-1.5 text-[10px] text-white">{deadLetters.length}</span> : null}
            {t.id === "incidents" && t.badge ? <span className="ml-0.5 rounded-full bg-[var(--danger)] px-1.5 text-[10px] text-white">{t.badge}</span> : null}
          </button>
        ))}
      </div>

      {/* ── Overview ── */}
      {tab === "overview" ? (
        <div className="grid gap-5">
          {analytics ? (
            <section className="sarvam-card rounded-[1.5rem] p-5">
              <p className="mb-3 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">Delivery summary · last {analytics.window_minutes}m</p>
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

          <section className="sarvam-card rounded-[1.5rem] p-5">
            <p className="mb-3 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">Destinations</p>
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
                          <span className="ml-2 rounded-md border border-[var(--border)] bg-[var(--surface-muted)] px-1.5 py-0.5 text-[10px] font-black uppercase text-[var(--text-subtle)]">{d.kind}</span>
                          {d.is_escalation ? <span className="ml-1.5 text-[10px] font-black uppercase text-[var(--secondary)]">escalation</span> : null}
                          {!d.enabled ? <span className="ml-1.5 text-[10px] font-black uppercase text-[var(--text-subtle)]">disabled</span> : null}
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
                          <span className="text-[10px] text-[var(--text-subtle)]">Secrets are not editable here.</span>
                        </div>
                      </div>
                    ) : null}

                    {preview[d.destination_id] ? (
                      <div className="mt-3 rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3">
                        <p className="mb-1.5 text-[10px] font-black uppercase tracking-wide text-[var(--text-subtle)]">Routing decisions (live alerts)</p>
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
                  <section key={state} className="sarvam-card rounded-[1.5rem] p-5">
                    <div className="mb-3 flex items-baseline gap-2">
                      <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">{title}</p>
                      <span className="text-[11px] text-[var(--text-muted)]">· {hint}</span>
                      <span className="ml-auto text-[11px] font-black text-[var(--text-muted)]">{rows.length}</span>
                    </div>
                    <div className="grid gap-2">
                      {rows.map((inc) => (
                        <IncidentRow key={inc.id} inc={inc} busy={busy === inc.id}
                          onAck={() => void onAck(inc.id)} onSilence={() => void onSilence(inc.id)} onUnsilence={() => void onUnsilence(inc.id)} />
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
        <section className="sarvam-card rounded-[1.5rem] p-5">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">Delivery history</p>
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
        <section className="sarvam-card rounded-[1.5rem] p-5">
          <p className="mb-3 flex items-center gap-2 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
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
