"use client";

import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Tooltip, XAxis, YAxis } from "recharts";

import { CHART_COLOURS, CHART_TOOLTIP_STYLE, ChartFrame } from "@/components/Chart";

import { PageHeader, SectionCard } from "@/components/ui/page";
import { ErrorState, Skeleton } from "@/components/States";
import { Button, Select } from "@/components/ui/primitives";
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
        title="Reports"
        description="How enrolment has moved year on year, counted from student-level records."
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

      <label className="flex w-fit items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm shadow-card">
        <input
          type="checkbox"
          checked={newOnly}
          onChange={(event) => setNewOnly(event.target.checked)}
        />
        Compare new admissions only (year-1 plus lateral entrants)
      </label>

      {query.isLoading ? (
        <Skeleton rows={3} height="h-48" />
      ) : (
        <>
          <SectionCard
            title={`${DIMENSIONS.find((item) => item.value === dimension)?.label} · ${years.join(" vs ")}`}
            footer={
              (data?.notes ?? []).length > 0 ? (
                <ul className="space-y-1 text-xs leading-relaxed text-muted-foreground">
                  {(data?.notes ?? []).map((note) => (
                    <li key={note}>• {note}</li>
                  ))}
                </ul>
              ) : undefined
            }
          >
            {/*
              Horizontal bars: branch names run to "Computer Science and
              Engineering (Online/ODL)", which no rotated x-axis can show whole.
            */}
            <ChartFrame height={Math.max(220, chartData.length * 56)}>
              {(width) => (
                <BarChart
                  width={width}
                  height={Math.max(220, chartData.length * 56)}
                  data={chartData}
                  layout="vertical"
                  margin={{ left: 0, right: 40, top: 8, bottom: 8 }}
                  barGap={2}
                >
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke={CHART_COLOURS.grid} />
                  <XAxis
                    type="number"
                    tick={{ fontSize: 11, fill: CHART_COLOURS.axis }}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    type="category"
                    dataKey="key"
                    width={Math.min(260, Math.max(140, Math.round(width * 0.32)))}
                    tick={{ fontSize: 11, fill: CHART_COLOURS.axis }}
                    tickLine={false}
                    axisLine={false}
                  />
                  <Tooltip cursor={{ fill: "rgba(30,64,175,0.06)" }} contentStyle={CHART_TOOLTIP_STYLE} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  {years.map((year, index) => (
                    <Bar
                      key={year}
                      dataKey={year}
                      fill={index === 0 ? CHART_COLOURS.comparison : CHART_COLOURS.primary}
                      radius={[0, 3, 3, 0]}
                      maxBarSize={18}
                      isAnimationActive={false}
                    />
                  ))}
                </BarChart>
              )}
            </ChartFrame>
          </SectionCard>

          <SectionCard title="Detail" bodyClassName="p-0">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[34rem] text-sm">
                  <thead>
                    <tr className="border-b border-border bg-secondary/60">
                      <th className="px-5 py-3 text-left type-label">
                        {DIMENSIONS.find((item) => item.value === dimension)?.label}
                      </th>
                      {years.map((year) => (
                        <th key={year} className="px-4 py-3 text-right type-label">
                          {year}
                        </th>
                      ))}
                      <th className="px-5 py-3 text-right type-label">Change</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {(data?.series ?? []).map((row) => (
                      <tr key={row.key}>
                        <td className="px-5 py-2.5">{row.key}</td>
                        {years.map((year) => (
                          <td key={year} className="px-4 py-2.5 text-right tabular-nums">
                            {count(row.values[year])}
                          </td>
                        ))}
                        <td
                          className={`px-5 py-2.5 text-right tabular-nums ${
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
          </SectionCard>
        </>
      )}
    </>
  );
}
