"use client";

/**
 * The institution's own reconciliation status: how many of its records AICTE has
 * confirmed, and exactly what to fix for the rest.
 */
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, ClipboardList, XCircle } from "lucide-react";
import { useState } from "react";

import { TableFilters } from "@/components/DataTable";
import { ReconRecordsTable } from "@/components/ReconRecordsTable";
import { ErrorState } from "@/components/States";
import { KpiCard, KpiRow, PageHeader, SectionCard } from "@/components/ui/page";
import { Badge, Select } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { CURRENT_YEAR, RECON_LABELS } from "@/lib/recon";

export default function InstitutionReconciliationPage() {
  const [page, setPage] = useState(1);
  const [overall, setOverall] = useState("");
  const query = useQuery({
    queryKey: ["institution-recon", CURRENT_YEAR, overall, page],
    queryFn: () => api.institutionRecon({ academic_year: CURRENT_YEAR, overall: overall || undefined, page, page_size: 25 }),
  });
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  const data = query.data;

  return (
    <>
      <PageHeader
        title="Reconciliation"
        description={`AICTE checks each record you reported for ${CURRENT_YEAR} against its own: your approval, the programme's approval and intake, the APAAR registry, the documents and duplicate enrolment. Records AICTE cannot confirm are listed with what to do.`}
      />
      <KpiRow>
        <KpiCard label="Records reported" value={data?.records} icon={<ClipboardList className="h-4 w-4" />} hint={`Active enrolments, ${CURRENT_YEAR}`} />
        <KpiCard label="Confirmed" value={data?.counts.confirmed} tone="positive" icon={<CheckCircle2 className="h-4 w-4" />} hint="All six checks passed" />
        <KpiCard label="Needs review" value={data?.counts.needs_review} tone="warning" icon={<ClipboardList className="h-4 w-4" />} hint="Something to add or wait for" />
        <KpiCard label="Rejected" value={data?.counts.rejected} tone="critical" icon={<XCircle className="h-4 w-4" />} hint="Needs a correction" />
      </KpiRow>

      <SectionCard title="What to fix" description="Grouped by check, failures first.">
        {data && data.to_fix.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing outstanding. Every record is confirmed.</p>
        ) : (
          <ul className="divide-y divide-border">
            {(data?.to_fix ?? []).map((item) => (
              <li key={`${item.check}-${item.fix}`} className="flex flex-wrap items-start justify-between gap-3 py-3">
                <div className="min-w-0 max-w-3xl">
                  <p className="text-sm font-medium">{item.label}</p>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{item.example}</p>
                  {item.fix && <p className="mt-1 text-xs leading-relaxed"><span className="font-medium">What to do:</span> {item.fix}</p>}
                </div>
                <Badge tone={item.result === "fail" ? "danger" : "warning"}>
                  {item.records} record{item.records === 1 ? "" : "s"}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      <ReconRecordsTable
        showInstitution={false}
        rows={data?.items ?? []}
        loading={query.isLoading}
        total={data?.total}
        page={page}
        onPageChange={setPage}
        toolbar={
          <TableFilters hint="The reason for each status is shown beside the record.">
            <Select value={overall} onChange={(event) => { setOverall(event.target.value); setPage(1); }} className="w-44">
              <option value="">Any status</option>
              {Object.entries(RECON_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </Select>
          </TableFilters>
        }
      />
    </>
  );
}
