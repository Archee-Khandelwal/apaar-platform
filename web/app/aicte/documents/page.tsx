"use client";

/**
 * The officer's document review queue. Rows are masked; opening a case asks for a
 * reason first, because the case shows the student's real name and date of birth.
 */
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, ClipboardList, FileX2, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { DataTable, TableFilters, type Column } from "@/components/DataTable";
import { VerificationBadge } from "@/components/DocumentStatusBadge";
import { MaskedApaar } from "@/components/Masked";
import { KpiCard, KpiRow, PageHeader } from "@/components/ui/page";
import { Select } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateOnly } from "@/lib/format";
import type { ReviewRow } from "@/lib/types";

export default function DocumentReviewPage() {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("needs_review");

  const query = useQuery({
    queryKey: ["review-queue", page, status],
    queryFn: () => api.reviewQueue({ page, page_size: 25, status }),
  });
  const counts = query.data?.counts ?? {};

  const columns: Column<ReviewRow>[] = [
    { key: "doc", header: "Document", cell: (row) => <span className="font-medium">{row.label}</span> },
    { key: "student", header: "Student", width: "w-[10rem]", cell: (row) => <MaskedApaar value={row.apaar_masked} /> },
    { key: "inst", header: "Institution", cell: (row) => <span className="text-xs">{row.institution_name}</span> },
    { key: "issuer", header: "Issuer check", width: "w-[10rem]", cell: (row) => <span className="text-xs">{row.issuer_label}</span> },
    {
      key: "why",
      header: "Why",
      cell: (row) => (
        <ul className="space-y-0.5 text-xs leading-snug text-muted-foreground">
          {row.reasons
            .filter((reason) => reason.severity !== "info")
            .map((reason) => (
              <li key={reason.code}>{reason.message}</li>
            ))}
        </ul>
      ),
    },
    { key: "status", header: "Status", width: "w-[10rem]", cell: (row) => <VerificationBadge status={row.verification_status} /> },
    { key: "date", header: "Uploaded", width: "w-[7rem]", nowrap: true, cell: (row) => <span className="text-xs">{dateOnly(row.uploaded_at)}</span> },
  ];

  return (
    <>
      <PageHeader
        title="Document review"
        description="Documents the automatic checks could not settle. Each case shows the submitted record beside what the document says, the issuer's answer and the tamper checks."
      />
      <KpiRow>
        <KpiCard label="Needs officer review" value={counts.needs_review ?? 0} tone={(counts.needs_review ?? 0) > 0 ? "warning" : "positive"} icon={<ClipboardList className="h-4 w-4" />} hint="Waiting for a decision" />
        <KpiCard label="Rejected" value={counts.rejected ?? 0} tone="critical" icon={<FileX2 className="h-4 w-4" />} hint="Tampered or contradicted by the issuer" />
        <KpiCard label="Auto-verified" value={counts.auto_verified ?? 0} tone="positive" icon={<ShieldCheck className="h-4 w-4" />} hint="Issuer confirmed and data matched" />
        <KpiCard label="Approved by an officer" value={counts.verified ?? 0} icon={<CheckCircle2 className="h-4 w-4" />} hint="After review" />
      </KpiRow>
      <DataTable
        minWidth="min-w-[66rem]"
        columns={columns}
        rows={query.data?.items ?? []}
        loading={query.isLoading}
        total={query.data?.total}
        page={page}
        pageSize={25}
        onPageChange={setPage}
        onRowClick={(row) => router.push(`/aicte/documents/${row.document_id}`)}
        emptyTitle="Nothing waiting"
        emptyDescription="Every document in this state has been dealt with."
        rowKey={(row) => row.document_id}
        toolbar={
          <TableFilters hint="Select a row to open the case.">
            <Select
              value={status}
              onChange={(event) => {
                setStatus(event.target.value);
                setPage(1);
              }}
              className="w-52"
            >
              <option value="needs_review">Needs officer review</option>
              <option value="rejected">Rejected</option>
              <option value="verified">Approved by an officer</option>
              <option value="auto_verified">Auto-verified</option>
              <option value="all">All documents</option>
            </Select>
          </TableFilters>
        }
      />
    </>
  );
}
