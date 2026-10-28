"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { PageHeader } from "@/components/ui/page";
import { DataTable, TableFilters, type Column } from "@/components/DataTable";
import { SeverityBadge } from "@/components/SeverityBadge";
import { Input, Select } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { count, dateOnly } from "@/lib/format";
import { FLAG_TYPES, type InstitutionRow } from "@/lib/types";

export default function InstitutionsPage() {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("-open_flags_total");
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
      cell: (row) => <span className="font-medium leading-snug">{row.name}</span>,
    },
    {
      key: "state",
      header: "State",
      width: "w-[9rem]",
      cell: (row) => row.state,
    },
    {
      key: "students",
      header: "Students",
      sortKey: "students_reported",
      width: "w-[6.5rem]",
      align: "right",
      nowrap: true,
      cell: (row) => count(row.students_reported),
    },
    {
      key: "flags",
      header: "Open flags",
      sortKey: "open_flags_total",
      width: "w-[12rem]",
      align: "right",
      cell: (row) => (
        <span className="flex flex-wrap justify-end gap-1.5">
          {(["critical", "high", "medium", "low"] as const)
            .filter((severity) => row.open_flags[severity])
            .map((severity) => (
              <span
                key={severity}
                className="inline-flex items-center gap-1 whitespace-nowrap"
                title={severity}
              >
                <SeverityBadge severity={severity} showDot={false} className="px-1.5" />
                <span className="tabular-nums">{count(row.open_flags[severity])}</span>
              </span>
            ))}
          {!(["critical", "high", "medium", "low"] as const).some((s) => row.open_flags[s]) && "—"}
        </span>
      ),
    },
    {
      key: "excess",
      header: "Excess",
      sortKey: "excess_seats",
      width: "w-[6.5rem]",
      align: "right",
      nowrap: true,
      cell: (row) =>
        row.excess_seats === 0 ? "—" : <span className="font-semibold text-red-700">{count(row.excess_seats)}</span>,
    },
    {
      key: "upload",
      header: "Last upload",
      width: "w-[8.5rem]",
      nowrap: true,
      cell: (row) => <span className="text-xs text-muted-foreground">{dateOnly(row.last_upload_at)}</span>,
    },
  ];

  return (
    <>
      <PageHeader
        title="Institutions"
        description="Every AICTE-approved institution with its reported students and open findings. Select a row for the full profile."
      />

      <DataTable
        minWidth="min-w-[62rem]"
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
        rowKey={(row) => row.id}
        toolbar={
          <TableFilters hint="Select a row for the full profile.">
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
          </TableFilters>
        }
      />

    </>
  );
}
