"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  ArrowRight,
  BrainCircuit,
  CheckCircle2,
  Clock,
  Database,
  LockKeyhole,
  Palette,
  RefreshCw,
  Server,
  ShieldCheck,
  Sparkles,
  Wrench,
  XCircle,
} from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";
import { useAiraMode } from "@/components/mode-provider";
import { cn } from "@/lib/utils";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type RuntimeStatus = "checking" | "online" | "offline";

const systemCards = [
  {
    title: "Agents",
    description:
      "Review the specialist modules responsible for planning, execution, validation, reflection, and memory.",
    href: "/agents",
    icon: BrainCircuit,
    label: "Open agent modules",
  },
  {
    title: "Tools",
    description:
      "Inspect the execution capability layer, available actions, tool policies, and risk boundaries.",
    href: "/tools",
    icon: Wrench,
    label: "Open tool layer",
  },
];

const safetyPolicies = [
  "Approval-gated actions pause before modifying the environment.",
  "Git write and push actions show preflight context before execution.",
  "Rejected commit approvals can trigger cleanup of staged changes.",
  "Stale approval processing is recovered safely to prevent duplicate execution.",
];

const executionBoundaries = [
  {
    title: "Research",
    description:
      "Ask questions, retrieve sources, read documents, and produce grounded answers.",
  },
  {
    title: "Execution",
    description:
      "Plan tasks, call tools, validate results, retry failures, and generate traceable outcomes.",
  },
  {
    title: "Approval",
    description:
      "Pause risky operations and ask the user before continuing environment-changing actions.",
  },
];

function getRuntimeLabel(status: RuntimeStatus) {
  if (status === "checking") {
    return "Checking";
  }

  if (status === "online") {
    return "Operational";
  }

  return "Offline";
}

function getRuntimeIcon(status: RuntimeStatus) {
  if (status === "checking") {
    return <Clock className="h-4 w-4" />;
  }

  if (status === "online") {
    return <CheckCircle2 className="h-4 w-4" />;
  }

  return <XCircle className="h-4 w-4" />;
}

function getRuntimeClass(status: RuntimeStatus) {
  if (status === "online") {
    return "status-success";
  }

  if (status === "offline") {
    return "status-danger";
  }

  return "status-warning";
}

function formatDateTime(value?: Date | null) {
  if (!value) {
    return "Not checked yet";
  }

  return value.toLocaleString();
}

function RuntimeHealthCard() {
  const [status, setStatus] = useState<RuntimeStatus>("checking");
  const [lastCheckedAt, setLastCheckedAt] = useState<Date | null>(null);
  const [error, setError] = useState("");

  const checkBackendHealth = useCallback(async () => {
    setStatus("checking");
    setError("");

    try {
      const response = await fetch(`${API_URL}/health`, {
        cache: "no-store",
      });

      setStatus(response.ok ? "online" : "offline");

      if (!response.ok) {
        setError(`Backend returned HTTP ${response.status}.`);
      }
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Backend health check failed.";

      setStatus("offline");
      setError(message);
    } finally {
      setLastCheckedAt(new Date());
    }
  }, []);

  useEffect(() => {
    checkBackendHealth();

    const intervalId = window.setInterval(checkBackendHealth, 15000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [checkBackendHealth]);

  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-center gap-3">
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--accent-soft)] p-3 text-[var(--accent)]">
            <Server className="h-5 w-5" />
          </div>

          <div>
            <h2 className="text-lg font-bold text-[var(--text-strong)]">
              Runtime Health
            </h2>

            <p className="text-sm text-[var(--text-muted)]">
              Shared backend status for AIRA research and AIRA-X execution.
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={checkBackendHealth}
          className="inline-flex w-fit items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-2 text-xs font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </button>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
          <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
            Backend API
          </p>

          <div
            className={cn(
              "mt-2 inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-black",
              getRuntimeClass(status)
            )}
          >
            {getRuntimeIcon(status)}
            {getRuntimeLabel(status)}
          </div>
        </div>

        <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
          <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
            Last Checked
          </p>

          <p className="mt-2 text-sm font-semibold text-[var(--text-strong)]">
            {formatDateTime(lastCheckedAt)}
          </p>
        </div>

        <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
          <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
            Used By
          </p>

          <p className="mt-2 text-sm font-semibold text-[var(--text-strong)]">
            AIRA + AIRA-X
          </p>
        </div>
      </div>

      {error && (
        <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] p-3 text-sm leading-6 text-[var(--danger)]">
          <strong>Runtime issue:</strong> {error}
        </div>
      )}
    </section>
  );
}

function AppearanceCard() {
  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <div className="mb-4 flex items-center gap-3">
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--accent-soft)] p-3 text-[var(--accent)]">
          <Palette className="h-5 w-5" />
        </div>

        <div>
          <h2 className="text-lg font-bold text-[var(--text-strong)]">
            Appearance
          </h2>

          <p className="text-sm text-[var(--text-muted)]">
            Choose how AIRA looks on this device.
          </p>
        </div>
      </div>

      <ThemeToggle />

      <p className="mt-4 text-xs leading-5 text-[var(--text-subtle)]">
        Theme preference is saved locally and supports Light, Dark, and System
        modes.
      </p>
    </section>
  );
}

function AiraResearchSettings() {
  return (
    <>
      <section className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <AppearanceCard />
        <RuntimeHealthCard />
      </section>

      <section className="sarvam-card rounded-[1.5rem] p-5">
        <div className="mb-4 flex items-center gap-3">
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--secondary-soft)] p-3 text-[var(--secondary)]">
            <Database className="h-5 w-5" />
          </div>

          <div>
            <h2 className="text-lg font-bold text-[var(--text-strong)]">
              Research Workspace
            </h2>

            <p className="text-sm text-[var(--text-muted)]">
              AIRA keeps the interface focused on document-backed answers,
              citations, and knowledge retrieval.
            </p>
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-3">
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
            <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
              Ask AIRA
            </p>

            <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">
              Research questions, summaries, and citation-backed responses.
            </p>
          </div>

          <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
            <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
              Knowledge Base
            </p>

            <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">
              Uploaded documents and indexed source material.
            </p>
          </div>

          <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
            <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
              Interactions
            </p>

            <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">
              Previous conversations and research sessions.
            </p>
          </div>
        </div>
      </section>
    </>
  );
}

function AiraXSystemSettings() {
  return (
    <>
      <section className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <AppearanceCard />
        <RuntimeHealthCard />
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        {systemCards.map((card) => {
          const Icon = card.icon;

          return (
            <Link
              key={card.title}
              href={card.href}
              className="sarvam-card group rounded-[1.5rem] p-5 transition hover:-translate-y-0.5"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-3 text-[var(--accent)]">
                  <Icon className="h-5 w-5" />
                </div>

                <ArrowRight className="h-4 w-4 text-[var(--text-subtle)] transition group-hover:translate-x-1 group-hover:text-[var(--accent)]" />
              </div>

              <h2 className="mt-4 text-lg font-bold text-[var(--text-strong)]">
                {card.title}
              </h2>

              <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">
                {card.description}
              </p>

              <div className="mt-4 inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-1.5 text-xs font-bold text-[var(--text-muted)]">
                {card.label}
                <ArrowRight className="h-3.5 w-3.5" />
              </div>
            </Link>
          );
        })}
      </section>

      <section className="grid gap-4 lg:grid-cols-[0.95fr_1.05fr]">
        <div className="sarvam-card rounded-[1.5rem] p-5">
          <div className="mb-4 flex items-center gap-3">
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--secondary-soft)] p-3 text-[var(--secondary)]">
              <ShieldCheck className="h-5 w-5" />
            </div>

            <div>
              <h2 className="text-lg font-bold text-[var(--text-strong)]">
                Safety Policies
              </h2>

              <p className="text-sm text-[var(--text-muted)]">
                Core rules used before risky execution.
              </p>
            </div>
          </div>

          <div className="space-y-3">
            {safetyPolicies.map((policy) => (
              <div
                key={policy}
                className="flex items-start gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-3"
              >
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--success)]" />

                <p className="text-sm leading-6 text-[var(--text-muted)]">
                  {policy}
                </p>
              </div>
            ))}
          </div>
        </div>

        <div className="sarvam-card rounded-[1.5rem] p-5">
          <div className="mb-4 flex items-center gap-3">
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--warning-soft)] p-3 text-[var(--warning)]">
              <LockKeyhole className="h-5 w-5" />
            </div>

            <div>
              <h2 className="text-lg font-bold text-[var(--text-strong)]">
                Execution Boundaries
              </h2>

              <p className="text-sm text-[var(--text-muted)]">
                AIRA-X separates normal research from autonomous execution.
              </p>
            </div>
          </div>

          <div className="grid gap-3">
            {executionBoundaries.map((boundary) => (
              <div
                key={boundary.title}
                className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4"
              >
                <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
                  {boundary.title}
                </p>

                <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">
                  {boundary.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </>
  );
}

export default function SettingsPage() {
  const { mode } = useAiraMode();

  const isAiraMode = mode === "aira";

  return (
    <div className="mx-auto flex min-h-[calc(100vh-64px)] max-w-6xl flex-col gap-6">
      <section className="sarvam-card fade-up relative rounded-[1.75rem] p-6">
        <div className="relative z-10 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="aira-chip mb-3 px-3 py-1.5 text-xs font-bold">
              {isAiraMode ? (
                <Palette className="h-3.5 w-3.5" />
              ) : (
                <Sparkles className="h-3.5 w-3.5" />
              )}
              {isAiraMode ? "AIRA Preferences" : "AIRA-X System Console"}
            </div>

            <h1 className="aira-gradient-text text-3xl font-black tracking-tight">
              {isAiraMode ? "Appearance" : "System Console"}
            </h1>

            <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--text-muted)]">
              {isAiraMode
                ? "Adjust the visual experience and check the shared runtime used by AIRA research features."
                : "Configure appearance, inspect system modules, review execution tools, and understand the safety policies that protect autonomous workflows."}
            </p>
          </div>

          <div
            className={cn(
              "inline-flex w-fit items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-black",
              isAiraMode ? "status-info" : "status-success"
            )}
          >
            <Activity className="h-3.5 w-3.5" />
            {isAiraMode ? "Research mode" : "Execution mode"}
          </div>
        </div>
      </section>

      {isAiraMode ? <AiraResearchSettings /> : <AiraXSystemSettings />}
    </div>
  );
}
