"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  Building2,
  CalendarRange,
  FileText,
  Gavel,
  Hash,
  LayoutDashboard,
  ListChecks,
  Loader2,
  MessageSquareMore,
  Scale,
  Sparkles,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ChatInterface } from "@/components/chat-interface";
import { OverviewTab } from "@/components/overview-tab";
import { SuggestedQuestions } from "@/components/suggested-questions";
import { ValidationFindings } from "@/components/validation-findings";
import { SummaryPanel } from "@/components/summary-panel";
import { deleteReport, getReport } from "@/lib/api";
import { cn, formatDate, formatDateTime, titleCase } from "@/lib/utils";
import type { ReportDetail } from "@/types";

interface Props {
  reportId: string;
  initial: ReportDetail;
}

export function ReportDashboard({ reportId, initial }: Props) {
  const router = useRouter();
  const [report, setReport] = React.useState<ReportDetail>(initial);
  const [tab, setTab] = React.useState("overview");
  const [chatSeed, setChatSeed] = React.useState<string | null>(null);

  const isProcessing = report.status === "processing";
  const isFailed = report.status === "failed";
  const isReady = report.status === "ready";

  // Poll /report/{id} while the backend finishes semantic augmentation +
  // embedding. The initial upload returns in ~5 s with status=processing;
  // typical tail is 30–90 s on a local Ollama + BGE-small stack, but cold
  // starts on a fresh container can stretch to ~3 min. We poll every 2 s
  // and bail out after 3 min / 10 consecutive errors so a dead backend
  // doesn't chew CPU forever.
  React.useEffect(() => {
    if (!isProcessing) return;

    let cancelled = false;
    let consecutiveErrors = 0;
    const startedAt = Date.now();
    const MAX_MS = 3 * 60_000;

    const tick = async () => {
      if (cancelled) return;
      if (Date.now() - startedAt > MAX_MS) {
        toast.error(
          "Processing is taking longer than expected. Try refreshing or re-uploading.",
        );
        return;
      }
      try {
        const fresh = await getReport(reportId);
        if (cancelled) return;
        consecutiveErrors = 0;
        setReport(fresh);
        if (fresh.status === "ready") {
          toast.success("Report ready — chat unlocked");
          return;
        }
        if (fresh.status === "failed") {
          toast.error(fresh.error_message ?? "Processing failed");
          return;
        }
        setTimeout(tick, 2000);
      } catch {
        if (cancelled) return;
        consecutiveErrors += 1;
        if (consecutiveErrors >= 10) {
          toast.error("Lost contact with the backend while polling status.");
          return;
        }
        setTimeout(tick, 2000);
      }
    };

    const t = setTimeout(tick, 2000);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [reportId, isProcessing]);

  const handleAskQuestion = React.useCallback((q: string) => {
    setChatSeed(q);
    setTab("chat");
  }, []);

  const handleDelete = React.useCallback(async () => {
    if (!confirm("Delete this report and all associated chat history? This cannot be undone.")) {
      return;
    }
    try {
      await deleteReport(reportId);
      toast.success("Report deleted");
      router.push("/");
    } catch (e: any) {
      toast.error(e?.message ?? "Failed to delete report");
    }
  }, [reportId, router]);

  return (
    <div className="container py-8">
      <div className="mb-6 flex items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Link href="/" className="hover:text-foreground inline-flex items-center gap-1">
              <ArrowLeft className="h-3.5 w-3.5" />
              Home
            </Link>
            <span>/</span>
            <span className="truncate">{report.filename}</span>
          </div>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight md:text-3xl">
            {report.company_name || "Unknown organization"}
            <span className="ml-2 text-base font-normal text-muted-foreground">
              · {report.report_type || "Unknown report type"}
            </span>
          </h1>
          <div className="mt-1 text-xs text-muted-foreground">
            Uploaded {formatDateTime(report.uploaded_at)} · {report.page_count} pages
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={handleDelete} className="text-red-600 hover:text-red-700 dark:text-red-400">
            <Trash2 className="mr-1.5 h-4 w-4" />
            Delete
          </Button>
        </div>
      </div>

      {isProcessing && (
        <Card className="mb-4 border-amber-500/30 bg-amber-500/5">
          <CardContent className="flex items-start gap-3 p-4">
            <Loader2 className="mt-0.5 h-5 w-5 shrink-0 animate-spin text-amber-600 dark:text-amber-400" />
            <div className="min-w-0">
              <div className="text-sm font-medium">Embedding in progress</div>
              <div className="mt-0.5 text-xs text-muted-foreground">
                Regex validation is done and shown below. Semantic
                augmentation, chunking, and embedding are running in the
                background — usually finishes in under a minute. Chat,
                suggested questions, and summary will unlock automatically.
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {isFailed && (
        <Card className="mb-4 border-red-500/30 bg-red-500/5">
          <CardContent className="flex items-start gap-3 p-4">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-600 dark:text-red-400" />
            <div className="min-w-0">
              <div className="text-sm font-medium">Processing failed</div>
              <div className="mt-0.5 text-xs text-muted-foreground">
                {report.error_message ??
                  "The backend could not finish processing this report. Try deleting and re-uploading."}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <SummaryCards report={report} />

      <div className="mt-8">
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList className="flex w-full flex-wrap">
            <TabsTrigger value="overview">
              <LayoutDashboard className="mr-1.5 h-4 w-4" />
              Overview
            </TabsTrigger>
            <TabsTrigger value="validation">
              <ListChecks className="mr-1.5 h-4 w-4" />
              Validation
              {report.findings.filter((f) => f.severity === "critical").length > 0 && (
                <Badge variant="destructive" className="ml-2">
                  {report.findings.filter((f) => f.severity === "critical").length}
                </Badge>
              )}
            </TabsTrigger>
            <TabsTrigger value="questions" disabled={!isReady}>
              <Sparkles className="mr-1.5 h-4 w-4" />
              Suggested questions
            </TabsTrigger>
            <TabsTrigger value="chat" disabled={!isReady}>
              <MessageSquareMore className="mr-1.5 h-4 w-4" />
              Chat
            </TabsTrigger>
            <TabsTrigger value="summary" disabled={!isReady}>
              <FileText className="mr-1.5 h-4 w-4" />
              Summary
            </TabsTrigger>
          </TabsList>

          <TabsContent value="overview">
            <OverviewTab report={report} />
          </TabsContent>
          <TabsContent value="validation">
            <ValidationFindings report={report} />
          </TabsContent>
          <TabsContent value="questions">
            {isReady ? (
              <SuggestedQuestions reportId={reportId} onAsk={handleAskQuestion} />
            ) : (
              <NotReadyCard />
            )}
          </TabsContent>
          <TabsContent value="chat">
            {isReady ? (
              <ChatInterface
                reportId={reportId}
                seed={chatSeed}
                onSeedConsumed={() => setChatSeed(null)}
              />
            ) : (
              <NotReadyCard />
            )}
          </TabsContent>
          <TabsContent value="summary">
            {isReady ? (
              <SummaryPanel reportId={reportId} report={report} />
            ) : (
              <NotReadyCard />
            )}
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

function NotReadyCard() {
  return (
    <Card className="mt-4">
      <CardContent className="flex items-center gap-3 p-6 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Waiting for embedding to finish before this view becomes available…
      </CardContent>
    </Card>
  );
}

function SummaryCards({ report }: { report: ReportDetail }) {
  const critical = report.findings.filter((f) => f.severity === "critical").length;
  const warnings = report.findings.filter((f) => f.severity === "warning").length;

  const ratingTone = {
    Strong: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20",
    Moderate: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20",
    Weak: "bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20",
    Unknown: "bg-muted text-muted-foreground border-border",
  }[report.risk_rating];

  return (
    <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-5">
      <MetricCard
        icon={Hash}
        label="Type"
        value={report.report_type || "Unknown"}
        hint={report.auditor_firm ? `Auditor: ${report.auditor_firm}` : undefined}
      />
      <MetricCard
        icon={Building2}
        label="Opinion"
        value={titleCase(report.opinion)}
        hint={report.opinion_date ? `Issued ${formatDate(report.opinion_date)}` : "Date unknown"}
      />
      <MetricCard
        icon={CalendarRange}
        label="Coverage"
        value={
          report.coverage_start && report.coverage_end
            ? `${formatDate(report.coverage_start)} → ${formatDate(report.coverage_end)}`
            : "—"
        }
        hint={report.report_age_days != null ? `${report.report_age_days} days since opinion` : undefined}
      />
      <MetricCard
        icon={Gavel}
        label="Findings"
        value={`${critical} critical · ${warnings} warnings`}
        hint={`${report.findings.length} total`}
      />
      <Card className={cn("border-2", ratingTone)}>
        <CardContent className="p-4">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider">
            <Scale className="h-3.5 w-3.5" />
            Risk score
          </div>
          <div className="mt-2 flex items-end justify-between">
            <span className="text-3xl font-semibold tabular-nums">
              {report.risk_score}
              <span className="ml-1 text-sm text-muted-foreground">/ 100</span>
            </span>
            <Badge
              variant={
                report.risk_rating === "Strong"
                  ? "success"
                  : report.risk_rating === "Moderate"
                  ? "warning"
                  : report.risk_rating === "Weak"
                  ? "destructive"
                  : "outline"
              }
            >
              {report.risk_rating}
            </Badge>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function MetricCard({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground">
          <Icon className="h-3.5 w-3.5" />
          {label}
        </div>
        <div className="mt-2 truncate text-base font-semibold" title={value}>
          {value}
        </div>
        {hint && (
          <div className="mt-1 truncate text-xs text-muted-foreground" title={hint}>
            {hint}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
