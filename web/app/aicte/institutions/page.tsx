"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { PageHeader } from "@/components/AppShell";
import { DataTable, type Column } from "@/components/DataTable";
import { SeverityBadge } from "@/components/SeverityBadge";
import { Input, Select } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { count, dateTime } from "@/lib/format";
import { FLAG_TYPES, type InstitutionRow } from "@/lib/types";

export default function InstitutionsPage() {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("-risk_score");
  const [search, setSearch] = useState("");
  const [state, setState] = useState("");
  const [flagType, setFlagType] = useState("");
  const [reporting, setReporting] = useState("");

  const query = useQuery({
    queryKey: ["aicte-institutions", page, sort, search, state, flagType, reporting],
    queryFn: () =>
      api.institutions({
        page,
        page_size: 25,
        sort,
        q: search || undefined,
        state: state || undefined,
        has_flag_type: flagType || undefined,
        reporting: reporting || undefined,
      }),
  });

  const states = Array.from(new Set((query.data?.items ?? []).map((row) => row.state))).sort();

  const columns: Column<InstitutionRow>[] = [
    {
      key: "name",
      header: "Institution",
      sortKey: "name",
      cell: (row) => (
        <span>
          <span className="font-medium">{row.name}</span>
          <span className="block font-mono text-xs text-muted-foreground">
            {row.aicte_permanent_id}
          </span>
        </span>
      ),
    },
    { key: "state", header: "State", cell: (row) => row.state },
    {
      key: "risk",
      header: "Risk",
      sortKey: "risk_score",
      align: "right",
      cell: (row) => (
        <span className="inline-flex items-center gap-2">
          <span className="tabular-nums">{row.risk_score.toFixed(1)}</span>
          <SeverityBadge severity={row.risk_band} showDot={false} />
        </span>
      ),
    },
    {
      key: "students",
      header: "Students",
      sortKey: "students_reported",
      align: "right",
      cell: (row) => count(row.students_reported),
    },
    {
      key: "flags",
      header: "Open findings",
      align: "right",
      cell: (row) => (
        <span className="flex justify-end gap-1 text-xs">
          {(["critical", "high", "medium", "low"] as const).map((severity) =>
            row.open_flags[severity] ? (
              <span key={severity} title={severity}>
                <SeverityBadge severity={severity} showDot={false} className="px-1.5" />
                <span className="ml-0.5 tabular-nums">{count(row.open_flags[severity])}</span>
              </span>
            ) : null,
          )}
        </span>
      ),
    },
    {
      key: "excess",
      header: "Excess",
      sortKey: "excess_seats",
      align: "right",
      cell: (row) =>
        row.excess_seats === 0 ? "—" : <span className="font-medium text-red-700">{count(row.excess_seats)}</span>,
    },
    {
      key: "upload",
      header: "Last upload",
      cell: (row) => <span className="text-xs text-muted-foreground">{dateTime(row.last_upload_at)}</span>,
    },
  ];

  return (
    <>
      <PageHeader
        title="Institutions"
        description="Every AICTE-approved institution in the dataset, ranked by risk. Click a row for the full profile."
      />
      <DataTable
        columns={columns}
        rows={query.data?.items ?? []}
        loading={query.isLoading}
        total={query.data?.total}
        page={page}
        pageSize={25}
        sort={sort}
        onSortChange={setSort}
        onPageChange={setPage}
        onRowClick={(row) => router.push(`/aicte/institutions/${row.id}`)}
        emptyTitle="No institutions match these filters"
        toolbar={
          <div className="flex flex-wrap items-center gap-2">
            <Input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(1);
              }}
              placeholder="Name or AICTE permanent id"
              className="w-64"
            />
            <Select
              value={state}
              onChange={(event) => {
                setState(event.target.value);
                setPage(1);
              }}
              className="w-44"
            >
              <option value="">All states</option>
              {states.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </Select>
            <Select
              value={flagType}
              onChange={(event) => {
                setFlagType(event.target.value);
                setPage(1);
              }}
              className="w-56"
            >
              <option value="">Any finding</option>
              {FLAG_TYPES.map((item) => (
                <option key={item} value={item}>
                  has {item.replace(/_/g, " ").toLowerCase()}
                </option>
              ))}
            </Select>
            <Select
              value={reporting}
              onChange={(event) => {
                setReporting(event.target.value);
                setPage(1);
              }}
              className="w-40"
            >
              <option value="">Reporting or not</option>
              <option value="yes">Reporting</option>
              <option value="no">Not reporting</option>
            </Select>
          </div>
        }
      />
    </>
  );
}
