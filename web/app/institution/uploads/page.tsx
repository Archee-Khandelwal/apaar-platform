"use client";

import { useQuery } from "@tanstack/react-query";
import { Download, FileSpreadsheet } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/ui/page";
import { DataTable, type Column } from "@/components/DataTable";
import { Badge, Button } from "@/components/ui/primitives";
import { api, download } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { UploadSummary } from "@/lib/types";

export default function UploadHistoryPage() {
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("-created_at");
  const query = useQuery({
    queryKey: ["uploads", page, sort],
    queryFn: () => api.uploads({ page, page_size: 20, sort }),
  });

  const columns: Column<UploadSummary>[] = [
    {
      key: "file",
      header: "File",
      cell: (row) => (
        <span className="flex items-start gap-2 font-medium">
          <FileSpreadsheet className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0 leading-snug">{row.filename}</span>
        </span>
      ),
    },
    {
      key: "year",
      header: "Year",
      width: "w-[6.5rem]",
      nowrap: true,
      cell: (row) => row.academic_year ?? "—",
    },
    {
      key: "state",
      header: "State",
      width: "w-[7.5rem]",
      nowrap: true,
      cell: (row) => (
        <Badge tone={row.state === "completed" ? "success" : row.state === "failed" ? "danger" : "warning"}>
          {row.state.replace("_", " ")}
        </Badge>
      ),
    },
    {
      key: "rows",
      header: "Rows",
      width: "w-[5.5rem]",
      align: "right",
      nowrap: true,
      sortKey: "rows_total",
      cell: (row) => row.rows_total,
    },
    {
      key: "ok",
      header: "Accepted",
      width: "w-[6.5rem]",
      align: "right",
      nowrap: true,
      cell: (row) => row.rows_ok,
    },
    {
      key: "errors",
      header: "Rejected",
      width: "w-[6.5rem]",
      align: "right",
      nowrap: true,
      cell: (row) => (row.rows_error > 0 ? <span className="font-semibold text-red-700">{row.rows_error}</span> : 0),
    },
    {
      key: "score",
      header: "Quality",
      width: "w-[5.5rem]",
      align: "right",
      nowrap: true,
      sortKey: "quality_score",
      cell: (row) => (row.quality_score === null || row.quality_score === undefined ? "—" : row.quality_score),
    },
    {
      key: "created",
      header: "Uploaded",
      width: "w-[9.5rem]",
      nowrap: true,
      sortKey: "created_at",
      cell: (row) => <span className="text-xs text-muted-foreground">{dateTime(row.created_at)}</span>,
    },
    {
      key: "actions",
      header: "",
      width: "w-[6.5rem]",
      align: "right",
      cell: (row) =>
        row.rows_error > 0 ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => download(`/institution/uploads/${row.id}/errors.csv`, `upload_${row.id}_errors.csv`)}
          >
            <Download className="h-3.5 w-3.5" />
            Errors
          </Button>
        ) : null,
    },
  ];

  return (
    <>
      <PageHeader
        title="Upload history"
        description="Every file you have submitted, with its quality score and the rows that were rejected."
        actions={
          <Button asChild>
            <Link href="/institution/upload">New upload</Link>
          </Button>
        }
      />
      <DataTable
        minWidth="min-w-[70rem]"
        columns={columns}
        rows={query.data?.items ?? []}
        loading={query.isLoading}
        total={query.data?.total}
        page={page}
        pageSize={20}
        sort={sort}
        onSortChange={setSort}
        onPageChange={setPage}
        emptyTitle="No uploads yet"
        emptyDescription="Upload an Excel or CSV file of your admissions to get started."
        rowKey={(row) => row.id}
      />
    </>
  );
}
