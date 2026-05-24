"use client";

import { useRouter } from "next/navigation";
import {
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Database,
  GitBranch,
  LockKeyhole,
  MessageSquare,
  Sparkles,
  UploadCloud,
  Workflow,
  Zap,
} from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";
import {
  useAiraMode,
  type AiraOperatingMode,
} from "@/components/mode-provider";
import { cn } from "@/lib/utils";

const researchFeatures = [
  "Document-grounded answers",
  "PDF and source ingestion",
  "Citation-backed responses",
  "Knowledge base retrieval",
];

const executionFeatures = [
  "Autonomous workflow planning",
  "Tool and agent orchestration",
  "Approval-gated risky actions",
  "Execution logs and validation",
];

function FeaturePill({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-2 text-xs font-bold text-[var(--text-muted)]">
      <CheckCircle2 className="h-3.5 w-3.5 text-[var(--success)]" />
      {children}
    </div>
  );
}

function ModeCard({
  mode,
  title,
  eyebrow,
  description,
  icon,
  features,
  cta,
  active,
  onEnter,
}: {
  mode: AiraOperatingMode;
  title: string;
  eyebrow: string;
  description: string;
  icon: React.ReactNode;
  features: string[];
  cta: string;
  active: boolean;
  onEnter: (mode: AiraOperatingMode) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onEnter(mode)}
      className={cn(
        "group relative overflow-hidden rounded-[2rem] border p-6 text-left shadow-[var(--shadow-card)] transition-all duration-300",
        "hover:-translate-y-1 hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:shadow-[var(--shadow-hover)]",
        active
          ? "border-[var(--border-strong)] bg-[var(--accent-soft)]"
          : "border-[var(--border)] bg-[var(--surface)]"
      )}
    >
      <div className="pointer-events-none absolute -right-20 -top-20 h-48 w-48 rounded-full bg-[var(--accent-glow)] blur-3xl transition duration-300 group-hover:scale-125" />

      <div className="relative z-10">
        <div className="mb-6 flex items-start">
          <div
            className={cn(
              "flex h-14 w-14 items-center justify-center rounded-2xl border shadow-[var(--shadow-soft)]",
              active
                ? "border-[var(--border-strong)] bg-[var(--accent)] text-[var(--accent-foreground)]"
                : "border-[var(--border)] bg-[var(--surface-soft)] text-[var(--accent)]"
            )}
          >
            {icon}
          </div>
        </div>

        <p className="text-xs font-black uppercase tracking-[0.22em] text-[var(--accent)]">
          {eyebrow}
        </p>

        <h2 className="mt-3 text-3xl font-black tracking-tight text-[var(--text-strong)]">
          {title}
        </h2>

        <p className="mt-3 text-sm leading-7 text-[var(--text-muted)]">
          {description}
        </p>

        <div className="mt-6 grid gap-2">
          {features.map((feature) => (
            <FeaturePill key={feature}>{feature}</FeaturePill>
          ))}
        </div>

        <div className="mt-7 inline-flex items-center gap-2 rounded-full bg-[var(--accent)] px-5 py-3 text-sm font-black text-[var(--accent-foreground)] shadow-[var(--shadow-soft)] transition group-hover:gap-3">
          {cta}
          <ArrowRight className="h-4 w-4" />
        </div>
      </div>
    </button>
  );
}

export default function LandingPage() {
  const router = useRouter();
  const { mode, setMode } = useAiraMode();

  function enterMode(nextMode: AiraOperatingMode) {
    setMode(nextMode);
    router.push(nextMode === "aira" ? "/chat" : "/overview");
  }

  return (
    <main className="relative min-h-screen overflow-hidden px-4 py-6 sm:px-6 lg:px-8">
      <div className="pointer-events-none absolute -left-32 top-10 h-72 w-72 rounded-full bg-[var(--accent-glow)] blur-3xl" />
      <div className="pointer-events-none absolute -right-32 bottom-10 h-80 w-80 rounded-full bg-[var(--secondary-glow)] blur-3xl" />

      <div className="relative z-10 mx-auto flex min-h-[calc(100vh-48px)] max-w-7xl flex-col">
        <header className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-[var(--border-strong)] bg-[var(--accent-soft)] text-[var(--accent)] shadow-[0_0_30px_var(--accent-glow)]">
              <Sparkles className="h-5 w-5" />
            </div>

            <div>
              <h1 className="text-xl font-black tracking-tight text-[var(--text-strong)]">
                AIRA
                <span className="text-[var(--accent)]"> / </span>
                AIRA-X
              </h1>

              <p className="text-xs font-black uppercase tracking-[0.22em] text-[var(--text-subtle)]">
                Research and execution platform
              </p>
            </div>
          </div>

          <ThemeToggle />
        </header>

        <section className="grid flex-1 items-center gap-8 py-12 lg:grid-cols-[0.95fr_1.05fr] lg:py-16">
          <div>
            <div className="aira-chip mb-5 px-3 py-1.5 text-xs font-bold">
              <Zap className="h-3.5 w-3.5" />
              Choose your operating mode
            </div>

            <h2 className="max-w-3xl text-5xl font-black tracking-tight text-[var(--text-strong)] sm:text-6xl">
              Research when you need answers.
              <span className="aira-gradient-text block">
                Execute when you need outcomes.
              </span>
            </h2>

            <p className="mt-6 max-w-2xl text-base leading-8 text-[var(--text-muted)]">
              AIRA is the grounded research layer. AIRA-X extends it into an
              autonomous execution layer with planning, tools, approvals,
              validation, and traceable workflow logs.
            </p>

            <div className="mt-8 grid gap-3 sm:grid-cols-2">
              <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
                <div className="mb-3 flex items-center gap-2 text-sm font-black text-[var(--text-strong)]">
                  <MessageSquare className="h-4 w-4 text-[var(--accent)]" />
                  AIRA for research
                </div>

                <p className="text-sm leading-6 text-[var(--text-muted)]">
                  Ask questions, upload documents, retrieve citations, and build
                  a reliable knowledge base.
                </p>
              </div>

              <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
                <div className="mb-3 flex items-center gap-2 text-sm font-black text-[var(--text-strong)]">
                  <Workflow className="h-4 w-4 text-[var(--accent)]" />
                  AIRA-X for execution
                </div>

                <p className="text-sm leading-6 text-[var(--text-muted)]">
                  Convert goals into workflows, inspect approvals, and track
                  every step from plan to result.
                </p>
              </div>
            </div>
          </div>

          <div className="grid gap-5">
            <ModeCard
              mode="aira"
              title="AIRA"
              eyebrow="Research Assistant"
              description="A focused research workspace for grounded answers, document ingestion, citations, and knowledge retrieval."
              icon={<BookOpen className="h-6 w-6" />}
              features={researchFeatures}
              cta="Enter AIRA"
              active={mode === "aira"}
              onEnter={enterMode}
            />

            <ModeCard
              mode="aira-x"
              title="AIRA-X"
              eyebrow="Execution Platform"
              description="A command center for autonomous workflows, tool usage, approval-gated actions, validation, and audit-ready traces."
              icon={<Zap className="h-6 w-6" />}
              features={executionFeatures}
              cta="Enter AIRA-X"
              active={mode === "aira-x"}
              onEnter={enterMode}
            />
          </div>
        </section>

        <section className="mb-6 grid gap-3 md:grid-cols-4">
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
            <UploadCloud className="mb-3 h-4 w-4 text-[var(--accent)]" />
            <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
              Intake
            </p>
            <p className="mt-1 text-sm font-bold text-[var(--text-strong)]">
              Upload documents
            </p>
          </div>

          <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
            <Database className="mb-3 h-4 w-4 text-[var(--accent)]" />
            <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
              Retrieve
            </p>
            <p className="mt-1 text-sm font-bold text-[var(--text-strong)]">
              Ground answers
            </p>
          </div>

          <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
            <GitBranch className="mb-3 h-4 w-4 text-[var(--accent)]" />
            <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
              Execute
            </p>
            <p className="mt-1 text-sm font-bold text-[var(--text-strong)]">
              Run workflows
            </p>
          </div>

          <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
            <LockKeyhole className="mb-3 h-4 w-4 text-[var(--accent)]" />
            <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
              Govern
            </p>
            <p className="mt-1 text-sm font-bold text-[var(--text-strong)]">
              Manage approvals
            </p>
          </div>
        </section>
      </div>
    </main>
  );
}