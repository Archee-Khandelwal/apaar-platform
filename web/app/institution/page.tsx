"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, BadgeCheck, FileSpreadsheet, Flag, Users } from "lucide-react";
import Link from "next/link";

import { PageHeader } from "@/components/AppShell";
import { SeverityBadge } from "@/components/SeverityBadge";
import { StatCard } from "@/components/StatCard";
import { ErrorState, LoadingSkeleton } from "@/components/States";
import { Button, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { Severity } from "@/lib/types";

const CURRENT_YEAR = "2026-27";

function QualityDial({ score }: { score: number | null | undefined }) {
  const value = score ?? 0;
  const tone = value >= 85 ? "text-emerald-600" : value >= 65 ? "text-amber-600" : "text-red-600";
  const circumference = 2 * Math.PI * 42;
  return (
    <div className="relative h-32 w-32">
      <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90">
        <circle cx="50" cy="50" r="42" fill="none" stroke="currentColor" strokeWidth="9" className="text-muted" />
        <circle
          cx="50"
          cy="50"
          r="42"
          fill="none"
          stroke="currentColor"
          strokeWidth="9"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - value / 100)}
          className={tone}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={`text-2xl font-semibold tabular-nums ${tone}`}>
          {score === null || score === undefined ? "—" : score}
        </span>
        <span className="text-xs text-muted-foreground">quality</span>
      </div>
    </div>
  );
}

export default function InstitutionDashboardPage() {
  const profile = useQuery({ queryKey: ["institution-me"], queryFn: api.institutionMe });
  const dashboard = useQuery({
    queryKey: ["institution-dashboard", CURRENT_YEAR],
    queryFn: () => api.institutionDashboard(CURRENT_YEAR),
  });

  if (dashboard.isError) return <ErrorState error={dashboard.error} onRetry={dashboard.refetch} />;

  const data = dashboard.data;
  const flags = data?.open_flags ?? { low: 0, medium: 0, high: 0, critical: 0 };
  const openTotal = Object.values(flags).reduce((sum, value) => sum + value, 0);
  const seats = data?.seat_matrix_summary;

  return (
    <>
      <PageHeader
        title={profile.data?.name ?? "Institution dashboard"}
        description={
          profile.data
            ? `${profile.data.state} · AICTE permanent id ${profile.data.aicte_permanent_id} · ${profile.data.programs.length} approved programmes`
            : "Loading your institution…"
        }
        actions={
          <Button asChild>
            <Link href="/institution/upload">
              <FileSpreadsheet className="h-4 w-4" />
              Upload student data
            </Link>
          </Button>
        }
      />

      {dashboard.isLoading ? (
        <LoadingSkeleton rows={6} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="Students reported"
              value={data?.students_reported ?? 0}
              hint={`${CURRENT_YEAR} · active enrolments`}
              icon={<Users className="h-4 w-4" />}
            />
            <StatCard
              label="Open findings"
              value={openTotal}
              hint={
                openTotal === 0
                  ? "Nothing outstanding"
                  : `${flags.critical} critical · ${flags.high} high · ${flags.medium} medium`
              }
              tone={flags.critical > 0 ? "danger" : flags.high > 0 ? "warning" : "success"}
              icon={<Flag className="h-4 w-4" />}
            />
            <StatCard
              label="Approved intake"
              value={seats?.approved_intake ?? 0}
              hint={`${seats?.regular_admitted ?? 0} regular admitted`}
            />
            <StatCard
              label="Excess seats"
              value={seats?.excess ?? 0}
              hint={
                (seats?.excess ?? 0) > 0
                  ? "Beyond intake and valid supernumerary"
                  : "Within approved intake"
              }
              tone={(seats?.excess ?? 0) > 0 ? "danger" : "success"}
              icon={<AlertTriangle className="h-4 w-4" />}
            />
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle>Data quality</CardTitle>
              </CardHeader>
              <CardContent className="flex items-center gap-4">
                <QualityDial score={data?.latest_quality_score} />
                <div className="min-w-0 text-sm">
                  <p className="text-muted-foreground">
                    Score of your most recent upload. It falls with rejected rows, warnings and
                    missing columns we need for detection.
                  </p>
                  {data?.quality_trend && data.quality_trend.length > 1 && (
                    <div className="mt-3 flex items-end gap-1" aria-label="Quality score trend">
                      {data.quality_trend.map((point) => (
                        <div
                          key={point.upload_id}
                          title={`Upload #${point.upload_id}: ${point.quality_score ?? "—"}`}
                          className="w-4 rounded-t bg-accent/70"
                          style={{ height: `${Math.max(((point.quality_score ?? 0) / 100) * 56, 4)}px` }}
                        />
                      ))}
                    </div>
                  )}
                  <p className="mt-2 text-xs text-muted-foreground">
                    Last upload {dateTime(data?.last_upload_at)}
                  </p>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Open findings by severity</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {(["critical", "high", "medium", "low"] as Severity[]).map((severity) => (
                  <div key={severity} className="flex items-center justify-between gap-2">
                    <SeverityBadge severity={severity} />
                    <span className="text-sm font-medium tabular-nums">{flags[severity]}</span>
                  </div>
                ))}
                <Button asChild variant="outline" size="sm" className="mt-2 w-full">
                  <Link href="/institution/flags">Open the flag inbox</Link>
                </Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Compliance certificate</CardTitle>
              </CardHeader>
              <CardContent>
                {data?.compliance_certificate_eligible ? (
                  <>
                    <p className="flex items-center gap-2 text-sm text-emerald-700">
                      <BadgeCheck className="h-4 w-4" />
                      Eligible for {CURRENT_YEAR}
                    </p>
                    <Button asChild size="sm" className="mt-3">
                      <Link href="/institution/certificate">View certificate</Link>
                    </Button>
                  </>
                ) : (
                  <>
                    <p className="text-sm text-muted-foreground">Not available yet:</p>
                    <ul className="mt-2 space-y-1 text-sm">
                      {(data?.compliance_certificate_reasons ?? []).map((reason) => (
                        <li key={reason} className="flex items-start gap-1.5">
                          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />
                          {reason}
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </>
  );
}
