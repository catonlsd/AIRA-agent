"use client";

import { useEffect, useState } from "react";
import { Library, FileText, Sparkles, Trash2 } from "lucide-react";
import { apiDelete, apiGet, summarizeDocument } from "@/lib/api";
import { CitationList } from "@/components/citation-list";
import type { Citation } from "@/lib/api";

type DocumentRow = {
  id: number;
  filename: string;
  file_type: string;
  chunk_count: number;
  created_at: string;
};

export default function DocumentsPage() {
  const [docs, setDocs] = useState<DocumentRow[]>([]);
  const [status, setStatus] = useState("");
  const [summary, setSummary] = useState<{
    text: string;
    citations: Citation[];
  } | null>(null);

  async function load() {
    setDocs(await apiGet<DocumentRow[]>("/documents"));
  }

  useEffect(() => {
    load().catch((error) => setStatus(error.message));
  }, []);

  async function remove(id: number) {
    await apiDelete(`/documents/${id}`);
    await load();
  }

  async function summarize(id: number) {
    setStatus("Summarizing document...");

    const result = await summarizeDocument(id);

    setSummary({
      text: result.summary,
      citations: result.citations,
    });

    setStatus("");
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-7">
        <div className="absolute -right-16 -top-16 h-48 w-48 rounded-full bg-blue-200/50 blur-3xl" />

        <div className="relative z-10">
          <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-blue-100 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-accent">
            <Library className="h-3.5 w-3.5" />
            AI-powered knowledge base
          </div>

          <h1 className="text-3xl font-semibold tracking-tight text-slate-950">
            Document Library
          </h1>

          <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">
            Manage uploaded documents, inspect indexed chunks, and generate
            clean summaries with source citations.
          </p>
        </div>
      </section>

      {status && (
        <div className="fade-up rounded-2xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm font-medium text-slate-700">
          {status}
        </div>
      )}

      <section className="sarvam-card fade-up overflow-hidden rounded-[2rem]">
        {docs.map((doc) => (
          <div
            key={doc.id}
            className="group flex flex-wrap items-center justify-between gap-4 border-b border-blue-100 p-5 transition-all duration-300 last:border-b-0 hover:bg-blue-50/50"
          >
            <div className="flex items-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-blue-50 text-accent transition-all duration-300 group-hover:-translate-y-0.5 group-hover:scale-105">
                <FileText className="h-5 w-5" />
              </div>

              <div>
                <div className="font-semibold text-slate-900">
                  {doc.filename}
                </div>

                <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-500">
                  <span className="rounded-full bg-blue-50 px-2 py-1 font-medium text-accent">
                    {doc.file_type.toUpperCase()}
                  </span>
                  <span className="rounded-full bg-slate-100 px-2 py-1">
                    {doc.chunk_count} chunks
                  </span>
                </div>
              </div>
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => summarize(doc.id)}
                className="inline-flex items-center gap-2 rounded-full border border-blue-100 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition-all duration-300 hover:-translate-y-0.5 hover:bg-blue-50 hover:text-accent hover:shadow-sm"
              >
                <Sparkles className="h-4 w-4" />
                Summarize
              </button>

              <button
                onClick={() => remove(doc.id)}
                className="group/delete rounded-full border border-red-100 bg-white px-3 py-2 text-sm text-slate-500 transition-all duration-300 hover:-translate-y-0.5 hover:bg-red-50 hover:text-red-600 hover:shadow-sm"
              >
                <Trash2 className="h-4 w-4 transition-transform duration-300 group-hover/delete:scale-110 group-hover/delete:rotate-6" />
              </button>
            </div>
          </div>
        ))}

        {!docs.length && (
          <div className="p-8 text-center">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-blue-50 text-accent">
              <Library className="h-5 w-5" />
            </div>
            <p className="text-sm font-medium text-slate-700">
              No documents indexed yet.
            </p>
            <p className="mt-1 text-xs text-slate-500">
              Upload documents to start building your research library.
            </p>
          </div>
        )}
      </section>

      {summary && (
        <section className="sarvam-card fade-up rounded-[2rem] p-6">
          <div className="mb-4 flex items-center gap-2">
            <div className="rounded-2xl bg-blue-50 p-2 text-accent">
              <Sparkles className="h-4 w-4" />
            </div>
            <h2 className="text-lg font-semibold text-slate-900">
              Summary
            </h2>
          </div>

          <div className="whitespace-pre-wrap text-sm leading-7 text-slate-700">
            {summary.text
            .replace(/^###\s?/gm, "")
            .replace(/^##\s?/gm, "")
            .replace(/^#\s?/gm, "")
            .replace(/\*\*/g, "")
            }
          </div>

          {summary.citations.length > 0 && (
            <div className="mt-5 rounded-[1.25rem] border border-blue-100 bg-blue-50/40 p-4">
              <p className="mb-3 text-sm font-semibold text-slate-800">
                Sources
              </p>
              <CitationList citations={summary.citations} />
            </div>
          )}
        </section>
      )}
    </div>
  );
}