"use client";

/** Institution drill-down: profile, risk gauge with its three reasons, seats, findings. */
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, FileSpreadsheet } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { PageHeader } from "@/components/AppShell";
import { SeverityBadge, StatusBadge } from "@/components/SeverityBadge";
import { StatCard } from "@/components/StatCard";
import { ErrorState, LoadingSkeleton } from "@/components/States";
import { Button, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime, flagLabel } from "@/lib/format";
import type { Severity } from "@/lib/types";
import { cn } from "@/lib/utils";

const BAND_COLOUR: Record<Severity, string> = {
  low: "text-slate-500",
  medium: "text-amber-500",
  high: "text-orange-500",
  critical: "text-red-600",
};

function RiskGauge({ score, band }: { score: number; band: Severity }) {
  const circumference = Math.PI * 44; // half circle
  return (
    <div className="relative h-28 w-48">
      <svg viewBox="0 0 100 56" className="h-full w-full">
        <path
          d="M6 50 A44 44 0 0 1 94 50"
          fill="none"
          stroke="currentColor"
          strokeWidth="8"
          strokeLinecap="round"
          className="text-muted"
        />
        <path
          d="M6 50 A44 44 0 0 1 94 50"
          fill="none"
          stroke="currentColor"
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - score / 100)}
          className={BAND_COLOUR[band]}
        />
      </svg>
      <div className="absolute inset-x-0 bottom-0 text-center">
        <p className={cn("text-3xl font-semibold tabular-nums", BAND_COLOUR[band])}>
          {score.toFixed(0)}
        </p>
        <p className="text-xs uppercase tracking-wide text-muted-foreground">{band} risk</p>
      </div>
    </div>
  );
}

export default function InstitutionProfilePage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const query = useQuery({
    queryKey: ["aicte-institution", id],
    queryFn: () => api.institution(id),
    enabled: Number.isFinite(id),
  });
  const seatMatrix = useQuery({
    queryKey: ["aicte-institution-seats", id],
    queryFn: () => api.institutionSeatMatrix(id, "2026-27"),
    enabled: Number.isFinite(id),
  });

  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;
  if (query.isLoading || !query.data) return <LoadingSkeleton rows={8} />;

  const { institution, risk, reporting, seat_matrix_summary, flags, upload_timeline } = query.data;

  return (
    <>
      <Button asChild variant="ghost" size="sm" className="mb-2 px-0">
        <Link href="/aicte/institutions">
          <ArrowLeft className="h-3.5 w-3.5" />
          All institutions
        </Link>
      </Button>

      <PageHeader
        title={institution.name}
        description={`${institution.state} · ${institution.region} · ${institution.type.replace(/_/g, " ")} · AICTE permanent id ${institution.aicte_permanent_id}`}
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Risk score</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex justify-center">
              <RiskGauge score={risk.score} band={risk.band} />
            </div>
            <div className="mt-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Top reasons
              </p>
              <ol className="mt-1.5 space-y-1.5 text-sm">
                {risk.reasons.map((reason, index) => (
                  <li key={index} className="flex gap-2">
                    <span className="text-muted-foreground">{index + 1}.</span>
                    <span>{reason}</span>
                  </li>
                ))}
              </ol>
              <p className="mt-2 text-xs text-muted-foreground">
                {risk.components.flags.toFixed(1)} from open findings ·{" "}
                {risk.components.anomaly.toFixed(1)} from the statistical model
              </p>
            </div>
          </CardContent>
        </Card>

        <div className="grid content-start gap-3 lg:col-span-2 sm:grid-cols-2">
          <StatCard label="Students reported" value={reporting.students_reported} hint="2026-27" />
          <StatCard
            label="Uploads"
            value={reporting.uploads}
            hint={`last ${dateTime(reporting.last_upload_at)}`}
          />
          <StatCard
            label="Average quality"
            value={reporting.avg_quality_score ?? "—"}
            hint="across their uploads"
          />
          <StatCard
            label="Excess seats"
            value={seat_matrix_summary.excess}
            tone={seat_matrix_summary.excess > 0 ? "danger" : "success"}
            hint={`${seat_matrix_summary.approved_intake} approved intake`}
          />
        </div>
      </div>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>Open and past findings ({flags.length})</CardTitle>
        </CardHeader>
        <CardContent>
          {flags.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Nothing has been flagged against this institution.
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {flags.map((flag) => (
                <li key={flag.id} className="flex flex-wrap items-start gap-3 py-2.5">
                  <SeverityBadge severity={flag.severity} />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">
                      {flagLabel(flag.type)} — {flag.title}
                    </p>
                    <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                      {flag.explanation}
                    </p>
                  </div>
                  <StatusBadge status={flag.status} />
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {seatMatrix.data && seatMatrix.data.programs.length > 0 && (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle>Seat matrix 2026-27</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="py-1.5 text-left font-semibold">Programme</th>
                    <th className="py-1.5 text-right font-semibold">Intake</th>
                    <th className="py-1.5 text-right font-semibold">Regular</th>
                    <th className="py-1.5 text-right font-semibold">Valid supernumerary</th>
                    <th className="py-1.5 text-right font-semibold">Excess</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {seatMatrix.data.programs.map((program) => (
                    <tr key={program.program_id}>
                      <td className="py-1.5">
                        {program.course} {program.branch}
                        {program.mode === "online" && (
                          <span className="ml-1 text-xs text-muted-foreground">(online)</span>
                        )}
                      </td>
                      <td className="py-1.5 text-right tabular-nums">{program.approved_intake}</td>
                      <td className="py-1.5 text-right tabular-nums">{program.regular_admitted}</td>
                      <td className="py-1.5 text-right tabular-nums">{program.valid_supernumerary}</td>
                      <td
                        className={cn(
                          "py-1.5 text-right tabular-nums",
                          program.excess > 0 && "font-semibold text-red-700",
                        )}
                      >
                        {program.excess}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {upload_timeline.length > 0 && (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle>Reporting timeline</CardTitle>
          </CardHeader>
          <CardContent>
            <ol className="space-y-2">
              {upload_timeline.map((upload) => (
                <li key={upload.upload_id} className="flex flex-wrap items-center gap-3 text-sm">
                  <FileSpreadsheet className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <span className="font-medium">{upload.filename}</span>
                  <span className="text-xs text-muted-foreground">{dateTime(upload.created_at)}</span>
                  <span className="text-xs">
                    {upload.rows_ok} accepted
                    {upload.rows_error > 0 && `, ${upload.rows_error} rejected`}
                  </span>
                  {upload.quality_score !== null && upload.quality_score !== undefined && (
                    <span className="ml-auto rounded bg-muted px-2 py-0.5 text-xs tabular-nums">
                      quality {upload.quality_score}
                    </span>
                  )}
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      )}
    </>
  );
}
