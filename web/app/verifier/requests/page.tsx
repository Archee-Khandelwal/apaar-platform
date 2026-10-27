"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { PageHeader } from "@/components/AppShell";
import { DataTable, type Column } from "@/components/DataTable";
import { Badge } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { VerificationRequestStatus } from "@/lib/types";

const TONE: Record<string, "neutral" | "success" | "warning" | "danger"> = {
  pending: "warning",
  approved: "success",
  denied: "neutral",
  expired: "neutral",
  revoked: "danger",
};

export default function VerifierRequestsPage() {
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["verifier-requests", page],
    queryFn: () => api.verificationRequests({ page, page_size: 25 }),
    refetchInterval: 8000,
  });

  const columns: Column<VerificationRequestStatus>[] = [
    { key: "apaar", header: "APAAR", cell: (row) => <span className="font-mono text-xs">{row.apaar_masked}</span> },
    { key: "purpose", header: "Purpose", cell: (row) => row.purpose.replace(/_/g, " ") },
    {
      key: "status",
      header: "Status",
      cell: (row) => <Badge tone={TONE[row.status] ?? "neutral"}>{row.status}</Badge>,
    },
    {
      key: "result",
      header: "Result",
      cell: (row) =>
        row.result ? (
          <span className="text-sm">
            {row.result.verified ? "Verified" : "Not verified"}
            {row.result.program && (
              <span className="block text-xs text-muted-foreground">
                {row.result.program} · {row.result.academic_year}
              </span>
            )}
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">nothing shared</span>
        ),
    },
    { key: "requested", header: "Requested", cell: (row) => <span className="text-xs">{dateTime(row.requested_at)}</span> },
    { key: "answered", header: "Answered", cell: (row) => <span className="text-xs">{dateTime(row.responded_at)}</span> },
  ];

  return (
    <>
      <PageHeader
        title="My verification requests"
        description="Statuses update on their own. A revoked consent removes the result you were given."
      />
      <DataTable
        columns={columns}
        rows={query.data?.items ?? []}
        loading={query.isLoading}
        total={query.data?.total}
        page={page}
        pageSize={25}
        onPageChange={setPage}
        emptyTitle="No requests yet"
        emptyDescription="Submit an APAAR ID on the verify page to get started."
      />
    </>
  );
}
