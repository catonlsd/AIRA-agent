"use client";

import { useEffect, useState } from "react";
import { History, MessageSquare, Trash2 } from "lucide-react";
import { apiDelete, apiGet } from "@/lib/api";

type Message = {
  id: number;
  role: string;
  content: string;
  created_at: string;
};

export default function HistoryPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [status, setStatus] = useState("");

  async function load() {
    setMessages(await apiGet<Message[]>("/history"));
  }

  useEffect(() => {
    load().catch((error) => setStatus(error.message));
  }, []);

  async function clear() {
    await apiDelete("/history");
    setMessages([]);
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-7">
        <div className="absolute -right-16 -top-16 h-48 w-48 rounded-full bg-blue-200/50 blur-3xl" />

        <div className="relative z-10 flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-blue-100 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-accent">
              <History className="h-3.5 w-3.5" />
              Conversation archive
            </div>

            <h1 className="text-3xl font-semibold tracking-tight text-slate-950">
              Interaction Timeline
            </h1>

            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">
              Review stored conversation turns used by the assistant for recent
              context and follow-up continuity.
            </p>
          </div>

          <button
            onClick={clear}
            className="group inline-flex items-center gap-2 rounded-full border border-red-100 bg-white px-4 py-2 text-sm font-semibold text-slate-600 transition-all duration-300 hover:-translate-y-0.5 hover:bg-red-50 hover:text-red-600 hover:shadow-sm"
          >
            <Trash2 className="h-4 w-4 transition-transform duration-300 group-hover:scale-110 group-hover:rotate-6" />
            Clear history
          </button>
        </div>
      </section>

      {status && (
        <div className="fade-up rounded-2xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm font-medium text-slate-700">
          {status}
        </div>
      )}

      <section className="space-y-3">
        {messages.map((message) => (
          <div
            key={message.id}
            className="sarvam-card fade-up rounded-[1.5rem] p-5 transition-all duration-300 hover:-translate-y-0.5"
          >
            <div className="mb-3 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-blue-50 text-accent">
                <MessageSquare className="h-4 w-4" />
              </div>

              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-accent">
                  {message.role}
                </div>
                <div className="text-xs text-slate-400">
                  {new Date(message.created_at).toLocaleString()}
                </div>
              </div>
            </div>

            <div className="whitespace-pre-wrap text-sm leading-7 text-slate-700">
              {message.content}
            </div>
          </div>
        ))}

        {!messages.length && (
          <div className="sarvam-card fade-up rounded-[2rem] p-10 text-center">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-blue-50 text-accent">
              <History className="h-5 w-5" />
            </div>

            <p className="text-sm font-semibold text-slate-800">
              No interactions yet.
            </p>

            <p className="mt-1 text-xs text-slate-500">
              You haven't interacted with AIRA yet.
            </p>
          </div>
        )}
      </section>
    </div>
  );
}