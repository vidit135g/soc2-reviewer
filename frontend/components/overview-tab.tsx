"use client";

import {
  Building2,
  CalendarDays,
  CheckCircle2,
  ExternalLink,
  Fingerprint,
  Gauge,
  ListTree,
  Shield,
  XCircle,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { cn, formatDate, titleCase } from "@/lib/utils";
import type {
  CategoryScore,
  CUECDetail,
  FieldConfidence,
  FieldConfidenceLevel,
  ReportDetail,
} from "@/types";

const ALL_SECTIONS: { key: string; label: string }[] = [
  { key: "independent_auditor_report", label: "Independent auditor report" },
  { key: "management_assertion", label: "Management assertion" },
  { key: "system_description", label: "System description" },
  { key: "controls_and_tests", label: "Controls & tests" },
  { key: "results_and_exceptions", label: "Results / exceptions" },
  { key: "complementary_user_entity_controls", label: "CUECs" },
  { key: "subservice_organizations", label: "Subservice orgs" },
];

// Friendlier names for each category in the score breakdown.
const CATEGORY_LABELS: Record<string, string> = {
  metadata_completeness: "Metadata completeness",
  coverage_quality: "Coverage quality",
  control_transparency: "Control transparency",
  opinion_strength: "Opinion strength",
  structure_quality: "Structure quality",
};

export function OverviewTab({ report }: { report: ReportDetail }) {
  const md = report.metadata;
  const fc = report.field_confidence ?? {};
  const cuecDetails = report.cuec_details ?? [];

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Fingerprint className="h-4 w-4 text-primary" />
            Identification
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <Field
            label="Company"
            value={md.company_name}
            confidence={fc.company_name}
          />
          <Field
            label="Auditor"
            value={md.auditor_firm}
            confidence={fc.auditor_firm}
          />
          <Field
            label="Report type"
            value={md.report_type}
            confidence={fc.report_type}
          />
          <Field
            label="Opinion"
            value={titleCase(md.opinion)}
            confidence={fc.opinion}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CalendarDays className="h-4 w-4 text-primary" />
            Dates
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <Field
            label="Opinion date"
            value={formatDate(md.opinion_date)}
            confidence={fc.opinion_date}
          />
          <Field
            label="Coverage start"
            value={formatDate(md.coverage_start)}
            confidence={fc.coverage_start}
          />
          <Field
            label="Coverage end"
            value={formatDate(md.coverage_end)}
            confidence={fc.coverage_end}
          />
          <Field
            label="Age since opinion"
            value={
              report.report_age_days != null
                ? `${report.report_age_days} days`
                : "—"
            }
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Shield className="h-4 w-4 text-primary" />
            Trust Service Criteria
          </CardTitle>
        </CardHeader>
        <CardContent>
          {md.trust_service_criteria.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No criteria were detected from the report text.
            </p>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              {md.trust_service_criteria.map((c) => (
                <Badge key={c} variant="success">
                  {c}
                </Badge>
              ))}
              <ConfidencePill confidence={fc.trust_service_criteria} />
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Building2 className="h-4 w-4 text-primary" />
            Subservice organizations
          </CardTitle>
        </CardHeader>
        <CardContent>
          {md.subservice_organizations.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No subservice organizations were identified.
            </p>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              {md.subservice_organizations.map((c) => (
                <Badge key={c} variant="info">
                  {c}
                </Badge>
              ))}
              <ConfidencePill confidence={fc.subservice_organizations} />
            </div>
          )}
        </CardContent>
      </Card>

      <CategoryScoreCard report={report} />

      <Card className="md:col-span-2">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ExternalLink className="h-4 w-4 text-primary" />
            Report sections
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-2 sm:grid-cols-2 md:grid-cols-3">
            {ALL_SECTIONS.map((s) => {
              const present = md.sections_present.includes(s.key);
              return (
                <div
                  key={s.key}
                  className="flex items-center gap-2 rounded-lg border bg-card/70 px-3 py-2 text-sm"
                >
                  {present ? (
                    <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                  ) : (
                    <XCircle className="h-4 w-4 text-red-500" />
                  )}
                  <span className={present ? "" : "text-muted-foreground"}>
                    {s.label}
                  </span>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {cuecDetails.length > 0 && (
        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ListTree className="h-4 w-4 text-primary" />
              Complementary User Entity Controls
              <Badge variant="outline" className="ml-auto">
                {cuecDetails.length}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {cuecDetails.map((c, idx) => (
                <CUECRow key={idx} item={c} />
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {md.exceptions_summary && (
        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Exceptions summary
              <ConfidencePill confidence={fc.exceptions_summary} />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">{md.exceptions_summary}</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Field({
  label,
  value,
  confidence,
}: {
  label: string;
  value?: string | null;
  confidence?: FieldConfidence;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-muted-foreground">{label}</span>
      <span className="flex min-w-0 items-center gap-2">
        <span className="truncate font-medium" title={value || undefined}>
          {value || "—"}
        </span>
        <ConfidencePill confidence={confidence} />
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Confidence pill — tiny colored badge with hover tooltip showing method +
// evidence excerpt + page number when available.
// ---------------------------------------------------------------------------

const PILL_TONE: Record<FieldConfidenceLevel, string> = {
  high: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20",
  medium: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20",
  low: "bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20",
  none: "bg-muted text-muted-foreground border-border",
};

const PILL_LABEL: Record<FieldConfidenceLevel, string> = {
  high: "High",
  medium: "Med",
  low: "Low",
  none: "?",
};

function ConfidencePill({ confidence }: { confidence?: FieldConfidence }) {
  if (!confidence) return null;
  const level = confidence.confidence;
  // Compose a single human-readable tooltip — `title` keeps the badge
  // tooltip-only without pulling in a Radix provider for one read-only
  // surface.
  const parts: string[] = [];
  parts.push(`Confidence: ${level}`);
  if (confidence.method) parts.push(`Method: ${confidence.method}`);
  if (confidence.page_number != null) parts.push(`Page ${confidence.page_number}`);
  if (confidence.evidence) parts.push(`"${confidence.evidence}"`);
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full border px-1.5 py-0 text-[10px] font-medium uppercase tracking-wide",
        PILL_TONE[level],
      )}
      title={parts.join(" · ")}
    >
      {PILL_LABEL[level]}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Score breakdown card — renders the 5 weighted categories with progress
// bars + reasons on hover.
// ---------------------------------------------------------------------------

function CategoryScoreCard({ report }: { report: ReportDetail }) {
  const cats = report.category_scores ?? {};
  const entries = Object.entries(cats);
  if (entries.length === 0) {
    // Don't render the card at all on legacy rows that pre-date the
    // 5-category score breakdown.
    return null;
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Gauge className="h-4 w-4 text-primary" />
          Score breakdown
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {entries.map(([key, cat]) => (
          <CategoryRow key={key} name={key} cat={cat} />
        ))}
      </CardContent>
    </Card>
  );
}

function CategoryRow({ name, cat }: { name: string; cat: CategoryScore }) {
  const label = CATEGORY_LABELS[name] ?? titleCase(name.replace(/_/g, " "));
  const pct = Math.round((cat.ratio ?? 0) * 100);
  const tone =
    pct >= 80
      ? "bg-emerald-500"
      : pct >= 55
        ? "bg-amber-500"
        : "bg-red-500";
  return (
    <div title={cat.reasons.length ? cat.reasons.join("\n") : undefined}>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="font-medium">{label}</span>
        <span className="tabular-nums text-muted-foreground">
          {cat.points.toFixed(1)} / {cat.weight}
        </span>
      </div>
      <Progress value={pct} className="h-1.5" indicatorClassName={tone} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Single CUEC row with page-number chip + heading subtitle.
// ---------------------------------------------------------------------------

function CUECRow({ item }: { item: CUECDetail }) {
  return (
    <li className="rounded-lg border bg-card/70 px-3 py-2 text-sm">
      <div className="flex items-start gap-2">
        <span className="flex-1">{item.text}</span>
        {item.page_number != null && (
          <Badge variant="outline" className="shrink-0">
            p. {item.page_number}
          </Badge>
        )}
      </div>
      {item.heading && (
        <div className="mt-1 truncate text-xs text-muted-foreground">
          under {item.heading}
        </div>
      )}
    </li>
  );
}
