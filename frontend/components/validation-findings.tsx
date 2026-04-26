"use client";

import * as React from "react";
import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  Info,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn, humanReadableSeverity } from "@/lib/utils";
import type { ReportDetail, Severity } from "@/types";

const ORDER: Severity[] = ["critical", "warning", "info", "ok"];

const TONES: Record<
  Severity,
  {
    icon: React.ComponentType<{ className?: string }>;
    bg: string;
    text: string;
    label: string;
    badge: "destructive" | "warning" | "info" | "success";
  }
> = {
  critical: {
    icon: AlertOctagon,
    bg: "bg-red-500/10 border-red-500/20",
    text: "text-red-600 dark:text-red-400",
    label: "Critical",
    badge: "destructive",
  },
  warning: {
    icon: AlertTriangle,
    bg: "bg-amber-500/10 border-amber-500/20",
    text: "text-amber-600 dark:text-amber-400",
    label: "Warning",
    badge: "warning",
  },
  info: {
    icon: Info,
    bg: "bg-sky-500/10 border-sky-500/20",
    text: "text-sky-600 dark:text-sky-400",
    label: "Info",
    badge: "info",
  },
  ok: {
    icon: CheckCircle2,
    bg: "bg-emerald-500/10 border-emerald-500/20",
    text: "text-emerald-600 dark:text-emerald-400",
    label: "OK",
    badge: "success",
  },
};

export function ValidationFindings({ report }: { report: ReportDetail }) {
  const grouped = React.useMemo(() => {
    const out: Record<Severity, typeof report.findings> = {
      critical: [],
      warning: [],
      info: [],
      ok: [],
    };
    for (const f of report.findings) {
      (out[f.severity] ??= []).push(f);
    }
    return out;
  }, [report.findings]);

  const totals = {
    critical: grouped.critical.length,
    warning: grouped.warning.length,
    info: grouped.info.length,
    ok: grouped.ok.length,
  };

  return (
    <div className="space-y-6">
      <div className="grid gap-3 md:grid-cols-4">
        {ORDER.map((sev) => {
          const tone = TONES[sev];
          const Icon = tone.icon;
          return (
            <Card key={sev} className={cn("border", tone.bg)}>
              <CardContent className="flex items-center justify-between p-4">
                <div>
                  <div className="text-xs uppercase tracking-wider text-muted-foreground">
                    {tone.label}
                  </div>
                  <div className="mt-1 text-2xl font-semibold tabular-nums">
                    {totals[sev]}
                  </div>
                </div>
                <Icon className={cn("h-6 w-6", tone.text)} />
              </CardContent>
            </Card>
          );
        })}
      </div>

      <div className="space-y-4">
        {ORDER.map((sev) => {
          const items = grouped[sev];
          if (items.length === 0) return null;
          const tone = TONES[sev];
          return (
            <div key={sev} className="space-y-2">
              <div className="flex items-center gap-2">
                <h3 className={cn("text-sm font-semibold", tone.text)}>
                  {humanReadableSeverity(sev)}
                </h3>
                <Badge variant={tone.badge}>{items.length}</Badge>
              </div>
              <div className="grid gap-3">
                {items.map((f) => {
                  const Icon = TONES[f.severity].icon;
                  return (
                    <Card key={f.code} className={cn("border-l-4", tone.bg, "border-l-current", tone.text)}>
                      <CardHeader className="pb-2">
                        <CardTitle className="flex items-center gap-2 text-sm text-foreground">
                          <Icon className={cn("h-4 w-4 shrink-0", tone.text)} />
                          {f.title}
                          <Badge variant="outline" className="ml-auto text-[10px] font-mono">
                            {f.code}
                          </Badge>
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="pt-0 text-sm text-muted-foreground">
                        {f.detail}
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            </div>
          );
        })}
        {report.findings.length === 0 && (
          <Card>
            <CardContent className="p-6 text-center text-sm text-muted-foreground">
              No validation findings produced — the validation engine didn&apos;t return any output.
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
