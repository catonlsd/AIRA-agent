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
    default: "AIRA-X | AI Research & Execution Platform",
    template: "%s · AIRA-X",
  },
  description:
    "AIRA-X is a production AI workspace for conversational answers, document-backed research, workflow execution, approvals, and auditable tool operations.",
  applicationName: "AIRA-X",
  keywords: [
    "AIRA-X",
    "AI assistant",
    "document RAG",
    "workflow automation",
    "human-in-the-loop",
    "enterprise AI",
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