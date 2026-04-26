import { notFound } from "next/navigation";

import { ReportDashboard } from "@/components/report-dashboard";

async function fetchReport(id: string) {
  const base = process.env.BACKEND_URL || "http://backend:8000";
  try {
    const res = await fetch(`${base}/api/report/${id}`, { cache: "no-store" });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const report = await fetchReport(id);
  return {
    title: report?.company_name
      ? `${report.company_name} — SOC 2 assessment`
      : "Report assessment",
  };
}

export default async function ReportPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const initial = await fetchReport(id);
  if (!initial) return notFound();
  return <ReportDashboard reportId={id} initial={initial} />;
}
