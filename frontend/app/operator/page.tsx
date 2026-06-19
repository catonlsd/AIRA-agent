"use client";

// Operator delivery console — OPERATOR-ONLY. Renders outside the product nav
// (see AppShell) and is never linked from the user UI. Backed entirely by the
// already-gated /operator/* APIs; the service key is entered here and kept in
// sessionStorage. Minimal, curated panels — not a dashboard maze: a delivery
// summary, destination health (+ routing explainability & cooldown recovery), and
// a dead-letter recovery list. Secrets are never shown.

import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  LockKeyhole,
  RefreshCw,
  Send,
  ShieldCheck,
  Snowflake,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  canRedrive,
  clearCooldown,
  clearOperatorKey,
  deadLetterLabel,
  deadLetterTone,
  fetchAnalytics,
  fetchDeadLetters,
  fetchDestinationHealth,
  fetchRoutingPreview,
  getOperatorKey,
  healthTone,
  redriveBlockedReason,
  redriveDelivery,
  runSweep,
  setOperatorKey,
  verifyOperator,
  type DeadLetter,
  type DeliveryAnalytics,
  type DestinationHealth,
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

export default function OperatorConsole() {
  const [status, setStatus] = useState<"checking" | "needs_key" | "ready">("checking");
  const [keyInput, setKeyInput] = useState("");
  const [keyError, setKeyError] = useState("");
  const [analytics, setAnalytics] = useState<DeliveryAnalytics | null>(null);
  const [destinations, setDestinations] = useState<DestinationHealth[]>([]);
  const [deadLetters, setDeadLetters] = useState<DeadLetter[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [flash, setFlash] = useState<string>("");
  const [preview, setPreview] = useState<Record<string, RoutingPreview | null>>({});

  const load = useCallback(async () => {
    const [a, d, dl] = await Promise.all([
      fetchAnalytics(),
      fetchDestinationHealth(),
      fetchDeadLetters(),
    ]);
    setAnalytics(a);
    setDestinations(d);
    setDeadLetters(dl);
  }, []);

  useEffect(() => {
    if (!getOperatorKey()) {
      setStatus("needs_key");
      return;
    }
    verifyOperator().then((ok) => {
      if (ok) {
        setStatus("ready");
        void load();
      } else {
        setStatus("needs_key");
      }
    });
  }, [load]);

  const connect = useCallback(async () => {
    setKeyError("");
    setOperatorKey(keyInput);
    const ok = await verifyOperator();
    if (ok) {
      setStatus("ready");
      void load();
    } else {
      clearOperatorKey();
      setKeyError("That service key was not accepted.");
    }
  }, [keyInput, load]);

  const disconnect = useCallback(() => {
    clearOperatorKey();
    setStatus("needs_key");
    setAnalytics(null);
    setDestinations([]);
    setDeadLetters([]);
  }, []);

  const flashMsg = (msg: string) => {
    setFlash(msg);
    window.setTimeout(() => setFlash(""), 3000);
  };

  const onRedrive = useCallback(async (id: string) => {
    setBusy(id);
    try {
      const res = await redriveDelivery(id);
      flashMsg(res.ok ? "Redrive scheduled." : res.message || "Could not redrive.");
      await load();
    } finally {
      setBusy(null);
    }
  }, [load]);

  const onClearCooldown = useCallback(async (destId: string) => {
    setBusy(destId);
    try {
      if (await clearCooldown(destId)) flashMsg("Cooldown cleared.");
      await load();
    } finally {
      setBusy(null);
    }
  }, [load]);

  const onPreview = useCallback(async (destId: string) => {
    // Toggle: hide if already shown, else fetch the live routing decisions.
    if (preview[destId]) {
      setPreview((p) => ({ ...p, [destId]: null }));
      return;
    }
    const data = await fetchRoutingPreview(destId);
    setPreview((p) => ({ ...p, [destId]: data }));
  }, [preview]);

  const onSweep = useCallback(async () => {
    setBusy("sweep");
    try {
      const r = await runSweep();
      flashMsg(r ? `Swept — routed ${r.routed ?? 0}, suppressed ${r.suppressed ?? 0}, delivered ${r.delivered ?? 0}.` : "Sweep failed.");
      await load();
    } finally {
      setBusy(null);
    }
  }, [load]);

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
            type="password"
            value={keyInput}
            onChange={(e) => setKeyInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && keyInput.trim()) void connect(); }}
            placeholder="Service key"
            className="mt-5 w-full rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-2.5 text-sm text-[var(--text-strong)] outline-none transition focus:border-[var(--border-strong)]"
          />
          {keyError ? <p className="mt-2 text-xs font-semibold text-[var(--danger)]">{keyError}</p> : null}
          <button
            type="button"
            onClick={() => void connect()}
            disabled={!keyInput.trim() || status === "checking"}
            className="mt-4 w-full rounded-full border border-transparent bg-[var(--accent)] px-4 py-2.5 text-sm font-black text-[var(--accent-contrast,#fff)] transition hover:opacity-90 disabled:opacity-60"
          >
            {status === "checking" ? "Checking…" : "Connect"}
          </button>
        </div>
      </div>
    );
  }

  // ── console ──────────────────────────────────────────────────────────────────
  return (
    <div className="mx-auto min-h-screen w-full max-w-5xl px-4 py-6 sm:px-6">
      <header className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--accent-soft)] text-[var(--accent)]">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-lg font-black tracking-tight text-[var(--text-strong)]">Delivery console</h1>
            <p className="text-xs text-[var(--text-muted)]">Operator-only · destination health, routing, and recovery</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {flash ? <span className="text-xs font-semibold text-[var(--success)]">{flash}</span> : null}
          <button type="button" onClick={() => void onSweep()} disabled={busy === "sweep"}
            className="inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-1.5 text-xs font-black text-[var(--text-muted)] transition hover:text-[var(--text-strong)] disabled:opacity-60">
            <Zap className="h-3.5 w-3.5" /> {busy === "sweep" ? "Sweeping…" : "Sweep"}
          </button>
          <button type="button" onClick={() => void load()}
            className="inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-1.5 text-xs font-black text-[var(--text-muted)] transition hover:text-[var(--text-strong)]">
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </button>
          <button type="button" onClick={disconnect}
            className="rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-1.5 text-xs font-black text-[var(--text-muted)] transition hover:text-[var(--danger)]">
            Disconnect
          </button>
        </div>
      </header>

      <div className="grid gap-5">
        {/* Summary */}
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

        {/* Destinations */}
        <section className="sarvam-card rounded-[1.5rem] p-5">
          <p className="mb-3 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">Destinations</p>
          {destinations.length === 0 ? (
            <p className="text-sm text-[var(--text-muted)]">No destinations configured.</p>
          ) : (
            <div className="grid gap-2.5">
              {destinations.map((d) => (
                <div key={d.destination_id} className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-2.5">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-black text-[var(--text-strong)]">
                          {d.name || "Destination"}
                          <span className="ml-2 rounded-md border border-[var(--border)] bg-[var(--surface-muted)] px-1.5 py-0.5 text-[10px] font-black uppercase text-[var(--text-subtle)]">{d.kind}</span>
                          {d.is_escalation ? <span className="ml-1.5 text-[10px] font-black uppercase text-[var(--secondary)]">escalation</span> : null}
                        </p>
                        <p className="mt-0.5 truncate text-xs text-[var(--text-muted)]">{d.reason}</p>
                      </div>
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
                  <div className="mt-3 flex items-center gap-1.5">
                    <button type="button" onClick={() => void onPreview(d.destination_id)}
                      className="rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-1 text-[11px] font-black text-[var(--text-muted)] transition hover:text-[var(--text-strong)]">
                      Why routed?
                    </button>
                    {d.cooling_down ? (
                      <button type="button" onClick={() => void onClearCooldown(d.destination_id)} disabled={busy === d.destination_id}
                        className="rounded-full border border-transparent bg-[var(--accent)] px-3 py-1 text-[11px] font-black text-[var(--accent-contrast,#fff)] transition hover:opacity-90 disabled:opacity-60">
                        {busy === d.destination_id ? "…" : "Clear cooldown"}
                      </button>
                    ) : null}
                  </div>
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

        {/* Dead-letters */}
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
                <div key={dl.id} className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-3.5">
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
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
