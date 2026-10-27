"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AICTE_INSTITUTION_TABS, PageHeader, SubTabs } from "@/components/ui/page";
import { DataTable, TableFilters, type Column } from "@/components/DataTable";
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
      width: "w-[3.5rem]",
      nowrap: true,
      cell: (row) => (
        <span className="tabular-nums text-muted-foreground">
          {(query.data?.items.indexOf(row) ?? 0) + 1 + (page - 1) * 25}
        </span>
      ),
    },
    {
      key: "name",
      header: "Institution",
      width: "w-[15rem]",
      cell: (row) => (
        <span className="block">
          <span className="block font-medium leading-snug">{row.name}</span>
          <span className="mt-0.5 block text-xs text-muted-foreground">{row.state}</span>
        </span>
      ),
    },
    {
      key: "score",
      header: "Risk",
      width: "w-[8.5rem]",
      align: "right",
      nowrap: true,
      cell: (row) => (
        <span className="inline-flex items-center gap-2">
          <span className="tabular-nums font-semibold">{row.risk_score.toFixed(1)}</span>
          <SeverityBadge severity={row.band} showDot={false} />
        </span>
      ),
    },
    {
      key: "reasons",
      header: "Why it scores this high",
      cell: (row) => (
        <ol className="space-y-1 text-xs leading-relaxed">
          {row.top_reasons.slice(0, 3).map((reason, index) => (
            <li key={index}>
              {index + 1}. {reason}
            </li>
          ))}
        </ol>
      ),
    },
    {
      key: "components",
      header: "From flags / model",
      width: "w-[8rem]",
      align: "right",
      nowrap: true,
      cell: (row) => (
        <span className="text-xs tabular-nums text-muted-foreground">
          {row.components.flags.toFixed(0)} / {row.components.anomaly.toFixed(0)}
        </span>
      ),
    },
    {
      key: "open",
      header: "Open flags",
      width: "w-[6rem]",
      align: "right",
      nowrap: true,
      cell: (row) => count(row.open_flags),
    },
  ];

  return (
    <>
      <PageHeader
        title="Risk leaderboard"
        description="Which institutions to look at first, and the reasons behind each score — nothing here is a black box."
      />

      <SubTabs tabs={AICTE_INSTITUTION_TABS} current="/aicte/risk" />

      <DataTable
        minWidth="min-w-[64rem]"
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
        rowKey={(row) => row.institution_id}
        toolbar={
          <TableFilters hint="A legal dual degree never adds risk; it carries weight zero.">
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
          </TableFilters>
        }
      />
    </>
  );
}
