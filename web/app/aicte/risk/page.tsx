"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { PageHeader } from "@/components/AppShell";
import { DataTable, type Column } from "@/components/DataTable";
import { SeverityBadge } from "@/components/SeverityBadge";
import { Select } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { count } from "@/lib/format";
import type { RiskRow, Severity } from "@/lib/types";

const BANDS: Severity[] = ["critical", "high", "medium", "low"];

export default function RiskPage() {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [band, setBand] = useState("");

  const query = useQuery({
    queryKey: ["aicte-risk", page, band],
    queryFn: () => api.risk({ page, page_size: 25, band: band || undefined }),
  });

  const columns: Column<RiskRow>[] = [
    {
      key: "rank",
      header: "#",
      cell: (row) => (
        <span className="tabular-nums text-muted-foreground">
          {(query.data?.items.indexOf(row) ?? 0) + 1 + (page - 1) * 25}
        </span>
      ),
    },
    {
      key: "name",
      header: "Institution",
      cell: (row) => (
        <span>
          <span className="font-medium">{row.name}</span>
          <span className="block text-xs text-muted-foreground">{row.state}</span>
        </span>
      ),
    },
    {
      key: "score",
      header: "Risk",
      align: "right",
      cell: (row) => (
        <span className="inline-flex items-center gap-2">
          <span className="tabular-nums font-semibold">{row.risk_score.toFixed(1)}</span>
          <SeverityBadge severity={row.band} showDot={false} />
        </span>
      ),
    },
    {
      key: "reasons",
      header: "Why",
      cell: (row) => (
        <ol className="max-w-xl space-y-0.5 text-xs">
          {row.top_reasons.slice(0, 3).map((reason, index) => (
            <li key={index} className="line-clamp-1">
              {index + 1}. {reason}
            </li>
          ))}
        </ol>
      ),
    },
    {
      key: "components",
      header: "Findings / model",
      align: "right",
      cell: (row) => (
        <span className="text-xs tabular-nums text-muted-foreground">
          {row.components.flags.toFixed(0)} / {row.components.anomaly.toFixed(0)}
        </span>
      ),
    },
    {
      key: "open",
      header: "Open",
      align: "right",
      cell: (row) => count(row.open_flags),
    },
  ];

  return (
    <>
      <PageHeader
        title="Risk leaderboard"
        description="A weighted sum of open findings plus the statistical anomaly score. Every row carries its own reasons — nothing here is a black box."
      />
      <DataTable
        columns={columns}
        rows={query.data?.items ?? []}
        loading={query.isLoading}
        total={query.data?.total}
        page={page}
        pageSize={25}
        onPageChange={setPage}
        onRowClick={(row) => router.push(`/aicte/institutions/${row.institution_id}`)}
        emptyTitle="No institutions scored yet"
        emptyDescription="Risk is computed when the detectors run. Try `make reset`."
        toolbar={
          <div className="flex flex-wrap items-center gap-2">
            <Select
              value={band}
              onChange={(event) => {
                setBand(event.target.value);
                setPage(1);
              }}
              className="w-40"
            >
              <option value="">All risk bands</option>
              {BANDS.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </Select>
            <p className="text-xs text-muted-foreground">
              A legal dual degree never adds risk; it carries weight zero.
            </p>
          </div>
        }
      />
    </>
  );
}
