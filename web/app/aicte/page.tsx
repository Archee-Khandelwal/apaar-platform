"use client";

/** National overview. Counts come from student-level records, not institution totals. */
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Building2, ClipboardCheck, Flag, Users } from "lucide-react";
import Link from "next/link";
import { Bar, BarChart, CartesianGrid, Cell, Tooltip, XAxis, YAxis } from "recharts";

import { CHART_COLOURS, CHART_TOOLTIP_STYLE, ChartFrame } from "@/components/Chart";
import { SeverityBadge } from "@/components/SeverityBadge";
import { ErrorState, KpiSkeleton, Skeleton } from "@/components/States";
import { KpiCard, KpiRow, PageHeader, SectionCard } from "@/components/ui/page";
import { Button } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { count, flagLabel, isSuppressed } from "@/lib/format";
import type { Severity, Suppressible } from "@/lib/types";

const SEVERITY_FILL: Record<Severity, string> = {
  low: "#64748b",
  medium: "#f59e0b",
  high: "#f97316",
  critical: "#dc2626",
};

/** A suppressed value cannot be plotted; charts drop to 0 and the caption says so. */
function plottable(value: Suppressible): number {
  return typeof value === "number" ? value : 0;
}

export default function AicteOverviewPage() {
  const { user } = useAuth();
  const isOfficer = user?.role === "aicte_officer";

  const query = useQuery({ queryKey: ["aicte-overview"], queryFn: () => api.overview() });
  const risk = useQuery({
    queryKey: ["aicte-risk", "top5"],
    queryFn: () => api.risk({ page: 1, page_size: 5 }),
    enabled: isOfficer,
  });
  const shortlist = useQuery({
    queryKey: ["aicte-shortlist", 3],
    queryFn: () => api.shortlist(3),
    enabled: isOfficer,
  });

  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;

  const data = query.data;
  const flags = data?.kpis.open_flags;
  const stateRows = (data?.by_state ?? []).map((row) => ({
    state: row.state,
    students: plottable(row.students_reported),
  }));
  const flagTypeRows = (data?.flags_by_type ?? []).slice(0, 7).map((row) => ({
    name: flagLabel(row.type),
    value: plottable(row.count),
    severity: row.max_severity,
  }));
  const anySuppressed =
    data?.suppression_applied &&
    (data.by_state.some((row) => isSuppressed(row.students_reported)) ||
      isSuppressed(data.kpis.students_reported));

  return (
    <>
      <PageHeader
        title="Overview"
        description={
          data
            ? `Where the risk is across every AICTE-approved institution for ${data.academic_year}, counted from student-level records.`
            : "Where the risk is across every AICTE-approved institution."
        }
        actions={
          isOfficer && (
            <Button asChild>
              <Link href="/aicte/shortlist">
                <ClipboardCheck className="h-4 w-4" />
                Inspection shortlist
              </Link>
            </Button>
          )
        }
      />

      {user?.role === "aicte_viewer" && (
        <p className="rounded-md border border-violet-200 bg-violet-50 px-4 py-3 text-xs leading-relaxed text-violet-900">
          You are signed in as an analyst: rows are masked and any count below 5 is shown as
          &ldquo;&lt;5&rdquo; so individuals cannot be identified. Flag evidence, case actions and
          the reveal control belong to officers.
        </p>
      )}

      {query.isLoading ? (
        <>
          <KpiSkeleton />
          <Skeleton rows={3} height="h-40" />
        </>
      ) : (
        <>
          <KpiRow>
            <KpiCard
              label="Institutions reporting"
              value={data!.kpis.institutions_reporting}
              hint={`Of ${count(data!.kpis.institutions_total)} approved · ${count(
                data!.kpis.institutions_non_reporting,
              )} have filed nothing`}
              icon={<Building2 className="h-4 w-4" />}
            />
            <KpiCard
              label="Students reported"
              value={data!.kpis.students_reported}
              hint="Active enrolments, at student level"
              icon={<Users className="h-4 w-4" />}
            />
            <KpiCard
              label="Open critical flags"
              value={flags?.critical ?? 0}
              hint={`${count(flags?.high)} high · ${count(flags?.medium)} medium · ${count(flags?.low)} low still open`}
              tone={
                isSuppressed(flags?.critical)
                  ? "default"
                  : plottable(flags?.critical ?? 0) > 0
                    ? "critical"
                    : "positive"
              }
              icon={<Flag className="h-4 w-4" />}
            />
            <KpiCard
              label="Total excess seats"
              value={data!.kpis.total_excess_seats}
              hint="Beyond approved intake and valid supernumerary caps"
              tone={
                isSuppressed(data!.kpis.total_excess_seats)
                  ? "default"
                  : plottable(data!.kpis.total_excess_seats) > 0
                    ? "critical"
                    : "positive"
              }
              icon={<AlertTriangle className="h-4 w-4" />}
            />
          </KpiRow>

          {isOfficer && (
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
              <SectionCard
                title="Highest-risk institutions"
                description="Risk is open findings plus the statistical anomaly score. Every row carries its reasons."
                className="lg:col-span-2"
                actions={
                  <Button asChild size="sm" variant="outline">
                    <Link href="/aicte/risk">Full leaderboard</Link>
                  </Button>
                }
                bodyClassName="p-0"
              >
                {risk.isLoading ? (
                  <div className="p-5">
                    <Skeleton rows={5} />
                  </div>
                ) : (
                  <ol className="divide-y divide-border">
                    {(risk.data?.items ?? []).map((row, index) => (
                      <li key={row.institution_id} className="flex gap-4 px-5 py-4">
                        <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-semibold tabular-nums">
                          {index + 1}
                        </span>
                        <div className="min-w-0 flex-1 space-y-1.5">
                          <Link
                            href={`/aicte/institutions/${row.institution_id}`}
                            className="block text-sm font-medium hover:underline"
                          >
                            {row.name}
                          </Link>
                          <p className="text-xs text-muted-foreground">{row.state}</p>
                          <ul className="space-y-1 text-xs leading-relaxed text-muted-foreground">
                            {row.top_reasons.slice(0, 2).map((reason, position) => (
                              <li key={position}>• {reason}</li>
                            ))}
                          </ul>
                        </div>
                        <span className="flex shrink-0 flex-col items-end gap-1.5">
                          <span className="text-lg font-semibold tabular-nums">
                            {row.risk_score.toFixed(1)}
                          </span>
                          <SeverityBadge severity={row.band} showDot={false} />
                        </span>
                      </li>
                    ))}
                  </ol>
                )}
              </SectionCard>

              <SectionCard
                title="Recommended for inspection"
                description="The top of the shortlist, with what to check on site."
                bodyClassName="p-0"
                footer={
                  <Button asChild size="sm" variant="outline" className="w-full">
                    <Link href="/aicte/shortlist">
                      Full shortlist
                      <ArrowRight className="h-3.5 w-3.5" />
                    </Link>
                  </Button>
                }
              >
                {shortlist.isLoading ? (
                  <div className="p-5">
                    <Skeleton rows={3} />
                  </div>
                ) : (
                  <ul className="divide-y divide-border">
                    {(shortlist.data?.items ?? []).map((row) => (
                      <li key={row.institution_id} className="space-y-1.5 px-5 py-4">
                        <Link
                          href={`/aicte/institutions/${row.institution_id}`}
                          className="block text-sm font-medium hover:underline"
                        >
                          {row.rank}. {row.name}
                        </Link>
                        <p className="text-xs leading-relaxed text-muted-foreground">
                          {row.suggested_checks[0] ?? row.reasons[0]}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </SectionCard>
            </div>
          )}

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
            <SectionCard
              title="Students reported by state"
              className="lg:col-span-3"
              footer={
                anySuppressed ? (
                  <p className="text-xs text-muted-foreground">
                    Suppressed values (&lt;5) are plotted as zero; the table below shows them as
                    &ldquo;&lt;5&rdquo;.
                  </p>
                ) : undefined
              }
            >
              <ChartFrame height={360}>
                {(width) => (
                  <BarChart
                    width={width}
                    height={360}
                    data={stateRows}
                    margin={{ left: 0, right: 8, top: 8, bottom: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={CHART_COLOURS.grid} />
                    <XAxis
                      dataKey="state"
                      tick={{ fontSize: 11, fill: CHART_COLOURS.axis }}
                      angle={-30}
                      textAnchor="end"
                      height={78}
                      interval={0}
                      tickLine={false}
                    />
                    <YAxis
                      tick={{ fontSize: 11, fill: CHART_COLOURS.axis }}
                      width={48}
                      tickLine={false}
                      axisLine={false}
                    />
                    <Tooltip
                      cursor={{ fill: "rgba(30,64,175,0.06)" }}
                      contentStyle={CHART_TOOLTIP_STYLE}
                      formatter={(value: number) => [value.toLocaleString("en-IN"), "Students"]}
                    />
                    <Bar
                      dataKey="students"
                      fill={CHART_COLOURS.primary}
                      radius={[3, 3, 0, 0]}
                      maxBarSize={44}
                      isAnimationActive={false}
                    />
                  </BarChart>
                )}
              </ChartFrame>
            </SectionCard>

            <SectionCard
              title="Open findings by type"
              description="Coloured by the most serious severity seen for that type."
              className="lg:col-span-2"
              footer={
                <Button asChild size="sm" variant="outline" className="w-full">
                  <Link href={isOfficer ? "/aicte/flags" : "/aicte/institutions"}>
                    {isOfficer ? "Open the flag queue" : "Browse institutions"}
                    <ArrowRight className="h-3.5 w-3.5" />
                  </Link>
                </Button>
              }
            >
              <div className="mb-5 space-y-2">
                {(["critical", "high", "medium", "low"] as Severity[]).map((severity) => (
                  <div key={severity} className="flex items-center justify-between gap-3">
                    <SeverityBadge severity={severity} />
                    <span className="text-sm font-semibold tabular-nums">{count(flags?.[severity])}</span>
                  </div>
                ))}
              </div>
              <ChartFrame height={224}>
                {(width) => (
                  <BarChart
                    width={width}
                    height={224}
                    data={flagTypeRows}
                    layout="vertical"
                    margin={{ left: 0, right: 28, top: 0, bottom: 0 }}
                  >
                    <XAxis type="number" hide />
                    <YAxis
                      type="category"
                      dataKey="name"
                      width={126}
                      tick={{ fontSize: 10, fill: CHART_COLOURS.axis }}
                      tickLine={false}
                      axisLine={false}
                    />
                    <Tooltip
                      cursor={{ fill: "rgba(30,64,175,0.06)" }}
                      contentStyle={CHART_TOOLTIP_STYLE}
                      formatter={(value: number) => [value, "Open findings"]}
                    />
                    <Bar dataKey="value" radius={[0, 3, 3, 0]} maxBarSize={18} isAnimationActive={false}>
                      {flagTypeRows.map((row) => (
                        <Cell key={row.name} fill={SEVERITY_FILL[row.severity]} />
                      ))}
                    </Bar>
                  </BarChart>
                )}
              </ChartFrame>
            </SectionCard>
          </div>

          <SectionCard
            title="State by state"
            description="The same numbers as the chart, with reporting coverage and average risk."
            bodyClassName="p-0"
          >
            <div className="overflow-x-auto">
              <table className="w-full min-w-[42rem] text-sm">
                <thead>
                  <tr className="border-b border-border bg-secondary/60">
                    <th className="px-5 py-3 text-left type-label">State</th>
                    <th className="px-4 py-3 text-right type-label">Institutions</th>
                    <th className="px-4 py-3 text-right type-label">Reporting</th>
                    <th className="px-4 py-3 text-right type-label">Students</th>
                    <th className="px-4 py-3 text-right type-label">Open findings</th>
                    <th className="px-4 py-3 text-right type-label">Excess seats</th>
                    <th className="px-5 py-3 text-right type-label">Avg risk</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {data!.by_state.map((row) => (
                    <tr key={row.state}>
                      <td className="px-5 py-2.5 font-medium">{row.state}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums">{count(row.institutions)}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums">
                        {count(row.institutions_reporting)}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums">{count(row.students_reported)}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums">{count(row.open_flags)}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums">{count(row.excess_seats)}</td>
                      <td className="px-5 py-2.5 text-right tabular-nums">{row.avg_risk.toFixed(1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </SectionCard>
        </>
      )}
    </>
  );
}
