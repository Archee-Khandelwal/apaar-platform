"use client";

/**
 * Reconciliation dashboard: every institution's records checked against AICTE's own
 * approvals, counted by status. Officers can also import the master records here.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ClipboardList, Download, FileSpreadsheet, XCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { DataTable, TableFilters, type Column } from "@/components/DataTable";
import { KpiCard, KpiRow, PageHeader, SectionCard } from "@/components/ui/page";
import { Badge, Button, Input, Select, Spinner } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api, download } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { count, dateTime } from "@/lib/format";
import { CURRENT_YEAR, RECON_YEARS, saveText } from "@/lib/recon";
import type { MasterImport, ReconInstitutionRow } from "@/lib/types";

type Kind = "institutions" | "programmes";

function MasterImportCard() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const institutionsInput = useRef<HTMLInputElement>(null);
  const programmesInput = useRef<HTMLInputElement>(null);
  const [last, setLast] = useState<MasterImport | null>(null);
  const status = useQuery({ queryKey: ["master-status"], queryFn: api.masterStatus });

  const upload = useMutation({
    mutationFn: ({ kind, file }: { kind: Kind; file: File }) => api.masterImport(kind, file),
    onSuccess: (result) => {
      setLast(result);
      toast(`${result.rows_ok} of ${result.rows_total} rows imported.`, result.rows_error ? "warning" : "success");
      queryClient.invalidateQueries({ queryKey: ["master-status"] });
      queryClient.invalidateQueries({ queryKey: ["recon-summary"] });
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  const pick = (kind: Kind) => (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) upload.mutate({ kind, file });
    event.target.value = "";
  };
  const approvals = status.data?.approvals ?? {};
  const programmes = status.data?.programme_records ?? {};
  const summarise = (values: Record<string, number>) =>
    Object.entries(values).map(([key, value]) => `${value} ${key.replace(/_/g, " ")}`).join(", ") || "none";

  return (
    <SectionCard
      title="AICTE master records"
      description="The approvals every submitted record is checked against. Import them from CSV or Excel; records are re-checked straight away."
      actions={
        <>
          <input ref={institutionsInput} type="file" accept=".csv,.xlsx" className="hidden" onChange={pick("institutions")} />
          <input ref={programmesInput} type="file" accept=".csv,.xlsx" className="hidden" onChange={pick("programmes")} />
          <Button variant="outline" onClick={() => institutionsInput.current?.click()} disabled={upload.isPending}>
            {upload.isPending ? <Spinner /> : <FileSpreadsheet className="h-4 w-4" />} Import institution approvals
          </Button>
          <Button variant="outline" onClick={() => programmesInput.current?.click()} disabled={upload.isPending}>
            <FileSpreadsheet className="h-4 w-4" /> Import programmes and intake
          </Button>
        </>
      }
    >
      <p className="text-xs leading-relaxed text-muted-foreground">
        Institution approvals on record: {summarise(approvals)}. Programme-year records: {summarise(programmes)}.
        Templates:{" "}
        <button type="button" className="underline" onClick={() => api.masterTemplate("institutions").then((text) => saveText(text, "institution_approvals.csv"))}>
          institution approvals
        </button>
        ,{" "}
        <button type="button" className="underline" onClick={() => api.masterTemplate("programmes").then((text) => saveText(text, "programmes_and_intake.csv"))}>
          programmes and intake
        </button>
        .
      </p>
      {last && (
        <div className="mt-4 rounded-md border border-border text-xs">
          <p className="border-b border-border px-4 py-2 font-medium">
            {last.filename}: {last.rows_ok} imported · {last.rows_error} skipped
          </p>
          {last.issues.length > 0 && (
            <ul className="max-h-48 divide-y divide-border overflow-y-auto">
              {last.issues.map((issue) => (
                <li key={issue.row} className="flex gap-2 px-4 py-2">
                  <Badge tone="danger">row {issue.row}</Badge>
                  <span className="text-muted-foreground">{issue.message}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {!last && status.data && status.data.imports.length > 0 && (
        <p className="mt-3 text-xs text-muted-foreground">
          Last import: {status.data.imports[0].filename} by {status.data.imports[0].actor}, {dateTime(status.data.imports[0].created_at)}.
        </p>
      )}
    </SectionCard>
  );
}

export default function ReconciliationDashboard() {
  const router = useRouter();
  const { user } = useAuth();
  const [year, setYear] = useState(CURRENT_YEAR);
  const [search, setSearch] = useState("");
  const query = useQuery({
    queryKey: ["recon-summary", year, search],
    queryFn: () => api.reconSummary({ academic_year: year, q: search || undefined }),
  });
  const totals = query.data?.totals;

  const columns: Column<ReconInstitutionRow>[] = [
    { key: "name", header: "Institution", cell: (row) => <span className="font-medium">{row.name}</span> },
    { key: "state", header: "State", width: "w-[10rem]", cell: (row) => <span className="text-xs">{row.state}</span> },
    { key: "records", header: "Records", width: "w-[6rem]", align: "right", cell: (row) => count(row.records) },
    { key: "confirmed", header: "Confirmed", width: "w-[6rem]", align: "right", cell: (row) => count(row.confirmed) },
    { key: "review", header: "Needs review", width: "w-[7rem]", align: "right", cell: (row) => count(row.needs_review) },
    { key: "rejected", header: "Rejected", width: "w-[6rem]", align: "right", cell: (row) => count(row.rejected) },
  ];

  return (
    <>
      <PageHeader
        title="Reconciliation"
        description="Each submitted record checked against AICTE's own: institution approved, programme approved for the year, within approved intake, APAAR verified, documents verified, no duplicate enrolment."
        actions={
          <Button variant="outline" onClick={() => download("/aicte/reconciliation/records.csv", "confirmed_records.csv", { academic_year: year })}>
            <Download className="h-4 w-4" /> Export confirmed records
          </Button>
        }
      />
      <KpiRow>
        <KpiCard label="Records checked" value={totals?.records} icon={<ClipboardList className="h-4 w-4" />} hint={`Active enrolments, ${year}`} />
        <KpiCard label="Confirmed" value={totals?.confirmed} tone="positive" icon={<CheckCircle2 className="h-4 w-4" />} hint="All six checks passed" />
        <KpiCard label="Needs review" value={totals?.needs_review} tone="warning" icon={<ClipboardList className="h-4 w-4" />} hint="Something is missing or unsettled" />
        <KpiCard label="Rejected" value={totals?.rejected} tone="critical" icon={<XCircle className="h-4 w-4" />} hint="A check failed" />
      </KpiRow>
      {user?.role === "aicte_officer" && <MasterImportCard />}
      <DataTable
        minWidth="min-w-[52rem]"
        columns={columns}
        rows={query.data?.items ?? []}
        loading={query.isLoading}
        onRowClick={(row) => router.push(`/aicte/reconciliation/institution/${row.institution_id}?year=${year}`)}
        emptyTitle="No records for this year"
        rowKey={(row) => row.institution_id}
        toolbar={
          <TableFilters hint="Institutions with the most open problems come first. Select one to see its students.">
            <Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search institution" className="w-56" />
            <Select value={year} onChange={(event) => setYear(event.target.value)} className="w-32">
              {RECON_YEARS.map((item) => (
                <option key={item}>{item}</option>
              ))}
            </Select>
          </TableFilters>
        }
      />
    </>
  );
}
