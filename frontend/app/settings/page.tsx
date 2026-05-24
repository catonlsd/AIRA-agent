"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  Activity,
  ArrowRight,
  BrainCircuit,
  CheckCircle2,
  Clock,
  Database,
  FileText,
  Layers3,
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
type ModuleTone = "accent" | "secondary" | "success" | "warning" | "danger";

const systemCards = [
  {
    title: "Agents",
    description:
      "Planner, executor, validator, reflection, memory, and approval-aware specialist modules.",
    href: "/agents",
    icon: BrainCircuit,
    label: "Inspect agents",
    tone: "secondary" as const,
  },
  {
    title: "Tools",
    description:
      "Execution capabilities, action policies, tool boundaries, and risk-aware operations.",
    href: "/tools",
    icon: Wrench,
    label: "Inspect tools",
    tone: "accent" as const,
  },
];

const safetyPolicies = [
  {
    title: "Approval Gates",
    description:
      "Environment-changing actions pause until the user explicitly approves or rejects them.",
  },
  {
    title: "Git Preflight",
    description:
      "Git write and push actions expose branch, diff, commit, and remote context before execution.",
  },
  {
    title: "Safe Rejection",
    description:
      "Rejected commit approvals can trigger cleanup so staged changes are not left behind.",
  },
  {
    title: "Stale Recovery",
    description:
      "Long-running approval processing is recovered safely to prevent duplicate execution.",
  },
];

const executionBoundaries = [
  {
    title: "Research Layer",
    description:
      "Answers questions, retrieves documents, reads sources, summarizes content, and cites evidence.",
    icon: FileText,
  },
  {
    title: "Execution Layer",
    description:
      "Turns user goals into workflows, calls tools, validates results, and records traceable outputs.",
    icon: Activity,
  },
  {
    title: "Governance Layer",
    description:
      "Separates safe actions from risky operations and routes sensitive execution through approvals.",
    icon: LockKeyhole,
  },
];

const researchModules = [
  {
    title: "Ask AIRA",
    description:
      "Question answering, summaries, citation-backed responses, and document-first research.",
    icon: Sparkles,
  },
  {
    title: "Knowledge Base",
    description:
      "Uploaded PDFs, indexed documents, retrieved chunks, and source-grounded context.",
    icon: Database,
  },
  {
    title: "Interactions",
    description:
      "Research sessions, question history, and previous assistant responses.",
    icon: Layers3,
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

function getToneSurface(tone: ModuleTone) {
  if (tone === "secondary") {
    return "bg-[var(--secondary-soft)] text-[var(--secondary)]";
  }

  if (tone === "success") {
    return "bg-[var(--success-soft)] text-[var(--success)]";
  }

  if (tone === "warning") {
    return "bg-[var(--warning-soft)] text-[var(--warning)]";
  }

  if (tone === "danger") {
    return "bg-[var(--danger-soft)] text-[var(--danger)]";
  }

  return "bg-[var(--accent-soft)] text-[var(--accent)]";
}

function SectionHeading({
  icon,
  title,
  description,
  action,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="flex items-start gap-3">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--accent-soft)] text-[var(--accent)]">
          {icon}
        </div>

        <div>
          <h2 className="text-lg font-black tracking-tight text-[var(--text-strong)]">
            {title}
          </h2>

          <p className="mt-1 max-w-2xl text-sm leading-6 text-[var(--text-muted)]">
            {description}
          </p>
        </div>
      </div>

      {action}
    </div>
  );
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
      <SectionHeading
        icon={<Server className="h-5 w-5" />}
        title="Runtime Health"
        description="Shared backend availability for AIRA research and AIRA-X execution."
        action={
          <button
            type="button"
            onClick={checkBackendHealth}
            className="inline-flex w-fit items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-2 text-xs font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
          >
            <RefreshCw
              className={cn(
                "h-3.5 w-3.5",
                status === "checking" && "animate-spin"
              )}
            />
            Refresh
          </button>
        }
      />

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
        <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] p-4 text-sm leading-6 text-[var(--danger)]">
          <strong>Runtime issue:</strong> {error}
        </div>
      )}
    </section>
  );
}

function AppearanceCard() {
  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <SectionHeading
        icon={<Palette className="h-5 w-5" />}
        title="Appearance"
        description="Switch between light, dark, and system theme without compromising the interface polish."
      />

      <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
        <ThemeToggle />

        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-muted)] p-3">
            <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
              Light
            </p>

            <p className="mt-1 text-xs leading-5 text-[var(--text-muted)]">
              Clean research workspace with soft surfaces.
            </p>
          </div>

          <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-muted)] p-3">
            <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
              Dark
            </p>

            <p className="mt-1 text-xs leading-5 text-[var(--text-muted)]">
              Operator-console feel with readable contrast.
            </p>
          </div>

          <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-muted)] p-3">
            <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
              System
            </p>

            <p className="mt-1 text-xs leading-5 text-[var(--text-muted)]">
              Follows the device theme preference.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

function ModuleLinkCard({
  title,
  description,
  href,
  icon,
  label,
  tone = "accent",
}: {
  title: string;
  description: string;
  href: string;
  icon: ReactNode;
  label: string;
  tone?: ModuleTone;
}) {
  return (
    <Link
      href={href}
      className="sarvam-card group rounded-[1.5rem] p-5 transition hover:-translate-y-0.5"
    >
      <div className="mb-5 flex items-start justify-between gap-4">
        <div
          className={cn(
            "flex h-12 w-12 items-center justify-center rounded-2xl border border-[var(--border)]",
            getToneSurface(tone)
          )}
        >
          {icon}
        </div>

        <ArrowRight className="h-4 w-4 text-[var(--text-subtle)] transition group-hover:translate-x-1 group-hover:text-[var(--accent)]" />
      </div>

      <h2 className="text-lg font-black text-[var(--text-strong)]">{title}</h2>

      <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">
        {description}
      </p>

      <div className="mt-5 inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-1.5 text-xs font-black text-[var(--text-muted)] transition group-hover:border-[var(--border-strong)] group-hover:text-[var(--text-strong)]">
        {label}
        <ArrowRight className="h-3.5 w-3.5" />
      </div>
    </Link>
  );
}

function ResearchWorkspaceSection() {
  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <SectionHeading
        icon={<Database className="h-5 w-5" />}
        title="Research Workspace"
        description="AIRA keeps the interface focused on document-backed answers, citations, and knowledge retrieval."
      />

      <div className="grid gap-3 md:grid-cols-3">
        {researchModules.map((module) => {
          const Icon = module.icon;

          return (
            <div
              key={module.title}
              className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4"
            >
              <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--accent-soft)] text-[var(--accent)]">
                <Icon className="h-4 w-4" />
              </div>

              <p className="text-sm font-black text-[var(--text-strong)]">
                {module.title}
              </p>

              <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">
                {module.description}
              </p>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function SafetyPoliciesSection() {
  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <SectionHeading
        icon={<ShieldCheck className="h-5 w-5" />}
        title="Safety Policies"
        description="Rules that keep autonomous execution inspectable, reversible, and human-controlled."
      />

      <div className="grid gap-3">
        {safetyPolicies.map((policy) => (
          <div
            key={policy.title}
            className="flex items-start gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4"
          >
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--success)]" />

            <div>
              <p className="text-sm font-black text-[var(--text-strong)]">
                {policy.title}
              </p>

              <p className="mt-1 text-sm leading-6 text-[var(--text-muted)]">
                {policy.description}
              </p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ExecutionBoundariesSection() {
  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <SectionHeading
        icon={<LockKeyhole className="h-5 w-5" />}
        title="Execution Boundaries"
        description="AIRA-X separates research, execution, and governance so risky actions never feel hidden."
      />

      <div className="grid gap-3">
        {executionBoundaries.map((boundary) => {
          const Icon = boundary.icon;

          return (
            <div
              key={boundary.title}
              className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4"
            >
              <div className="mb-3 flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--warning-soft)] text-[var(--warning)]">
                  <Icon className="h-4 w-4" />
                </div>

                <p className="text-sm font-black text-[var(--text-strong)]">
                  {boundary.title}
                </p>
              </div>

              <p className="text-sm leading-6 text-[var(--text-muted)]">
                {boundary.description}
              </p>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function AiraResearchSettings() {
  return (
    <>
      <section className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
        <AppearanceCard />
        <RuntimeHealthCard />
      </section>

      <ResearchWorkspaceSection />
    </>
  );
}

function AiraXSystemSettings() {
  return (
    <>
      <section className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
        <AppearanceCard />
        <RuntimeHealthCard />
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        {systemCards.map((card) => {
          const Icon = card.icon;

          return (
            <ModuleLinkCard
              key={card.title}
              title={card.title}
              description={card.description}
              href={card.href}
              icon={<Icon className="h-5 w-5" />}
              label={card.label}
              tone={card.tone}
            />
          );
        })}
      </section>

      <section className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
        <SafetyPoliciesSection />
        <ExecutionBoundariesSection />
      </section>
    </>
  );
}

export default function SettingsPage() {
  const { mode } = useAiraMode();

  const isAiraMode = mode === "aira";

  return (
    <div className="mx-auto flex min-h-[calc(100vh-64px)] max-w-7xl flex-col gap-6">
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-6">
        <div className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-[var(--accent-glow)] blur-3xl" />
        <div className="pointer-events-none absolute -bottom-28 left-1/3 h-64 w-64 rounded-full bg-[var(--secondary-glow)] blur-3xl" />

        <div className="relative z-10 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="aira-chip mb-4 px-3 py-1.5 text-xs font-bold">
              {isAiraMode ? (
                <Palette className="h-3.5 w-3.5" />
              ) : (
                <Sparkles className="h-3.5 w-3.5" />
              )}
              {isAiraMode ? "AIRA Preferences" : "AIRA-X System Console"}
            </div>

            <h1 className="aira-gradient-text text-4xl font-black tracking-tight">
              {isAiraMode ? "Appearance" : "System Console"}
            </h1>

            <p className="mt-3 max-w-3xl text-sm leading-7 text-[var(--text-muted)]">
              {isAiraMode
                ? "Tune the visual experience and check the shared runtime used by AIRA research features."
                : "Inspect the execution platform: runtime health, agent modules, tool boundaries, safety policies, and approval-aware execution rules."}
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
