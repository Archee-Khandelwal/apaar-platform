"use client";

import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  BadgeCheck,
  CheckCircle2,
  FileSpreadsheet,
  Flag,
  Users,
} from "lucide-react";
import Link from "next/link";

import { SeverityBadge } from "@/components/SeverityBadge";
import { ErrorState, KpiSkeleton, Skeleton } from "@/components/States";
import { KpiCard, KpiRow, PageHeader, SectionCard } from "@/components/ui/page";
import { Button } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime, flagLabel } from "@/lib/format";
import type { InstitutionFlag, Severity } from "@/lib/types";
import { cn } from "@/lib/utils";

const CURRENT_YEAR = "2026-27";

/** A horizontal stack showing how the admitted seats sit against approved intake. */
function SeatSummaryChart({
  intake,
  regular,
  supernumerary,
  excess,
}: {
  intake: number;
  regular: number;
  supernumerary: number;
  excess: number;
}) {
  const scale = Math.max(intake, regular + supernumerary + excess, 1);
  const width = (value: number) => `${(value / scale) * 100}%`;
  const segments = [
    { label: "Regular admitted", value: regular, className: "bg-primary" },
    { label: "Valid supernumerary", value: supernumerary, className: "bg-sky-400" },
    { label: "Excess", value: excess, className: "bg-severity-critical" },
  ].filter((segment) => segment.value > 0);

  return (
    <div className="space-y-4">
      <div className="relative h-9 w-full overflow-hidden rounded-md bg-secondary">
        <div className="flex h-full">
          {segments.map((segment) => (
            <div
              key={segment.label}
              className={cn("h-full", segment.className)}
              style={{ width: width(segment.value) }}
              title={`${segment.label}: ${segment.value}`}
            />
          ))}
        </div>
        {/* The approved-intake line is the thing a college actually watches. */}
        <div
          className="absolute inset-y-0 z-10 w-0.5 bg-slate-900"
          style={{ left: width(intake) }}
          aria-hidden
        />
      </div>

      <ul className="flex flex-wrap gap-x-5 gap-y-2 text-xs">
        {segments.map((segment) => (
          <li key={segment.label} className="inline-flex items-center gap-1.5">
            <span className={cn("h-2.5 w-2.5 rounded-sm", segment.className)} />
            <span className="text-muted-foreground">{segment.label}</span>
            <span className="font-semibold tabular-nums">{segment.value}</span>
          </li>
        ))}
        <li className="inline-flex items-center gap-1.5">
          <span className="h-3.5 w-0.5 bg-slate-900" />
          <span className="text-muted-foreground">Approved intake</span>
          <span className="font-semibold tabular-nums">{intake}</span>
        </li>
      </ul>
    </div>
  );
}

/** One row of the "Needs your attention" list: what happened, and what to do. */
function AttentionRow({
  severity,
  title,
  detail,
  action,
}: {
  severity?: Severity;
  title: string;
  detail: string;
  action: { label: string; href: string };
}) {
  return (
    <li className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3 py-4 first:pt-0 last:pb-0">
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          {severity && <SeverityBadge severity={severity} />}
          <p className="text-sm font-medium">{title}</p>
        </div>
        <p className="text-sm leading-relaxed text-muted-foreground">{detail}</p>
      </div>
      <Button asChild size="sm" variant="outline" className="shrink-0">
        <Link href={action.href}>
          {action.label}
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </Button>
    </li>
  );
}

export default function InstitutionDashboardPage() {
  const profile = useQuery({ queryKey: ["institution-me"], queryFn: api.institutionMe });
  const dashboard = useQuery({
    queryKey: ["institution-dashboard", CURRENT_YEAR],
    queryFn: () => api.institutionDashboard(CURRENT_YEAR),
  });
  const openFlags = useQuery({
    queryKey: ["institution-flags", "attention"],
    queryFn: () => api.institutionFlags({ page: 1, page_size: 5, status: "open", sort: "-severity" }),
  });

  if (dashboard.isError) return <ErrorState error={dashboard.error} onRetry={dashboard.refetch} />;

  const data = dashboard.data;
  const flags = data?.open_flags ?? { low: 0, medium: 0, high: 0, critical: 0 };
  const openTotal = Object.values(flags).reduce((sum, value) => sum + value, 0);
  const seats = data?.seat_matrix_summary;
  const quality = data?.latest_quality_score;
  const topFlags: InstitutionFlag[] = openFlags.data?.items ?? [];
  // Five rows of "APAAR not found" is noise; one row saying "5 students" is a task.
  const groupedFlags = Array.from(
    topFlags
      .reduce((groups, flag) => {
        const existing = groups.get(flag.type);
        if (existing) existing.count += 1;
        else groups.set(flag.type, { flag, count: 1 });
        return groups;
      }, new Map<string, { flag: InstitutionFlag; count: number }>())
      .values(),
  );

  const qualityTone =
    quality === null || quality === undefined
      ? "default"
      : quality >= 85
        ? "positive"
        : quality >= 65
          ? "warning"
          : "critical";

  return (
    <>
      <PageHeader
        title="Dashboard"
        description={
          profile.data
            ? `What ${profile.data.name} has reported for ${CURRENT_YEAR}, and what still needs your attention.`
            : "What your institution has reported this year, and what still needs your attention."
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
        <>
          <KpiSkeleton />
          <Skeleton rows={4} height="h-24" />
        </>
      ) : (
        <>
          <KpiRow>
            <KpiCard
              label="Students reported"
              value={data?.students_reported ?? 0}
              hint={`Active enrolments for ${CURRENT_YEAR}`}
              icon={<Users className="h-4 w-4" />}
            />
            <KpiCard
              label="Data quality score"
              value={quality ?? "—"}
              hint={
                data?.last_upload_at
                  ? `Your latest upload, ${dateTime(data.last_upload_at)}`
                  : "No upload yet this year"
              }
              tone={qualityTone}
              icon={<FileSpreadsheet className="h-4 w-4" />}
            />
            <KpiCard
              label="Open flags"
              value={openTotal}
              hint={
                openTotal === 0
                  ? "Nothing outstanding"
                  : `${flags.critical} critical · ${flags.high} high · ${flags.medium} medium · ${flags.low} low`
              }
              tone={flags.critical > 0 ? "critical" : flags.high > 0 ? "warning" : "positive"}
              icon={<Flag className="h-4 w-4" />}
            />
            <KpiCard
              label="Seats status"
              value={(seats?.excess ?? 0) === 0 ? "Within limits" : `${seats?.excess} excess`}
              hint={`${seats?.total_admitted ?? 0} admitted against ${seats?.approved_intake ?? 0} approved intake`}
              tone={(seats?.excess ?? 0) > 0 ? "critical" : "positive"}
              icon={<AlertTriangle className="h-4 w-4" />}
            />
          </KpiRow>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <SectionCard
              title="Seats against approved intake"
              description="Supernumerary seats sit outside approved intake, each with its own cap."
              className="lg:col-span-2"
              actions={
                <Button asChild size="sm" variant="outline">
                  <Link href="/institution/seat-matrix">Open seat matrix</Link>
                </Button>
              }
            >
              {seats ? (
                <SeatSummaryChart
                  intake={seats.approved_intake}
                  regular={seats.regular_admitted}
                  supernumerary={seats.valid_supernumerary}
                  excess={seats.excess}
                />
              ) : (
                <p className="text-sm text-muted-foreground">
                  No approved intake on record for {CURRENT_YEAR}.
                </p>
              )}
            </SectionCard>

            <SectionCard title="Compliance certificate">
              {data?.compliance_certificate_eligible ? (
                <div className="space-y-4">
                  <p className="flex items-start gap-2 text-sm font-medium text-emerald-700">
                    <BadgeCheck className="mt-0.5 h-4 w-4 shrink-0" />
                    Eligible for {CURRENT_YEAR}
                  </p>
                  <p className="text-sm leading-relaxed text-muted-foreground">
                    No high or critical finding is open against you for this year.
                  </p>
                  <Button asChild size="sm" className="w-full">
                    <Link href="/institution/certificate">View certificate</Link>
                  </Button>
                </div>
              ) : (
                <div className="space-y-4">
                  <p className="flex items-start gap-2 text-sm font-medium text-amber-700">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                    Not available yet
                  </p>
                  <ul className="space-y-2 text-sm leading-relaxed text-muted-foreground">
                    {(data?.compliance_certificate_reasons ?? []).map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                  <Button asChild size="sm" variant="outline" className="w-full">
                    <Link href="/institution/certificate">What is blocking it</Link>
                  </Button>
                </div>
              )}
            </SectionCard>
          </div>

          <SectionCard
            title="Needs your attention"
            description="The next things to act on, most serious first."
            actions={
              <Button asChild size="sm" variant="outline">
                <Link href="/institution/flags">All flags</Link>
              </Button>
            }
          >
            {openFlags.isLoading ? (
              <Skeleton rows={3} height="h-16" />
            ) : (
              <ul className="divide-y divide-border">
                {(seats?.excess ?? 0) > 0 && (
                  <AttentionRow
                    severity="high"
                    title={`${seats!.excess} admissions beyond approved intake`}
                    detail="Cancel or reclassify the extra admissions, or record the supernumerary category they belong to. The seat matrix shows which programme is over."
                    action={{ label: "Open seat matrix", href: "/institution/seat-matrix" }}
                  />
                )}
                {groupedFlags.map(({ flag, count: repeats }) => (
                  <AttentionRow
                    key={flag.id}
                    severity={flag.severity}
                    title={repeats > 1 ? `${flagLabel(flag.type)} — ${repeats} findings` : flag.title}
                    detail={flag.explanation}
                    action={{ label: "Open flags", href: "/institution/flags" }}
                  />
                ))}
                {(quality ?? 100) < 85 && (
                  <AttentionRow
                    severity="medium"
                    title={`Data quality is ${quality}`}
                    detail="Rejected rows, warnings and missing columns pull this score down. Fix the rows listed in your last upload report and submit again."
                    action={{ label: "Upload again", href: "/institution/upload" }}
                  />
                )}
                {groupedFlags.length === 0 && (seats?.excess ?? 0) === 0 && (quality ?? 100) >= 85 && (
                  <li className="flex items-start gap-2 py-2 text-sm text-emerald-700">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                    Nothing outstanding. Your data for {CURRENT_YEAR} is reported and clean.
                  </li>
                )}
              </ul>
            )}
          </SectionCard>
        </>
      )}
    </>
  );
}
