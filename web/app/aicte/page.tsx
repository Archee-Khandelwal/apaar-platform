"use client";

/** National overview. Counts come from student-level records, not institution totals. */
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Building2, FileWarning, Gauge, Users } from "lucide-react";
import Link from "next/link";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { PageHeader } from "@/components/AppShell";
import { SeverityBadge } from "@/components/SeverityBadge";
import { StatCard } from "@/components/StatCard";
import { ErrorState, LoadingSkeleton } from "@/components/States";
import { Button, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
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
  const query = useQuery({ queryKey: ["aicte-overview"], queryFn: () => api.overview() });

  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;

  const data = query.data;
  const flags = data?.kpis.open_flags;
  const stateRows = (data?.by_state ?? []).map((row) => ({
    ...row,
    students: plottable(row.students_reported),
    flags: plottable(row.open_flags),
  }));
  const anySuppressed =
    data?.suppression_applied &&
    (data.by_state.some((row) => isSuppressed(row.students_reported) || isSuppressed(row.open_flags)) ||
      isSuppressed(data.kpis.students_reported));

  return (
    <>
      <PageHeader
        title="National overview"
        description={
          data
            ? `Academic year ${data.academic_year} · counted from student-level records, not institution totals`
            : "Loading…"
        }
        actions={
          <Button asChild variant="outline">
            <Link href="/aicte/shortlist">
              <Gauge className="h-4 w-4" />
              Inspection shortlist
            </Link>
          </Button>
        }
      />

      {user?.role === "aicte_viewer" && (
        <p className="mb-4 rounded-md border border-violet-200 bg-violet-50 px-3 py-2 text-xs text-violet-900">
          You are signed in as an analyst: rows are masked and any count below 5 is shown as
          &ldquo;&lt;5&rdquo; so individuals cannot be identified. Flag evidence and the reveal
          action are available to officers.
        </p>
      )}

      {query.isLoading ? (
        <LoadingSkeleton rows={6} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="Institutions reporting"
              value={data!.kpis.institutions_reporting}
              hint={`of ${count(data!.kpis.institutions_total)} approved · ${count(
                data!.kpis.institutions_non_reporting,
              )} silent`}
              icon={<Building2 className="h-4 w-4" />}
            />
            <StatCard
              label="Students reported"
              value={data!.kpis.students_reported}
              hint="active enrolments, student-level"
              icon={<Users className="h-4 w-4" />}
            />
            <StatCard
              label="Excess seats"
              value={data!.kpis.total_excess_seats}
              hint="beyond intake and valid supernumerary"
              tone="danger"
              icon={<AlertTriangle className="h-4 w-4" />}
            />
            <StatCard
              label="Average data quality"
              value={data!.kpis.avg_data_quality ?? "—"}
              hint="across every upload"
              icon={<FileWarning className="h-4 w-4" />}
            />
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-5">
            <Card className="lg:col-span-3">
              <CardHeader>
                <CardTitle>Students reported by state</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={stateRows} margin={{ left: -16, right: 8, top: 8 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                      <XAxis
                        dataKey="state"
                        tick={{ fontSize: 11 }}
                        angle={-25}
                        textAnchor="end"
                        height={64}
                        interval={0}
                      />
                      <YAxis tick={{ fontSize: 11 }} />
                      <Tooltip
                        contentStyle={{ fontSize: 12, borderRadius: 8 }}
                        formatter={(value: number) => value.toLocaleString("en-IN")}
                      />
                      <Bar dataKey="students" name="Students" fill="#1d4ed8" radius={[3, 3, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                {anySuppressed && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    Suppressed values (&lt;5) are plotted as zero; the table below shows them as
                    &ldquo;&lt;5&rdquo;.
                  </p>
                )}
              </CardContent>
            </Card>

            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>Open findings</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {(["critical", "high", "medium", "low"] as Severity[]).map((severity) => (
                    <div key={severity} className="flex items-center justify-between gap-2">
                      <SeverityBadge severity={severity} />
                      <span className="text-sm font-medium tabular-nums">
                        {count(flags?.[severity])}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="mt-4 h-40">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={(data!.flags_by_type ?? []).slice(0, 6).map((row) => ({
                        name: flagLabel(row.type),
                        value: plottable(row.count),
                        severity: row.max_severity,
                      }))}
                      layout="vertical"
                      margin={{ left: 8, right: 8 }}
                    >
                      <XAxis type="number" hide />
                      <YAxis type="category" dataKey="name" width={140} tick={{ fontSize: 10 }} />
                      <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                      <Bar dataKey="value" radius={[0, 3, 3, 0]}>
                        {(data!.flags_by_type ?? []).slice(0, 6).map((row, index) => (
                          <Cell key={index} fill={SEVERITY_FILL[row.max_severity]} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <Button asChild size="sm" variant="outline" className="mt-2 w-full">
                  <Link href="/aicte/flags">Open the flag queue</Link>
                </Button>
              </CardContent>
            </Card>
          </div>

          <Card className="mt-4">
            <CardHeader>
              <CardTitle>State-wise detail</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs uppercase tracking-wide text-muted-foreground">
                      <th className="py-1.5 text-left font-semibold">State</th>
                      <th className="py-1.5 text-right font-semibold">Institutions</th>
                      <th className="py-1.5 text-right font-semibold">Reporting</th>
                      <th className="py-1.5 text-right font-semibold">Students</th>
                      <th className="py-1.5 text-right font-semibold">Open findings</th>
                      <th className="py-1.5 text-right font-semibold">Excess seats</th>
                      <th className="py-1.5 text-right font-semibold">Avg risk</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {data!.by_state.map((row) => (
                      <tr key={row.state}>
                        <td className="py-1.5 font-medium">{row.state}</td>
                        <td className="py-1.5 text-right tabular-nums">{count(row.institutions)}</td>
                        <td className="py-1.5 text-right tabular-nums">
                          {count(row.institutions_reporting)}
                        </td>
                        <td className="py-1.5 text-right tabular-nums">
                          {count(row.students_reported)}
                        </td>
                        <td className="py-1.5 text-right tabular-nums">{count(row.open_flags)}</td>
                        <td className="py-1.5 text-right tabular-nums">{count(row.excess_seats)}</td>
                        <td className="py-1.5 text-right tabular-nums">{row.avg_risk.toFixed(1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </>
  );
}
