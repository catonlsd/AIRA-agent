import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, JetBrains_Mono, Manrope } from "next/font/google";
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

// Operations mono — IDs, timestamps, metrics, log lines, incident numbers.
const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-ops",
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
  themeColor: "#2e2c7a", // night default; the provider updates this live per period
};

// Set data-theme/data-scheme before first paint so there is no wrong-theme flash.
// Mirrors lib/timeTheme.ts (kept inline because this runs pre-hydration, no imports).
const THEME_BOOTSTRAP = `(function(){try{var k="aira-x-theme";var v=localStorage.getItem(k);` +
  `var n=["predawn","sunrise","daytime","dusk","sunset","night"];` +
  `var t=n.indexOf(v)>=0?v:null;if(!t){var d=new Date();var m=d.getHours()*60+d.getMinutes();` +
  `t=(m>=180&&m<=329)?"predawn":(m>=330&&m<=479)?"sunrise":(m>=480&&m<=1019)?"daytime":` +
  `(m>=1020&&m<=1109)?"dusk":(m>=1110&&m<=1154)?"sunset":"night";}` +
  `var e=document.documentElement;e.dataset.theme=t;e.dataset.scheme=t==="night"?"dark":"light";` +
  `e.style.colorScheme=t==="night"?"dark":"light";}catch(e){}})();`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      </head>
      <body
        className={`${manrope.variable} ${ibmPlexMono.variable} ${jetbrainsMono.variable} no-page-scroll`}
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