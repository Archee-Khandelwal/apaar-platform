"use client";

/**
 * Document submission: every enrolled student with their checklist progress, and a ZIP
 * upload for doing a whole batch at once.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileArchive, FileWarning, Upload, XCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { DataTable, TableFilters, type Column } from "@/components/DataTable";
import { ChecklistBadge } from "@/components/DocumentStatusBadge";
import { MaskedApaar, MaskedName } from "@/components/Masked";
import { KpiCard, KpiRow, PageHeader, SectionCard } from "@/components/ui/page";
import { Badge, Button, Input, Select, Spinner } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import type { BulkUploadReport, DocumentOverviewRow } from "@/lib/types";

export default function DocumentsPage() {
  const router = useRouter();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const zipInput = useRef<HTMLInputElement>(null);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [report, setReport] = useState<BulkUploadReport | null>(null);

  const rules = useQuery({ queryKey: ["document-rules"], queryFn: api.documentRules, staleTime: Infinity });
  const query = useQuery({
    queryKey: ["documents-overview", page, status, search],
    queryFn: () =>
      api.documentsOverview({ page, page_size: 25, status: status || undefined, q: search || undefined }),
  });

  const labels = Object.fromEntries((rules.data?.document_types ?? []).map((item) => [item.doc_type, item.label]));
  const totals = query.data?.totals;

  const bulk = useMutation({
    mutationFn: (file: File) => api.uploadDocumentsZip(file),
    onSuccess: (result) => {
      setReport(result);
      toast(`${result.stored} of ${result.files} files stored.`, result.rejected ? "warning" : "success");
      queryClient.invalidateQueries({ queryKey: ["documents-overview"] });
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  const columns: Column<DocumentOverviewRow>[] = [
    { key: "apaar", header: "APAAR ID", width: "w-[10rem]", cell: (row) => <MaskedApaar value={row.apaar_masked} /> },
    { key: "name", header: "Student", cell: (row) => <MaskedName value={row.name_masked} /> },
    {
      key: "type",
      header: "Admission",
      width: "w-[9rem]",
      cell: (row) => (
        <span className="text-xs text-muted-foreground">
          {row.admission_type.replace(/_/g, " ")}
          {row.nationality_status !== "indian" && ` · ${row.nationality_status.toUpperCase()}`}
        </span>
      ),
    },
    {
      key: "progress",
      header: "Checklist",
      width: "w-[11rem]",
      cell: (row) => (
        <span className="text-xs tabular-nums">
          {row.counts.verified} verified · {row.counts.uploaded} uploaded · {row.counts.missing} missing
        </span>
      ),
    },
    {
      key: "missing",
      header: "Still needed",
      cell: (row) =>
        row.missing.length ? (
          <span className="text-xs text-muted-foreground">{row.missing.map((type) => labels[type] ?? type).join(", ")}</span>
        ) : (
          "—"
        ),
    },
    { key: "status", header: "Status", width: "w-[7rem]", cell: (row) => <ChecklistBadge status={row.status} /> },
  ];

  return (
    <>
      <PageHeader
        title="Documents"
        description="Attach the documents each student's admission rests on. Every file is checked by its contents, encrypted, and its SHA-256 recorded so later tampering is detectable."
      />

      <KpiRow>
        <KpiCard label="Complete and verified" value={totals?.verified ?? "—"} tone="positive" icon={<CheckCircle2 className="h-4 w-4" />} hint="Every required document verified" />
        <KpiCard label="Awaiting checks" value={totals?.uploaded ?? "—"} hint="Uploaded, being verified or reviewed" icon={<Upload className="h-4 w-4" />} />
        <KpiCard label="Missing documents" value={totals?.missing ?? "—"} tone={(totals?.missing ?? 0) > 0 ? "warning" : "positive"} hint="Students with a document still to upload" icon={<FileWarning className="h-4 w-4" />} />
        <KpiCard label="Rejected" value={totals?.rejected ?? "—"} tone={(totals?.rejected ?? 0) > 0 ? "critical" : "positive"} hint="Students with a document to replace" icon={<XCircle className="h-4 w-4" />} />
      </KpiRow>

      <SectionCard
        title="Upload many at once"
        description="A ZIP of files named <APAAR ID or student id>_<document type>.pdf — or one folder per student holding <document type>.pdf. PDF, JPEG or PNG, up to the size limit each."
        actions={
          <>
            <input
              ref={zipInput}
              type="file"
              accept=".zip,application/zip"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) bulk.mutate(file);
                event.target.value = "";
              }}
            />
            <Button onClick={() => zipInput.current?.click()} disabled={bulk.isPending}>
              {bulk.isPending ? <Spinner /> : <FileArchive className="h-4 w-4" />}
              Choose ZIP
            </Button>
          </>
        }
      >
        <p className="text-xs leading-relaxed text-muted-foreground">
          Document types:{" "}
          {(rules.data?.document_types ?? []).map((item, index) => (
            <span key={item.doc_type}>
              {index > 0 && ", "}
              <code className="font-mono text-foreground">{item.doc_type}</code>
            </span>
          ))}
          . Limits: {rules.data?.limits.max_file_mb ?? 5} MB per file, {rules.data?.limits.zip_max_files ?? 500} files per ZIP.
        </p>
        {report && (
          <div className="mt-4 rounded-md border border-border">
            <p className="border-b border-border px-4 py-2 text-sm font-medium">
              {report.stored} stored · {report.rejected} rejected · {report.skipped} skipped
            </p>
            <ul className="max-h-64 divide-y divide-border overflow-y-auto text-xs">
              {report.results.map((row) => (
                <li key={row.file} className="flex flex-wrap items-start gap-2 px-4 py-2">
                  <Badge tone={row.status === "stored" ? "success" : row.status === "rejected" ? "danger" : "neutral"}>
                    {row.status}
                  </Badge>
                  <code className="font-mono">{row.file}</code>
                  {row.reason && <span className="text-muted-foreground">— {row.reason}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </SectionCard>

      <DataTable
        minWidth="min-w-[60rem]"
        columns={columns}
        rows={query.data?.items ?? []}
        loading={query.isLoading}
        total={query.data?.total}
        page={page}
        pageSize={25}
        onPageChange={setPage}
        onRowClick={(row) => router.push(`/institution/documents/${row.student_id}`)}
        emptyTitle="No students match"
        rowKey={(row) => row.student_id}
        toolbar={
          <TableFilters hint="Select a student to upload or replace their documents.">
            <Input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(1);
              }}
              placeholder="Last 4 APAAR digits or student id"
              className="w-60"
            />
            <Select
              value={status}
              onChange={(event) => {
                setStatus(event.target.value);
                setPage(1);
              }}
              className="w-44"
            >
              <option value="">Any status</option>
              <option value="missing">Missing documents</option>
              <option value="uploaded">Awaiting checks</option>
              <option value="verified">Verified</option>
              <option value="rejected">Rejected</option>
            </Select>
          </TableFilters>
        }
      />
    </>
  );
}
