"use client";

import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { PageHeader } from "@/components/AppShell";
import { ErrorState, LoadingSkeleton } from "@/components/States";
import { Button, Card, CardContent, CardHeader, CardTitle, Select } from "@/components/ui/primitives";
import { api, download } from "@/lib/api";
import { count, percent } from "@/lib/format";
import type { Suppressible } from "@/lib/types";

const DIMENSIONS = [
  { value: "branch", label: "Branch" },
  { value: "state", label: "State" },
  { value: "category", label: "Category" },
  { value: "gender", label: "Gender" },
  { value: "year", label: "Year of study" },
  { value: "mode", label: "Mode (regular / online)" },
  { value: "admission_type", label: "Admission type" },
];

function plottable(value: Suppressible): number {
  return typeof value === "number" ? value : 0;
}

export default function ReportsPage() {
  const [dimension, setDimension] = useState("branch");
  const [newOnly, setNewOnly] = useState(true);

  const query = useQuery({
    queryKey: ["aicte-trends", dimension, newOnly],
    queryFn: () => api.trends({ dimension, new_admissions_only: newOnly }),
  });

  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;

  const data = query.data;
  const years = data?.academic_years ?? [];
  const chartData = (data?.series ?? []).slice(0, 14).map((row) => {
    const entry: Record<string, string | number> = { key: row.key };
    years.forEach((year) => {
      entry[year] = plottable(row.values[year]);
    });
    return entry;
  });

  return (
    <>
      <PageHeader
        title="Reports and trends"
        description="Year-on-year enrolment from student-level records, with CSV export."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Select
              value={dimension}
              onChange={(event) => setDimension(event.target.value)}
              className="w-52"
            >
              {DIMENSIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
            <Button
              variant="outline"
              onClick={() =>
                download("/aicte/reports/trends.csv", `trends_${dimension}.csv`, {
                  dimension,
                  new_admissions_only: newOnly,
                })
              }
            >
              <Download className="h-4 w-4" />
              Export CSV
            </Button>
          </div>
        }
      />

      <label className="mb-4 flex w-fit items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm">
        <input
          type="checkbox"
          checked={newOnly}
          onChange={(event) => setNewOnly(event.target.checked)}
        />
        Compare new admissions only (year-1 plus lateral entrants)
      </label>

      {query.isLoading ? (
        <LoadingSkeleton rows={6} />
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle>
                {DIMENSIONS.find((item) => item.value === dimension)?.label} · {years.join(" vs ")}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ left: -16, right: 8, top: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                    <XAxis
                      dataKey="key"
                      tick={{ fontSize: 10 }}
                      angle={-28}
                      textAnchor="end"
                      height={90}
                      interval={0}
                    />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    {years.map((year, index) => (
                      <Bar
                        key={year}
                        dataKey={year}
                        fill={index === 0 ? "#94a3b8" : "#1d4ed8"}
                        radius={[3, 3, 0, 0]}
                      />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <ul className="mt-2 space-y-0.5 text-xs text-muted-foreground">
                {(data?.notes ?? []).map((note) => (
                  <li key={note}>• {note}</li>
                ))}
              </ul>
            </CardContent>
          </Card>

          <Card className="mt-4">
            <CardHeader>
              <CardTitle>Detail</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs uppercase tracking-wide text-muted-foreground">
                      <th className="py-1.5 text-left font-semibold">
                        {DIMENSIONS.find((item) => item.value === dimension)?.label}
                      </th>
                      {years.map((year) => (
                        <th key={year} className="py-1.5 text-right font-semibold">
                          {year}
                        </th>
                      ))}
                      <th className="py-1.5 text-right font-semibold">Change</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {(data?.series ?? []).map((row) => (
                      <tr key={row.key}>
                        <td className="py-1.5">{row.key}</td>
                        {years.map((year) => (
                          <td key={year} className="py-1.5 text-right tabular-nums">
                            {count(row.values[year])}
                          </td>
                        ))}
                        <td
                          className={`py-1.5 text-right tabular-nums ${
                            (row.yoy_growth_pct ?? 0) > 20
                              ? "text-amber-700"
                              : (row.yoy_growth_pct ?? 0) < -20
                                ? "text-red-700"
                                : ""
                          }`}
                        >
                          {row.yoy_growth_pct === null || row.yoy_growth_pct === undefined
                            ? "—"
                            : percent(row.yoy_growth_pct)}
                        </td>
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
