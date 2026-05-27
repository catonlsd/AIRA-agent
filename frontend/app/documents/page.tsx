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
  BookOpen,
  Database,
  FileText,
  Library,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  UploadCloud,
} from "lucide-react";
import {
  apiDelete,
  apiGet,
  summarizeDocument,
  type Citation,
} from "@/lib/api";
import { CitationList } from "@/components/citation-list";
import { cn } from "@/lib/utils";

type DocumentRow = {
  id: number;
  filename: string;
  file_type: string;
  chunk_count: number;
  created_at: string;
};

type SummaryState = {
  documentId: number;
  documentName: string;
  text: string;
  citations: Citation[];
};

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

function sanitizeSummaryText(value: string) {
  return value
    .replace(/^###\s?/gm, "")
    .replace(/^##\s?/gm, "")
    .replace(/^#\s?/gm, "")
    .replace(/\*\*/g, "")
    .trim();
}

function getFileTypeLabel(fileType?: string) {
  return (fileType || "file").toUpperCase();
}

function getDocumentSearchText(doc: DocumentRow) {
  return [
    doc.filename,
    doc.file_type,
    doc.chunk_count,
    doc.created_at,
    String(doc.id),
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

function DocumentCard({
  doc,
  deleting,
  summarizing,
  onDelete,
  onSummarize,
}: {
  doc: DocumentRow;
  deleting: boolean;
  summarizing: boolean;
  onDelete: (doc: DocumentRow) => Promise<void>;
  onSummarize: (doc: DocumentRow) => Promise<void>;
}) {
  return (
    <article className="sarvam-card rounded-[1.5rem] p-5">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0 flex-1">
          <div className="mb-4 flex items-start gap-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--accent-soft)] text-[var(--accent)]">
              <FileText className="h-5 w-5" />
            </div>

            <div className="min-w-0">
              <h3 className="line-clamp-1 text-lg font-black text-[var(--text-strong)]">
                {doc.filename}
              </h3>

              <p className="mt-1 font-mono text-[11px] text-[var(--text-subtle)]">
                Document ID: {doc.id}
              </p>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-3">
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-3">
              <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
                File Type
              </p>

              <p className="mt-1 text-sm font-semibold text-[var(--text-strong)]">
                {getFileTypeLabel(doc.file_type)}
              </p>
            </div>

            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-3">
              <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
                Indexed Chunks
              </p>

              <p className="mt-1 text-sm font-semibold text-[var(--text-strong)]">
                {formatNumber(doc.chunk_count)}
              </p>
            </div>

            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-3">
              <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
                Added
              </p>

              <p className="mt-1 text-sm font-semibold text-[var(--text-strong)]">
                {formatDateTime(doc.created_at)}
              </p>
            </div>
          </div>

          <p className="mt-4 text-sm leading-6 text-[var(--text-muted)]">
            This source is indexed into your AIRA-X knowledge layer and can be used
            for document-backed answers, summaries, retrieval, and citations.
          </p>
        </div>

        <div className="flex shrink-0 flex-col gap-3 xl:w-48">
          <button
            type="button"
            onClick={() => onSummarize(doc)}
            disabled={summarizing || deleting}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-2.5 text-xs font-black text-[var(--accent-foreground)] shadow-[var(--shadow-soft)] transition hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {summarizing ? (
              <RefreshCw className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            {summarizing ? "Summarizing..." : "Summarize"}
          </button>

          <button
            type="button"
            onClick={() => onDelete(doc)}
            disabled={summarizing || deleting}
            className="inline-flex items-center justify-center gap-2 rounded-xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] px-4 py-2.5 text-xs font-black text-[var(--danger)] transition hover:bg-[var(--surface-hover)] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {deleting ? (
              <RefreshCw className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Trash2 className="h-3.5 w-3.5" />
            )}
            {deleting ? "Deleting..." : "Delete"}
          </button>
        </div>
      </div>
    </article>
  );
}

export default function DocumentsPage() {
  const [docs, setDocs] = useState<DocumentRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [summary, setSummary] = useState<SummaryState | null>(null);
  const [summarizingId, setSummarizingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const loadDocuments = useCallback(
    async (options?: { showLoading?: boolean }) => {
      const showLoading = options?.showLoading ?? true;

      try {
        if (showLoading) {
          setLoading(true);
        }

        const data = await apiGet<DocumentRow[]>("/documents");

        setDocs(data);
        setStatus("");
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Failed to load documents.";

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
    loadDocuments();
  }, [loadDocuments]);

  const totalChunks = useMemo(
    () => docs.reduce((total, doc) => total + (doc.chunk_count || 0), 0),
    [docs]
  );

  const fileTypeCount = useMemo(
    () => new Set(docs.map((doc) => getFileTypeLabel(doc.file_type))).size,
    [docs]
  );

  const averageChunks = useMemo(() => {
    if (docs.length === 0) {
      return 0;
    }

    return Math.round(totalChunks / docs.length);
  }, [docs.length, totalChunks]);

  const filteredDocs = useMemo(() => {
    const normalizedSearch = searchQuery.trim().toLowerCase();

    if (!normalizedSearch) {
      return docs;
    }

    return docs.filter((doc) =>
      getDocumentSearchText(doc).includes(normalizedSearch)
    );
  }, [docs, searchQuery]);

  async function removeDocument(doc: DocumentRow) {
    const confirmed = window.confirm(
      `Delete this document from AIRA-X knowledge?\n\n${doc.filename}\n\nThis removes the indexed source from local storage.`
    );

    if (!confirmed) {
      return;
    }

    try {
      setDeletingId(doc.id);
      setStatus("");

      await apiDelete(`/documents/${doc.id}`);
      await loadDocuments({ showLoading: false });

      if (summary?.documentId === doc.id) {
        setSummary(null);
      }
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to delete document.";

      setStatus(message);
    } finally {
      setDeletingId(null);
    }
  }

  async function summarize(doc: DocumentRow) {
    try {
      setSummarizingId(doc.id);
      setStatus("Summarizing document...");

      const result = await summarizeDocument(doc.id);

      setSummary({
        documentId: doc.id,
        documentName: doc.filename,
        text: result.summary,
        citations: result.citations,
      });

      setStatus("");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to summarize document.";

      setStatus(message);
    } finally {
      setSummarizingId(null);
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
              <Library className="h-3.5 w-3.5" />
              AIRA-X Knowledge
            </div>

            <h1 className="aira-gradient-text text-4xl font-black tracking-tight">
              Knowledge
            </h1>

            <p className="mt-3 max-w-3xl text-sm leading-7 text-[var(--text-muted)]">
              Manage uploaded sources, inspect indexed chunks, summarize
              documents, and keep your library ready for grounded AIRA-X
              answers in Assistant.
            </p>
          </div>

          <div className="rounded-[1.5rem] border border-[var(--border)] bg-[var(--surface-soft)] p-4">
            <p className="text-xs font-black uppercase tracking-[0.16em] text-[var(--text-subtle)]">
              Source Intake
            </p>

            <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">
              Upload documents from Assistant, then manage indexed sources here.
            </p>

            <Link
              href="/chat"
              className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-[var(--accent)] px-4 py-3 text-xs font-black text-[var(--accent-foreground)] shadow-[var(--shadow-soft)] transition hover:-translate-y-0.5"
            >
              <UploadCloud className="h-4 w-4" />
              Upload in Assistant
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
      </section>

      {loading && (
        <div className="w-fit rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-5 py-3 text-sm font-medium text-[var(--text-muted)] shadow-[var(--shadow-soft)]">
          Loading knowledge sources...
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
              label="Documents"
              value={formatNumber(docs.length)}
              description="Indexed sources available to Assistant."
              icon={<Library className="h-4 w-4" />}
            />

            <MetricCard
              label="Chunks"
              value={formatNumber(totalChunks)}
              description="Retrieved units for grounded answers."
              icon={<Database className="h-4 w-4" />}
              tone="secondary"
            />

            <MetricCard
              label="File Types"
              value={formatNumber(fileTypeCount)}
              description="Distinct source formats in the library."
              icon={<FileText className="h-4 w-4" />}
              tone="success"
            />

            <MetricCard
              label="Avg. Chunks"
              value={formatNumber(averageChunks)}
              description="Average indexed chunks per document."
              icon={<BookOpen className="h-4 w-4" />}
              tone="warning"
            />
          </section>

          <section className="sarvam-card rounded-[1.5rem] p-5">
            <SectionHeader
              icon={<Search className="h-4 w-4" />}
              title="Source Library"
              description={`Showing ${formatNumber(filteredDocs.length)} of ${formatNumber(
                docs.length
              )} indexed documents.`}
              action={
                <button
                  type="button"
                  onClick={() => loadDocuments({ showLoading: false })}
                  className="inline-flex w-fit items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-2 text-xs font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  Refresh
                </button>
              }
            />

            <label className="relative block">
              <span className="sr-only">Search documents</span>
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-subtle)]" />

              <input
                type="text"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Search filename, file type, document ID, or date..."
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

          {docs.length === 0 ? (
            <section className="aira-panel flex min-h-[280px] flex-col items-center justify-center rounded-[1.75rem] border-dashed p-10 text-center">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--accent-soft)] text-[var(--accent)]">
                <Library className="h-5 w-5" />
              </div>

              <h2 className="text-xl font-black text-[var(--text-strong)]">
                No documents indexed yet
              </h2>

              <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--text-muted)]">
                Upload documents in Assistant to build a searchable knowledge
                layer for citation-backed answers.
              </p>

              <Link
                href="/chat"
                className="mt-5 inline-flex items-center gap-2 rounded-2xl bg-[var(--accent)] px-5 py-3 text-sm font-black text-[var(--accent-foreground)] shadow-[var(--shadow-soft)] transition hover:-translate-y-0.5"
              >
                <UploadCloud className="h-4 w-4" />
                Upload Documents
              </Link>
            </section>
          ) : filteredDocs.length === 0 ? (
            <section className="aira-panel flex min-h-[260px] flex-col items-center justify-center rounded-[1.75rem] border-dashed p-10 text-center">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--warning-soft)] text-[var(--warning)]">
                <Search className="h-5 w-5" />
              </div>

              <h2 className="text-xl font-black text-[var(--text-strong)]">
                No matching documents
              </h2>

              <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--text-muted)]">
                Try searching a different filename, file type, document ID, or
                upload date.
              </p>
            </section>
          ) : (
            <section className="grid gap-4">
              {filteredDocs.map((doc) => (
                <DocumentCard
                  key={doc.id}
                  doc={doc}
                  deleting={deletingId === doc.id}
                  summarizing={summarizingId === doc.id}
                  onDelete={removeDocument}
                  onSummarize={summarize}
                />
              ))}
            </section>
          )}

          {summary && (
            <section className="sarvam-card fade-up rounded-[1.75rem] p-5">
              <SectionHeader
                icon={<Sparkles className="h-4 w-4" />}
                title="Document Summary"
                description={`Generated summary for ${summary.documentName}.`}
                action={
                  <button
                    type="button"
                    onClick={() => setSummary(null)}
                    className="inline-flex w-fit items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-2 text-xs font-black text-[var(--text-muted)] transition hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
                  >
                    Close
                  </button>
                }
              />

              <div className="whitespace-pre-wrap rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-5 text-sm leading-7 text-[var(--text)]">
                {sanitizeSummaryText(summary.text)}
              </div>

              {summary.citations.length > 0 && (
                <div className="mt-5 rounded-[1.25rem] border border-[var(--border)] bg-[var(--surface-soft)] p-4">
                  <p className="mb-3 text-sm font-black text-[var(--text-strong)]">
                    Sources
                  </p>

                  <CitationList citations={summary.citations} />
                </div>
              )}
            </section>
          )}
        </>
      )}
    </div>
  );
}
