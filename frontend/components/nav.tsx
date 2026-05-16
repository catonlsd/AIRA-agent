"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import {
  BookOpen,
  Handshake,
  Home,
  MessageSquare,
  Sparkles,
  Wrench,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const links = [
  { href: "/", label: "Home", animation: "home" },
  { href: "/upload", label: "Ingest Documents", animation: "upload" },
  { href: "/chat", label: "Ask AIRA-X", animation: "chat" },
  { href: "/documents", label: "Knowledge Base", animation: "book" },
  { href: "/history", label: "Interactions", animation: "handshake" },
  { href: "/tools", label: "Tools Registry", animation: "tools" },
  { href: "/settings", label: "About AIRA-X", animation: "spark" },
];

function UploadAnimatedIcon({ active }: { active: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={cn(
        "h-4 w-4 transition-colors duration-300",
        active ? "text-white" : "text-slate-500 group-hover:text-accent"
      )}
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />

      <g className="transition-all duration-700 ease-out group-hover:-translate-y-3 group-hover:opacity-0">
        <polyline points="17 8 12 3 7 8" />
        <line x1="12" y1="3" x2="12" y2="15" />
      </g>
    </svg>
  );
}

export function Nav() {
  const pathname = usePathname();
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);

  useEffect(() => {
    async function checkBackendHealth() {
      try {
        const response = await fetch(`${API_URL}/health`, {
          cache: "no-store",
        });

        setBackendOnline(response.ok);
      } catch {
        setBackendOnline(false);
      }
    }

    checkBackendHealth();

    const interval = setInterval(checkBackendHealth, 15000);

    return () => clearInterval(interval);
  }, []);

  return (
    <aside className="sticky top-0 flex min-h-screen w-72 flex-col border-r border-blue-100 bg-white/85 px-5 py-6 shadow-[8px_0_30px_rgba(37,99,235,0.06)] backdrop-blur-xl">
      <div className="mb-8 rounded-3xl border border-blue-100 bg-gradient-to-br from-white to-blue-50/70 p-4 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="rounded-2xl bg-blue-600 p-3 text-white shadow-lg shadow-blue-600/20 transition-all duration-300 hover:-translate-y-0.5 hover:rotate-3">
            <Sparkles className="h-5 w-5" />
          </div>

          <div>
            <div className="text-lg font-bold tracking-tight text-slate-950">
              AIRA-X
            </div>
            <div className="text-sm font-semibold text-accent">
              Research + Execution Platform
            </div>
          </div>
        </div>

        <p className="mt-4 text-sm leading-6 text-slate-500">
          Execution-focused AI platform for research, tool use, workflow
          automation, validation, and self-correction.
        </p>
      </div>

      <nav className="space-y-2">
        {links.map((item) => {
          const active = pathname === item.href;

          const iconClass =
            item.animation === "home"
              ? "group-hover:translate-x-2 group-hover:scale-110 group-hover:drop-shadow-[0_0_8px_rgba(37,99,235,0.45)] duration-500"
              : item.animation === "chat"
              ? "group-hover:animate-[chatBubblePop_0.55s_ease-out] duration-500"
              : item.animation === "book"
              ? "group-hover:scale-x-125 group-hover:scale-y-110 duration-500"
              : item.animation === "handshake"
              ? "group-hover:animate-[handshake_0.55s_ease-in-out] duration-500"
              : item.animation === "tools"
              ? "group-hover:rotate-12 group-hover:scale-125 duration-500"
              : "group-hover:rotate-6 group-hover:scale-125 duration-500";

          const Icon =
            item.animation === "home"
              ? Home
              : item.animation === "chat"
              ? MessageSquare
              : item.animation === "book"
              ? BookOpen
              : item.animation === "handshake"
              ? Handshake
              : item.animation === "tools"
              ? Wrench
              : item.animation === "spark"
              ? Sparkles
              : null;

          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "group relative flex items-center gap-3 rounded-2xl px-4 py-3 text-sm font-semibold transition-all duration-300 ease-out",
                "hover:-translate-y-0.5 hover:translate-x-1",
                active
                  ? "bg-blue-600 text-white shadow-lg shadow-blue-600/20"
                  : "text-slate-600 hover:bg-blue-50 hover:text-slate-950"
              )}
            >
              {active && (
                <span className="absolute left-1 top-1/2 h-6 w-1 -translate-y-1/2 rounded-full bg-white/80" />
              )}

              {item.animation === "upload" ? (
                <UploadAnimatedIcon active={active} />
              ) : Icon ? (
                item.animation === "spark" ? (
                  <span
                    className={cn(
                      "rounded-xl bg-blue-600 p-1 text-white shadow-lg shadow-blue-600/20 transition-all duration-300",
                      "group-hover:-translate-y-0.5 group-hover:rotate-3"
                    )}
                  >
                    <Icon className="h-4 w-4" />
                  </span>
                ) : (
                  <Icon
                    className={cn(
                      "h-4 w-4 transition-all ease-out",
                      iconClass,
                      active
                        ? "text-white"
                        : "text-slate-500 group-hover:text-accent"
                    )}
                  />
                )
              ) : null}

              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <div
        className={cn(
          "mt-auto rounded-3xl border p-4 transition-all duration-300",
          backendOnline === true
            ? "border-blue-100 bg-gradient-to-br from-blue-50 to-white"
            : backendOnline === false
            ? "border-red-100 bg-gradient-to-br from-red-50 to-white"
            : "border-slate-200 bg-gradient-to-br from-slate-50 to-white"
        )}
      >
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "h-2.5 w-2.5 rounded-full",
              backendOnline === true
                ? "bg-blue-600 shadow-[0_0_14px_rgba(37,99,235,0.55)]"
                : backendOnline === false
                ? "bg-red-500 shadow-[0_0_14px_rgba(239,68,68,0.55)]"
                : "bg-slate-400"
            )}
          />

          <span className="text-sm font-semibold text-slate-800">
            {backendOnline === null
              ? "Checking AIRA-X"
              : backendOnline
              ? "AIRA-X Online"
              : "AIRA-X Offline"}
          </span>
        </div>
      </div>
    </aside>
  );
}