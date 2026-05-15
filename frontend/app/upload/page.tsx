"use client";

import { useState } from "react";
import { FileText, Upload } from "lucide-react";
import { uploadDocuments } from "@/lib/api";

export default function UploadPage() {
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const input = event.currentTarget.elements.namedItem(
      "files"
    ) as HTMLInputElement;

    if (!input.files?.length) {
      return setStatus("Choose at least one document.");
    }

    setLoading(true);
    setStatus("");

    try {
      const result = await uploadDocuments(input.files);
      setStatus(`Uploaded ${result.documents.length} document(s).`);
      input.value = "";
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Upload failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-7">
        <div className="absolute -right-16 -top-16 h-48 w-48 rounded-full bg-blue-200/50 blur-3xl" />

        <div className="relative z-10">
          <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-blue-100 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-accent">
            <FileText className="h-3.5 w-3.5" />
            Document ingestion
          </div>

          <h1 className="text-3xl font-semibold tracking-tight text-slate-950">
            Upload Documents
          </h1>

          <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">
            Upload PDF, TXT, DOCX, and Markdown files. The system extracts text,
            chunks content, creates embeddings, and indexes sources for
            citation-grounded answers.
          </p>
        </div>
      </section>

      <form
        onSubmit={onSubmit}
        className="sarvam-card fade-up rounded-[2rem] p-6"
      >
        <label className="block text-sm font-semibold text-slate-800">
          Documents
        </label>

        <div className="mt-3 rounded-[1.5rem] border border-dashed border-blue-200 bg-blue-50/40 p-8 text-center transition-all duration-300 hover:border-accent hover:bg-blue-50">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-white text-accent shadow-sm">
            <Upload className="h-6 w-6" />
          </div>

          <p className="text-sm font-semibold text-slate-800">
            Select documents to upload
          </p>

          <p className="mt-1 text-xs text-slate-500">
            Supported formats: PDF, TXT, DOCX, MD
          </p>

          <input
            name="files"
            type="file"
            multiple
            accept=".pdf,.txt,.docx,.md,.markdown"
            className="mx-auto mt-5 block w-full max-w-md cursor-pointer rounded-full border border-blue-100 bg-white px-4 py-3 text-sm text-slate-700 shadow-sm file:mr-4 file:rounded-full file:border-0 file:bg-blue-50 file:px-4 file:py-2 file:text-sm file:font-semibold file:text-accent hover:border-accent"
          />
        </div>

        <button
          disabled={loading}
          className="group mt-5 inline-flex items-center gap-2 rounded-full bg-accent px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-blue-600/20 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-xl hover:shadow-blue-600/25 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <Upload className="h-4 w-4 transition-transform duration-300 group-hover:-translate-y-1 group-hover:scale-110" />
          {loading ? "Processing documents..." : "Upload and index"}
        </button>

        {status && (
          <div className="fade-up mt-5 rounded-2xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm font-medium text-slate-700">
            {status}
          </div>
        )}
      </form>
    </div>
  );
}