"use client";

/** Approved intake vs regular vs each supernumerary bucket vs excess, per programme. */
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2 } from "lucide-react";

import { PageHeader } from "@/components/AppShell";
import { StatCard } from "@/components/StatCard";
import { EmptyState, ErrorState, LoadingSkeleton } from "@/components/States";
import { Card, CardContent, CardHeader, CardTitle, Select } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import type { ProgramSeatMatrix } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useState } from "react";

const YEARS = ["2026-27", "2025-26"];

const BUCKET_COLOURS = [
  "bg-sky-400",
  "bg-violet-400",
  "bg-teal-400",
  "bg-fuchsia-400",
  "bg-lime-500",
];

function SeatBar({ program }: { program: ProgramSeatMatrix }) {
  const used = program.regular_admitted;
  const supernumerary = program.supernumerary.filter((bucket) => bucket.admitted > 0);
  // The bar is scaled against whichever is larger: intake, or everything admitted.
  const scale = Math.max(program.approved_intake, program.total_admitted, 1);
  const widthOf = (value: number) => `${(value / scale) * 100}%`;

  return (
    <div className="space-y-1.5">
      <div className="relative h-7 w-full overflow-hidden rounded bg-muted">
        {/* approved intake marker */}
        <div
          className="absolute inset-y-0 z-10 w-px bg-slate-900"
          style={{ left: widthOf(program.approved_intake) }}
          title={`Approved intake: ${program.approved_intake}`}
        />
        <div className="flex h-full">
          <div
            className={cn("h-full", program.regular_excess > 0 ? "bg-slate-500" : "bg-primary")}
            style={{ width: widthOf(Math.min(used, program.approved_intake)) }}
            title={`Regular within intake: ${Math.min(used, program.approved_intake)}`}
          />
          {program.regular_excess > 0 && (
            <div
              className="h-full bg-red-500"
              style={{ width: widthOf(program.regular_excess) }}
              title={`Regular beyond intake: ${program.regular_excess}`}
            />
          )}
          {supernumerary.map((bucket, index) => (
            <div key={bucket.admission_type} className="flex h-full">
              <div
                className={cn("h-full", BUCKET_COLOURS[index % BUCKET_COLOURS.length])}
                style={{ width: widthOf(bucket.valid) }}
                title={`${bucket.label} within cap: ${bucket.valid} of ${bucket.cap}`}
              />
              {bucket.excess > 0 && (
                <div
                  className="h-full bg-red-500"
                  style={{ width: widthOf(bucket.excess) }}
                  title={`${bucket.label} beyond cap: ${bucket.excess}`}
                />
              )}
            </div>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1">
          <span className="h-2 w-2 rounded-sm bg-primary" /> regular ({program.regular_admitted})
        </span>
        {supernumerary.map((bucket, index) => (
          <span key={bucket.admission_type} className="inline-flex items-center gap-1">
            <span
              className={cn("h-2 w-2 rounded-sm", BUCKET_COLOURS[index % BUCKET_COLOURS.length])}
            />
            {bucket.label} ({bucket.admitted}/{bucket.cap})
          </span>
        ))}
        {program.excess > 0 && (
          <span className="inline-flex items-center gap-1 font-medium text-red-700">
            <span className="h-2 w-2 rounded-sm bg-red-500" /> excess ({program.excess})
          </span>
        )}
        <span className="inline-flex items-center gap-1">
          <span className="h-3 w-px bg-slate-900" /> approved intake ({program.approved_intake})
        </span>
      </div>
    </div>
  );
}

export default function SeatMatrixPage() {
  const [year, setYear] = useState(YEARS[0]);
  const query = useQuery({
    queryKey: ["seat-matrix", year],
    queryFn: () => api.seatMatrix(year),
  });

  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;

  const data = query.data;
  const overProgrammes = (data?.programs ?? []).filter((program) => program.excess > 0);

  return (
    <>
      <PageHeader
        title="Seat matrix"
        description={
          data
            ? `Rule set ${data.rule_set}. Supernumerary seats sit outside approved intake, each with its own cap.`
            : "Approved intake against what was reported."
        }
        actions={
          <Select value={year} onChange={(event) => setYear(event.target.value)} className="w-36">
            {YEARS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </Select>
        }
      />

      {query.isLoading ? (
        <LoadingSkeleton rows={5} />
      ) : !data || data.programs.length === 0 ? (
        <EmptyState
          title="No approved intake on record for this year"
          description="Intake is seeded per programme per academic year. Try another year."
        />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            <StatCard label="Approved intake" value={data.totals.approved_intake} />
            <StatCard label="Regular admitted" value={data.totals.regular_admitted} />
            <StatCard label="Valid supernumerary" value={data.totals.valid_supernumerary} />
            <StatCard label="Total admitted" value={data.totals.total_admitted} />
            <StatCard
              label="Excess"
              value={data.totals.excess}
              tone={data.totals.excess > 0 ? "danger" : "success"}
              hint={overProgrammes.length > 0 ? `${overProgrammes.length} programme(s) over` : "all within limits"}
            />
          </div>

          <div className="mt-4 space-y-3">
            {data.programs.map((program) => (
              <Card key={program.program_id} className={program.excess > 0 ? "border-red-200" : undefined}>
                <CardHeader>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <CardTitle>
                        {program.course} — {program.branch}
                      </CardTitle>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {program.mode === "online" ? "Online / ODL" : "Regular"} ·{" "}
                        {program.vacant_regular_seats} seats vacant in year 1
                      </p>
                    </div>
                    {program.excess > 0 ? (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-red-100 px-2.5 py-1 text-xs font-medium text-red-800">
                        <AlertTriangle className="h-3.5 w-3.5" />
                        {program.excess} excess
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-medium text-emerald-800">
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        within limits
                      </span>
                    )}
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  <SeatBar program={program} />
                  <p className="rounded-md border-l-4 border-accent bg-accent/5 p-3 text-sm leading-relaxed">
                    {program.explanation}
                  </p>
                  {program.supernumerary.some((bucket) => bucket.admitted > 0) && (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-xs uppercase tracking-wide text-muted-foreground">
                            <th className="py-1 text-left font-semibold">Supernumerary category</th>
                            <th className="py-1 text-right font-semibold">Admitted</th>
                            <th className="py-1 text-right font-semibold">Cap</th>
                            <th className="py-1 text-right font-semibold">Excess</th>
                            <th className="py-1 pl-4 text-left font-semibold">Cap basis</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                          {program.supernumerary
                            .filter((bucket) => bucket.admitted > 0 || bucket.excess > 0)
                            .map((bucket) => (
                              <tr key={bucket.admission_type}>
                                <td className="py-1.5">{bucket.label}</td>
                                <td className="py-1.5 text-right tabular-nums">{bucket.admitted}</td>
                                <td className="py-1.5 text-right tabular-nums">{bucket.cap}</td>
                                <td
                                  className={cn(
                                    "py-1.5 text-right tabular-nums",
                                    bucket.excess > 0 && "font-semibold text-red-700",
                                  )}
                                >
                                  {bucket.excess}
                                </td>
                                <td className="py-1.5 pl-4 text-xs text-muted-foreground">
                                  {bucket.cap_basis}
                                </td>
                              </tr>
                            ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        </>
      )}
    </>
  );
}
