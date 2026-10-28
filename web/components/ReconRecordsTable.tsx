"use client";

/** A page of reconciliation records; selecting a row opens the side-by-side record page. */
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { DataTable, type Column } from "@/components/DataTable";
import { MaskedApaar, MaskedName } from "@/components/Masked";
import { ReconBadge } from "@/components/ReconBadge";
import type { ReconRow } from "@/lib/types";

export function ReconRecordsTable({
  rows,
  loading,
  total,
  page,
  onPageChange,
  toolbar,
  showInstitution = true,
  hrefFor,
}: {
  rows: ReconRow[];
  loading: boolean;
  total?: number;
  page: number;
  onPageChange: (page: number) => void;
  toolbar?: ReactNode;
  showInstitution?: boolean;
  /** Where a row leads; omit for a table that is not clickable. */
  hrefFor?: (row: ReconRow) => string;
}) {
  const router = useRouter();
  const columns: Column<ReconRow>[] = [
    { key: "apaar", header: "APAAR ID", width: "w-[10rem]", cell: (row) => <MaskedApaar value={row.apaar_masked} /> },
    { key: "name", header: "Student", width: "w-[9rem]", cell: (row) => <MaskedName value={row.name_masked} /> },
    ...(showInstitution
      ? [{ key: "inst", header: "Institution", cell: (row: ReconRow) => <span className="text-xs">{row.institution_name}</span> }]
      : []),
    {
      key: "programme",
      header: "Programme",
      cell: (row) => (
        <span className="text-xs">
          {row.programme} · {row.academic_year}
          <span className="text-muted-foreground"> · {row.admission_type.replace(/_/g, " ")}</span>
        </span>
      ),
    },
    {
      key: "why",
      header: "What needs attention",
      cell: (row) =>
        row.problems.length ? (
          <ul className="space-y-0.5 text-xs leading-snug text-muted-foreground">
            {row.problems.map((problem) => (
              <li key={problem.check}>
                <span className="font-medium text-foreground">{problem.label}:</span> {problem.message}
              </li>
            ))}
          </ul>
        ) : (
          <span className="text-xs text-muted-foreground">All six checks passed.</span>
        ),
    },
    { key: "status", header: "Status", width: "w-[8rem]", cell: (row) => <ReconBadge status={row.overall} /> },
  ];
  return (
    <DataTable
      minWidth="min-w-[62rem]"
      columns={columns}
      rows={rows}
      loading={loading}
      total={total}
      page={page}
      pageSize={25}
      onPageChange={onPageChange}
      onRowClick={hrefFor ? (row) => router.push(hrefFor(row)) : undefined}
      emptyTitle="No records match"
      emptyDescription="Change the filters to see other records."
      rowKey={(row) => row.enrolment_id}
      toolbar={toolbar}
    />
  );
}
