"use client";

/** Institution drill-down: profile, seats, findings and reporting history. */
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, FileSpreadsheet } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { SeverityBadge, StatusBadge } from "@/components/SeverityBadge";
import { ErrorState, Skeleton } from "@/components/States";
import { KpiCard, KpiRow, PageHeader, SectionCard } from "@/components/ui/page";
import { Button } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime, flagLabel } from "@/lib/format";
import { cn } from "@/lib/utils";

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
  if (query.isLoading || !query.data) return <Skeleton rows={6} height="h-28" />;

  const { institution, reporting, seat_matrix_summary, flags, upload_timeline } = query.data;
  const openFlags = flags.filter((flag) => !["resolved", "dismissed"].includes(flag.status));

  return (
    <>
      <div>
        <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2">
          <Link href="/aicte/institutions">
            <ArrowLeft className="h-3.5 w-3.5" />
            All institutions
          </Link>
        </Button>
        <PageHeader
          title={institution.name}
          description={`${institution.state} · ${institution.region} · ${institution.type.replace(/_/g, " ")} · AICTE permanent id ${institution.aicte_permanent_id}`}
        />
      </div>

      <KpiRow>
        <KpiCard
          label="Students reported"
          value={reporting.students_reported}
          hint="Active enrolments for 2026-27"
        />
        <KpiCard
          label="Uploads"
          value={reporting.uploads}
          hint={`Last filed ${dateTime(reporting.last_upload_at)}`}
        />
        <KpiCard
          label="Average data quality"
          value={reporting.avg_quality_score ?? "—"}
          hint="Across every upload they have made"
          tone={
            reporting.avg_quality_score === null || reporting.avg_quality_score === undefined
              ? "default"
              : reporting.avg_quality_score >= 85
                ? "positive"
                : reporting.avg_quality_score >= 65
                  ? "warning"
                  : "critical"
          }
        />
        <KpiCard
          label="Excess seats"
          value={seat_matrix_summary.excess}
          tone={seat_matrix_summary.excess > 0 ? "critical" : "positive"}
          hint={`Against ${seat_matrix_summary.approved_intake} approved intake`}
        />
      </KpiRow>

      <SectionCard
        title={`Findings (${openFlags.length} open of ${flags.length})`}
        description="Plain-English title first; open the flag queue for the full evidence."
        bodyClassName="p-0"
      >
        {flags.length === 0 ? (
          <p className="p-5 text-sm text-muted-foreground">
            Nothing has been flagged against this institution.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {flags.map((flag) => (
              <li key={flag.id} className="flex flex-wrap items-start gap-x-3 gap-y-2 px-5 py-4">
                <SeverityBadge severity={flag.severity} />
                <div className="min-w-0 flex-1 space-y-1">
                  <p className="text-sm font-medium leading-snug">
                    {flagLabel(flag.type)} — {flag.title}
                  </p>
                  <p className="text-xs leading-relaxed text-muted-foreground">{flag.explanation}</p>
                </div>
                <StatusBadge status={flag.status} />
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      {seatMatrix.data && seatMatrix.data.programs.length > 0 && (
        <SectionCard title="Seat matrix 2026-27" bodyClassName="p-0">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[36rem] text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/60">
                  <th className="px-5 py-3 text-left type-label">Programme</th>
                  <th className="px-4 py-3 text-right type-label">Intake</th>
                  <th className="px-4 py-3 text-right type-label">Regular</th>
                  <th className="px-4 py-3 text-right type-label">Valid supernumerary</th>
                  <th className="px-5 py-3 text-right type-label">Excess</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {seatMatrix.data.programs.map((program) => (
                  <tr key={program.program_id}>
                    <td className="px-5 py-2.5">
                      {program.course} {program.branch}
                      {program.mode === "online" && (
                        <span className="ml-1 text-xs text-muted-foreground">(online)</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{program.approved_intake}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{program.regular_admitted}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{program.valid_supernumerary}</td>
                    <td
                      className={cn(
                        "px-5 py-2.5 text-right tabular-nums",
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
        </SectionCard>
      )}

      {upload_timeline.length > 0 && (
        <SectionCard
          title="Reporting timeline"
          description="Every file this institution has filed, newest first."
          bodyClassName="p-0"
        >
          <ol className="divide-y divide-border">
            {upload_timeline.map((upload) => (
              <li
                key={upload.upload_id}
                className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3 text-sm"
              >
                <FileSpreadsheet className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="font-medium">{upload.filename}</span>
                <span className="text-xs text-muted-foreground">{dateTime(upload.created_at)}</span>
                <span className="text-xs text-muted-foreground">
                  {upload.rows_ok} accepted
                  {upload.rows_error > 0 && `, ${upload.rows_error} rejected`}
                </span>
                {upload.quality_score !== null && upload.quality_score !== undefined && (
                  <span className="ml-auto rounded bg-secondary px-2 py-0.5 text-xs tabular-nums">
                    quality {upload.quality_score}
                  </span>
                )}
              </li>
            ))}
          </ol>
        </SectionCard>
      )}
    </>
  );
}
