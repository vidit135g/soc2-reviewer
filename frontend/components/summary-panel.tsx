"use client";

import * as React from "react";
import {
  ClipboardCopy,
  Download,
  FileText,
  Loader2,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { getSummary } from "@/lib/api";
import { cn, formatDateTime } from "@/lib/utils";
import type { ReportDetail, ReportSummary } from "@/types";

const RATING_TONE: Record<
  string,
  { badge: "success" | "warning" | "destructive" | "outline"; tone: string }
> = {
  Strong: { badge: "success", tone: "border-emerald-500/30" },
  Moderate: { badge: "warning", tone: "border-amber-500/30" },
  Weak: { badge: "destructive", tone: "border-red-500/30" },
  Unknown: { badge: "outline", tone: "" },
};

const READINESS_TONE: Record<
  string,
  { badge: "success" | "warning" | "destructive" | "outline"; icon: React.ElementType }
> = {
  Ready: { badge: "success", icon: ThumbsUp },
  "Needs Review": { badge: "warning", icon: ShieldAlert },
  "Not Ready": { badge: "destructive", icon: ThumbsDown },
  Unknown: { badge: "outline", icon: ShieldCheck },
};

export function SummaryPanel({
  reportId,
  report,
}: {
  reportId: string;
  report: ReportDetail;
}) {
  const [summary, setSummary] = React.useState<ReportSummary | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await getSummary(reportId);
      setSummary(s);
    } catch (e: any) {
      setError(e?.message ?? "Failed to generate summary");
    } finally {
      setLoading(false);
    }
  }, [reportId]);

  React.useEffect(() => {
    load();
  }, [load]);

  if (loading) return <SummarySkeleton />;

  if (error) {
    return (
      <Card>
        <CardContent className="p-6 text-sm text-red-600 dark:text-red-400">
          {error}
          <div className="mt-3">
            <Button size="sm" variant="outline" onClick={load}>
              <RefreshCw className="mr-2 h-4 w-4" /> Retry
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }
  if (!summary) return null;

  const tone = RATING_TONE[summary.rating] ?? RATING_TONE.Unknown;
  const readiness = READINESS_TONE[summary.vendor_readiness] ?? READINESS_TONE.Unknown;
  const ReadinessIcon = readiness.icon;

  const markdown = buildMarkdown(report, summary);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(markdown);
      toast.success("Summary copied to clipboard");
    } catch {
      toast.error("Could not copy summary");
    }
  };

  const download = () => {
    const blob = new Blob([markdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(report.company_name || "report").replace(/\s+/g, "-").toLowerCase()}-soc2-summary.md`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4">
      <Card className={cn("border-2", tone.tone)}>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div>
              <CardTitle className="flex items-center gap-2">
                <FileText className="h-4 w-4 text-primary" />
                Executive summary
              </CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">
                Generated {formatDateTime(summary.generated_at)}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={tone.badge}>Rating: {summary.rating}</Badge>
              <Badge variant={readiness.badge}>
                <ReadinessIcon className="mr-1 h-3 w-3" />
                {summary.vendor_readiness}
              </Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          <p className="text-sm leading-relaxed">{summary.executive_summary}</p>

          <div className="grid gap-4 md:grid-cols-2">
            <Section title="Key strengths" items={summary.key_strengths} tone="success" />
            <Section title="Key risks" items={summary.key_risks} tone="destructive" />
          </div>

          <Section
            title="Recommended follow-up questions"
            items={summary.recommended_followups}
            tone="info"
          />

          <div className="flex items-center justify-end gap-2">
            <Button variant="outline" size="sm" onClick={copy}>
              <ClipboardCopy className="mr-2 h-4 w-4" />
              Copy markdown
            </Button>
            <Button size="sm" onClick={download}>
              <Download className="mr-2 h-4 w-4" />
              Export .md
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function Section({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: "success" | "destructive" | "info";
}) {
  const dot = {
    success: "bg-emerald-500",
    destructive: "bg-red-500",
    info: "bg-sky-500",
  }[tone];
  return (
    <div>
      <h4 className="mb-2 text-sm font-semibold">{title}</h4>
      {items.length === 0 ? (
        <p className="text-xs text-muted-foreground">None identified.</p>
      ) : (
        <ul className="space-y-1.5 text-sm">
          {items.map((t) => (
            <li key={t} className="flex items-start gap-2">
              <span className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", dot)} />
              <span className="leading-relaxed">{t}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SummarySkeleton() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" />
          Preparing summary…
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
        <Skeleton className="h-4 w-3/4" />
        <div className="grid gap-3 md:grid-cols-2">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      </CardContent>
    </Card>
  );
}

function buildMarkdown(report: ReportDetail, summary: ReportSummary): string {
  const lines: string[] = [];
  lines.push(`# SOC 2 Review Summary`);
  lines.push("");
  lines.push(`**Company:** ${report.company_name || "Unknown"}  `);
  lines.push(`**Report type:** ${report.report_type || "Unknown"}  `);
  lines.push(`**Auditor:** ${report.auditor_firm || "Unknown"}  `);
  lines.push(`**Opinion:** ${report.opinion || "Unknown"}  `);
  if (report.coverage_start && report.coverage_end) {
    lines.push(`**Coverage:** ${report.coverage_start} → ${report.coverage_end}  `);
  }
  lines.push(`**Risk score:** ${report.risk_score}/100 (${report.risk_rating})  `);
  lines.push(`**Vendor readiness:** ${summary.vendor_readiness}  `);
  lines.push("");
  lines.push(`## Executive summary`);
  lines.push("");
  lines.push(summary.executive_summary);
  lines.push("");
  lines.push(`## Key strengths`);
  summary.key_strengths.forEach((s) => lines.push(`- ${s}`));
  lines.push("");
  lines.push(`## Key risks`);
  summary.key_risks.forEach((s) => lines.push(`- ${s}`));
  lines.push("");
  lines.push(`## Recommended follow-up questions`);
  summary.recommended_followups.forEach((s) => lines.push(`- ${s}`));
  lines.push("");
  lines.push(`## Validation findings`);
  report.findings.forEach((f) => {
    lines.push(`- [${f.severity.toUpperCase()}] ${f.title} — ${f.detail}`);
  });
  return lines.join("\n");
}
