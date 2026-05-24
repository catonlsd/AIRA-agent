import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, Manrope } from "next/font/google";
import { AppShell } from "@/components/app-shell";
import { ModeProvider } from "@/components/mode-provider";
import { ThemeProvider } from "@/components/theme-provider";
import "./globals.css";

const manrope = Manrope({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "AIRA / AIRA-X | Research & Execution Platform",
    template: "%s | AIRA-X",
  },
  description:
    "AIRA is a grounded AI research assistant. AIRA-X extends it into an autonomous research and execution platform with workflows, approvals, tools, validation, and traceable execution.",
  applicationName: "AIRA-X",
  keywords: [
    "AIRA",
    "AIRA-X",
    "AI research assistant",
    "AI execution platform",
    "autonomous workflows",
    "multi-agent system",
    "RAG",
    "workflow automation",
  ],
  authors: [{ name: "AIRA-X" }],
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#050509",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${manrope.variable} ${ibmPlexMono.variable} min-h-screen`}
      >
        <ThemeProvider>
          <ModeProvider>
            <AppShell>{children}</AppShell>
          </ModeProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}