"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import Link from "next/link";
import {
  ArrowRight,
  Bot,
  CheckCircle2,
  Clock,
  History,
  MessageSquare,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  User,
} from "lucide-react";
import { apiDelete, apiGet } from "@/lib/api";
import { cn } from "@/lib/utils";

type Message = {
  id: number;
  role: string;
  content: string;
  created_at: string;
};

type RoleTone = "user" | "assistant" | "system" | "default";

function formatNumber(value: number) {
  return value.toLocaleString();
}

function formatDateTime(value?: string | null) {
  if (!value) {
    return "Not recorded";
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString();
}

function getTimestampMs(value?: string | null) {
  if (!value) {
    return 0;
  }

  const timestamp = new Date(value).getTime();

  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function getRoleTone(role: string): RoleTone {
  const normalizedRole = role.toLowerCase();

  if (normalizedRole === "user" || normalizedRole === "human") {
    return "user";
  }

  if (normalizedRole === "assistant" || normalizedRole === "ai") {
    return "assistant";
  }

  if (normalizedRole === "system") {
    return "system";
  }

  return "default";
}

function getRoleIcon(role: string) {
  const tone = getRoleTone(role);

  if (tone === "user") {
    return <User className="h-4 w-4" />;
  }

  if (tone === "assistant") {
    return <Bot className="h-4 w-4" />;
  }

  if (tone === "system") {
    return <Sparkles className="h-4 w-4" />;
  }

  return <MessageSquare className="h-4 w-4" />;
}

function getRoleClass(role: string) {
  const tone = getRoleTone(role);

  if (tone === "user") {
    return "bg-[var(--accent-soft)] text-[var(--accent)]";
  }

  if (tone === "assistant") {
    return "bg-[var(--secondary-soft)] text-[var(--secondary)]";
  }

  if (tone === "system") {
    return "bg-[var(--warning-soft)] text-[var(--warning)]";
  }

  return "bg-[var(--surface-muted)] text-[var(--text-muted)]";
}

function getRoleLabel(role: string) {
  if (!role) {
    return "Message";
  }

  return role
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function getPreviewText(content: string, maxLength = 180) {
  const cleanContent = content.replace(/\s+/g, " ").trim();

  if (cleanContent.length <= maxLength) {
    return cleanContent;
  }

  return `${cleanContent.slice(0, maxLength).trim()}...`;
}

function getMessageSearchText(message: Message) {
  return [
    message.id,
    message.role,
    message.content,
    message.created_at,
    formatDateTime(message.created_at),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function MetricCard({
  label,
  value,
  description,
  icon,
  tone = "accent",
}: {
  label: string;
  value: ReactNode;
  description: string;
  icon: ReactNode;
  tone?: "accent" | "secondary" | "success" | "warning";
}) {
  const toneClass =
    tone === "secondary"
      ? "bg-[var(--secondary-soft)] text-[var(--secondary)]"
      : tone === "success"
        ? "bg-[var(--success-soft)] text-[var(--success)]"
        : tone === "warning"
          ? "bg-[var(--warning-soft)] text-[var(--warning)]"
          : "bg-[var(--accent-soft)] text-[var(--accent)]";

  return (
    <div className="sarvam-card rounded-[1.35rem] p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <p className="text-xs font-black uppercase tracking-[0.16em] text-[var(--text-subtle)]">
          {label}
        </p>

        <div
          className={cn(
            "flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)]",
            toneClass
          )}
        >
          {icon}
        </div>
      </div>

      <h2 className="text-3xl font-black text-[var(--text-strong)]">
        {value}
      </h2>

      <p className="mt-2 text-xs leading-5 text-[var(--text-muted)]">
        {description}
      </p>
    </div>
  );
}

function SectionHeader({
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
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--accent-soft)] text-[var(--accent)]">
          {icon}
        </div>

        <div>
          <h2 className="text-lg font-black text-[var(--text-strong)]">
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

function MessageCard({ message }: { message: Message }) {
  const roleClass = getRoleClass(message.role);
  const previewText = getPreviewText(message.content);
  const hasLongContent =
    message.content.replace(/\s+/g, " ").trim().length > 180;

  return (
    <article className="sarvam-card rounded-[1.5rem] p-5 transition hover:-translate-y-0.5">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div
            className={cn(
              "flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-[var(--border)]",
              roleClass
            )}
          >
            {getRoleIcon(message.role)}
          </div>

          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={cn(
                  "inline-flex items-center gap-2 rounded-full border border-[var(--border)] px-3 py-1 text-[11px] font-black uppercase tracking-wide",
                  roleClass
                )}
              >
                {getRoleLabel(message.role)}
              </span>

              <span className="inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-1 text-[11px] font-bold text-[var(--text-muted)]">
                <Clock className="h-3.5 w-3.5" />
                {formatDateTime(message.created_at)}
              </span>
            </div>

            <p className="mt-2 font-mono text-[11px] text-[var(--text-subtle)]">
              Message ID: {message.id}
            </p>
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
        <p className="mb-2 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
          Preview
        </p>

        <p className="text-sm leading-7 text-[var(--text)]">{previewText}</p>
      </div>

      {hasLongContent && (
        <details className="mt-3 rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
          <summary className="cursor-pointer text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
            View full message
          </summary>

          <div className="mt-3 whitespace-pre-wrap text-sm leading-7 text-[var(--text)]">
            {message.content}
          </div>
        </details>
      )}
    </article>
  );
}

export default function HistoryPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [clearing, setClearing] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [status, setStatus] = useState("");

  const loadMessages = useCallback(
    async (options?: { showLoading?: boolean }) => {
      const showLoading = options?.showLoading ?? true;

      try {
        if (showLoading) {
          setLoading(true);
        }

        const data = await apiGet<Message[]>("/history");

        setMessages(data);
        setStatus("");
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : "Failed to load interactions.";

        setStatus(message);
      } finally {
        if (showLoading) {
          setLoading(false);
        }
      }
    },
    []
  );

  useEffect(() => {
    loadMessages();
  }, [loadMessages]);

  const userMessageCount = useMemo(
    () =>
      messages.filter((message) => getRoleTone(message.role) === "user")
        .length,
    [messages]
  );

  const assistantMessageCount = useMemo(
    () =>
      messages.filter((message) => getRoleTone(message.role) === "assistant")
        .length,
    [messages]
  );

  const latestMessageAt = useMemo(() => {
    if (messages.length === 0) {
      return null;
    }

    const latestMessage = messages
      .slice()
      .sort(
        (firstMessage, secondMessage) =>
          getTimestampMs(secondMessage.created_at) -
          getTimestampMs(firstMessage.created_at)
      )[0];

    return latestMessage?.created_at || null;
  }, [messages]);

  const filteredMessages = useMemo(() => {
    const normalizedSearch = searchQuery.trim().toLowerCase();

    const sortedMessages = messages
      .slice()
      .sort(
        (firstMessage, secondMessage) =>
          getTimestampMs(secondMessage.created_at) -
          getTimestampMs(firstMessage.created_at)
      );

    if (!normalizedSearch) {
      return sortedMessages;
    }

    return sortedMessages.filter((message) =>
      getMessageSearchText(message).includes(normalizedSearch)
    );
  }, [messages, searchQuery]);

  async function clearHistory() {
    const confirmed = window.confirm(
      "Clear all interaction history?\n\nThis removes stored conversation turns from local history."
    );

    if (!confirmed) {
      return;
    }

    try {
      setClearing(true);
      setStatus("");

      await apiDelete("/history");

      setMessages([]);
      setSearchQuery("");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to clear history.";

      setStatus(message);
    } finally {
      setClearing(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-[calc(100vh-64px)] max-w-7xl flex-col gap-6">
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-6">
        <div className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-[var(--accent-glow)] blur-3xl" />
        <div className="pointer-events-none absolute -bottom-28 left-1/3 h-64 w-64 rounded-full bg-[var(--secondary-glow)] blur-3xl" />

        <div className="relative z-10 grid gap-6 lg:grid-cols-[1fr_20rem]">
          <div>
            <div className="aira-chip mb-4 px-3 py-1.5 text-xs font-bold">
              <History className="h-3.5 w-3.5" />
              AIRA-X Conversation History
            </div>

            <h1 className="aira-gradient-text text-4xl font-black tracking-tight">
              Interactions
            </h1>

            <p className="mt-3 max-w-3xl text-sm leading-7 text-[var(--text-muted)]">
              Review stored conversation turns used for recent context,
              follow-up continuity, and assistant-session traceability.
            </p>
          </div>

          <div className="rounded-[1.5rem] border border-[var(--border)] bg-[var(--surface-soft)] p-4">
            <p className="text-xs font-black uppercase tracking-[0.16em] text-[var(--text-subtle)]">
              Continue in Assistant
            </p>

            <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">
              Return to Assistant for chat, document-backed answers, and
              workflow follow-ups.
            </p>

            <Link
              href="/chat"
              className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-[var(--accent)] px-4 py-3 text-xs font-black text-[var(--accent-foreground)] shadow-[var(--shadow-soft)] transition hover:-translate-y-0.5"
            >
              <Sparkles className="h-4 w-4" />
              Assistant
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
      </section>

      {loading && (
        <div className="w-fit rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-5 py-3 text-sm font-medium text-[var(--text-muted)] shadow-[var(--shadow-soft)]">
          Loading interactions...
        </div>
      )}

      {status && (
        <div
          className={cn(
            "rounded-2xl border p-4 text-sm font-semibold",
            status.toLowerCase().includes("failed") ||
              status.toLowerCase().includes("error")
              ? "border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] text-[var(--danger)]"
              : "border-[var(--border)] bg-[var(--surface-soft)] text-[var(--text-muted)]"
          )}
        >
          {status}
        </div>
      )}

      {!loading && (
        <>
          <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              label="Messages"
              value={formatNumber(messages.length)}
              description="Stored interaction turns."
              icon={<MessageSquare className="h-4 w-4" />}
            />

            <MetricCard
              label="User Turns"
              value={formatNumber(userMessageCount)}
              description="Questions and prompts from the user."
              icon={<User className="h-4 w-4" />}
              tone="success"
            />

            <MetricCard
              label="Assistant Turns"
              value={formatNumber(assistantMessageCount)}
              description="AIRA-X responses stored in history."
              icon={<Bot className="h-4 w-4" />}
              tone="secondary"
            />

            <MetricCard
              label="Latest"
              value={latestMessageAt ? "Active" : "Empty"}
              description={
                latestMessageAt
                  ? formatDateTime(latestMessageAt)
                  : "No session recorded yet."
              }
              icon={<CheckCircle2 className="h-4 w-4" />}
              tone="warning"
            />
          </section>

          <section className="sarvam-card rounded-[1.5rem] p-5">
            <SectionHeader
              icon={<Search className="h-4 w-4" />}
              title="Interaction Timeline"
              description={`Showing ${formatNumber(
                filteredMessages.length
              )} of ${formatNumber(messages.length)} stored turns.`}
              action={
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => loadMessages({ showLoading: false })}
                    className="inline-flex w-fit items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-2 text-xs font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                    Refresh
                  </button>

                  <button
                    type="button"
                    onClick={clearHistory}
                    disabled={clearing || messages.length === 0}
                    className="inline-flex w-fit items-center gap-2 rounded-full border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] px-4 py-2 text-xs font-black text-[var(--danger)] transition hover:bg-[var(--surface-hover)] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {clearing ? (
                      <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="h-3.5 w-3.5" />
                    )}
                    {clearing ? "Clearing..." : "Clear History"}
                  </button>
                </div>
              }
            />

            <label className="relative block">
              <span className="sr-only">Search interactions</span>
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-subtle)]" />

              <input
                type="text"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Search role, message content, date, or message ID..."
                className="w-full rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] px-10 py-3 text-sm text-[var(--text-strong)] outline-none transition placeholder:text-[var(--text-subtle)] focus:border-[var(--border-strong)] focus:shadow-[var(--shadow-soft)]"
              />
            </label>

            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery("")}
                className="mt-4 rounded-xl border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-2 text-xs font-black text-[var(--text-muted)] transition hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
              >
                Clear Search
              </button>
            )}
          </section>

          {messages.length === 0 ? (
            <section className="aira-panel flex min-h-[280px] flex-col items-center justify-center rounded-[1.75rem] border-dashed p-10 text-center">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--accent-soft)] text-[var(--accent)]">
                <History className="h-5 w-5" />
              </div>

              <h2 className="text-xl font-black text-[var(--text-strong)]">
                No interactions yet
              </h2>

              <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--text-muted)]">
                Start a conversation in Assistant and stored turns will appear
                here.
              </p>

              <Link
                href="/chat"
                className="mt-5 inline-flex items-center gap-2 rounded-2xl bg-[var(--accent)] px-5 py-3 text-sm font-black text-[var(--accent-foreground)] shadow-[var(--shadow-soft)] transition hover:-translate-y-0.5"
              >
                <Sparkles className="h-4 w-4" />
                Assistant
              </Link>
            </section>
          ) : filteredMessages.length === 0 ? (
            <section className="aira-panel flex min-h-[260px] flex-col items-center justify-center rounded-[1.75rem] border-dashed p-10 text-center">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--warning-soft)] text-[var(--warning)]">
                <Search className="h-5 w-5" />
              </div>

              <h2 className="text-xl font-black text-[var(--text-strong)]">
                No matching interactions
              </h2>

              <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--text-muted)]">
                Try searching a different role, phrase, date, or message ID.
              </p>
            </section>
          ) : (
            <section className="space-y-4">
              {filteredMessages.map((message) => (
                <MessageCard key={message.id} message={message} />
              ))}
            </section>
          )}
        </>
      )}
    </div>
  );
}

