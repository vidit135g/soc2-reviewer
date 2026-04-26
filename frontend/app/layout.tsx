import type { Metadata, Viewport } from "next";
import { Toaster } from "sonner";
import "./globals.css";

import { AnimatedBackdrop } from "@/components/animated-backdrop";
import { ThemeProvider } from "@/components/theme-provider";
import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";
import { cn } from "@/lib/utils";

// NOTE: We intentionally DO NOT use `next/font/google`. That helper fetches
// font files from fonts.googleapis.com at **build time**, which breaks
// offline / sandboxed docker builds. Instead, we load the same fonts at
// runtime via <link> tags below — the browser handles fallback to the
// system stack defined in globals.css if Google Fonts is unreachable.

export const metadata: Metadata = {
  title: {
    default: "SOC 2 Report Reviewer",
    template: "%s · SOC 2 Reviewer",
  },
  description:
    "Upload a SOC 2 report PDF and instantly validate, analyze, and ask security questions grounded in the report.",
  keywords: [
    "SOC 2",
    "security review",
    "vendor risk",
    "auditor report",
    "compliance",
    "AI",
  ],
  openGraph: {
    title: "SOC 2 Report Reviewer",
    description:
      "Upload a SOC 2 report and instantly validate, analyze, and ask security questions.",
    type: "website",
  },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#F8F8F8" },
    { media: "(prefers-color-scheme: dark)", color: "#1B1B1B" },
  ],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Runtime Google Fonts — build stays offline-safe. */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Instrument+Serif:ital@0;1&family=JetBrains+Mono:wght@400;500;600;700&display=swap"
        />
      </head>
      <body
        className={cn(
          // Body is transparent on purpose — the solid fallback lives on
          // <html> (see globals.css), and the fixed AnimatedBackdrop
          // animates over it. Keeping body transparent lets the mesh
          // render at z-index -10 without being occluded.
          "min-h-screen font-sans antialiased",
        )}
      >
        <ThemeProvider
          attribute="class"
          defaultTheme="light"
          enableSystem
          disableTransitionOnChange
        >
          {/* Fixed full-viewport animated gradient — sits behind all routes */}
          <AnimatedBackdrop />

          <div className="relative flex min-h-screen flex-col">
            <SiteHeader />
            <main className="flex-1">{children}</main>
            <SiteFooter />
          </div>
          <Toaster richColors position="top-right" />
        </ThemeProvider>
      </body>
    </html>
  );
}
