"use client";

/**
 * Retrieve data: search reconciled records by APAAR, institution, programme and year,
 * and export the confirmed ones as CSV. Identifiers stay masked.
 */
import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState } from "react";

import { TableFilters } from "@/components/DataTable";
import { ReconRecordsTable } from "@/components/ReconRecordsTable";
import { PageHeader } from "@/components/ui/page";
import { Button, Input, Select } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api, download } from "@/lib/api";
import { CURRENT_YEAR, RECON_LABELS, RECON_YEARS } from "@/lib/recon";

export default function RetrieveDataPage() {
  const { toast } = useToast();
  const [page, setPage] = useState(1);
  const [apaar, setApaar] = useState("");
  const [institutionId, setInstitutionId] = useState("");
  const [programId, setProgramId] = useState("");
  const [year, setYear] = useState(CURRENT_YEAR);
  const [overall, setOverall] = useState("");

  const institutions = useQuery({ queryKey: ["retrieve-institutions"], queryFn: () => api.institutions({ page_size: 200 }) });
  const query = useQuery({
    queryKey: ["retrieve", apaar, institutionId, programId, year, overall, page],
    queryFn: () =>
      api.reconRecords({
        q: apaar || undefined,
        institution_id: institutionId || undefined,
        program_id: programId || undefined,
        academic_year: year,
        overall: overall || undefined,
        page,
        page_size: 25,
      }),
  });
  const reset = () => setPage(1);

  return (
    <>
      <PageHeader
        title="Retrieve data"
        description="Find reconciled student records by APAAR ID, institution, programme and year. The export holds confirmed records only, with masked identifiers."
        actions={
          <Button
            variant="outline"
            onClick={() =>
              download("/aicte/reconciliation/records.csv", "confirmed_records.csv", {
                q: apaar || undefined,
                institution_id: institutionId || undefined,
                program_id: programId || undefined,
                academic_year: year,
              }).catch((error: Error) => toast(error.message, "danger"))
            }
          >
            <Download className="h-4 w-4" /> Export confirmed (CSV)
          </Button>
        }
      />
      <ReconRecordsTable
        rows={query.data?.items ?? []}
        loading={query.isLoading}
        total={query.data?.total}
        page={page}
        onPageChange={setPage}
        hrefFor={(row) => `/aicte/reconciliation/record/${row.enrolment_id}`}
        toolbar={
          <TableFilters hint="Choose an institution to filter by programme.">
            <Input value={apaar} onChange={(event) => { setApaar(event.target.value); reset(); }} placeholder="APAAR ID or last 4 digits" className="w-52" />
            <Select value={institutionId} onChange={(event) => { setInstitutionId(event.target.value); setProgramId(""); reset(); }} className="w-64">
              <option value="">All institutions</option>
              {(institutions.data?.items ?? []).map((item) => (
                <option key={item.id} value={item.id}>{item.name}</option>
              ))}
            </Select>
            <Select value={programId} onChange={(event) => { setProgramId(event.target.value); reset(); }} className="w-56" disabled={!institutionId}>
              <option value="">All programmes</option>
              {(query.data?.programmes ?? []).map((item) => (
                <option key={item.program_id} value={item.program_id}>{item.label}</option>
              ))}
            </Select>
            <Select value={year} onChange={(event) => { setYear(event.target.value); reset(); }} className="w-28">
              {RECON_YEARS.map((item) => (
                <option key={item}>{item}</option>
              ))}
            </Select>
            <Select value={overall} onChange={(event) => { setOverall(event.target.value); reset(); }} className="w-40">
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
