"use client";

/** Drill-down: one institution's students with their reconciliation status. */
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { TableFilters } from "@/components/DataTable";
import { ReconRecordsTable } from "@/components/ReconRecordsTable";
import { PageHeader } from "@/components/ui/page";
import { Input, Select } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { CURRENT_YEAR, RECON_LABELS } from "@/lib/recon";

function InstitutionStudents() {
  const params = useParams<{ id: string }>();
  const institutionId = Number(params.id);
  const year = useSearchParams().get("year") ?? CURRENT_YEAR;
  const [page, setPage] = useState(1);
  const [overall, setOverall] = useState("");
  const [programId, setProgramId] = useState("");
  const [search, setSearch] = useState("");

  const profile = useQuery({ queryKey: ["aicte-institution", institutionId], queryFn: () => api.institution(institutionId) });
  const query = useQuery({
    queryKey: ["recon-records", institutionId, year, overall, programId, search, page],
    queryFn: () =>
      api.reconRecords({
        institution_id: institutionId,
        academic_year: year,
        overall: overall || undefined,
        program_id: programId || undefined,
        q: search || undefined,
        page,
        page_size: 25,
      }),
  });

  return (
    <>
      <Link href="/aicte/reconciliation" className="mb-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-3.5 w-3.5" /> All institutions
      </Link>
      <PageHeader
        title={profile.data?.institution.name ?? "Institution"}
        description={`Reconciliation of every active enrolment reported for ${year}. Select a student to see their record beside AICTE's.`}
      />
      <ReconRecordsTable
        showInstitution={false}
        rows={query.data?.items ?? []}
        loading={query.isLoading}
        total={query.data?.total}
        page={page}
        onPageChange={setPage}
        hrefFor={(row) => `/aicte/reconciliation/record/${row.enrolment_id}`}
        toolbar={
          <TableFilters hint="APAAR search takes the full 12 digits or the last four.">
            <Input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(1);
              }}
              placeholder="APAAR ID or last 4 digits"
              className="w-56"
            />
            <Select value={programId} onChange={(event) => { setProgramId(event.target.value); setPage(1); }} className="w-56">
              <option value="">All programmes</option>
              {(query.data?.programmes ?? []).map((item) => (
                <option key={item.program_id} value={item.program_id}>{item.label}</option>
              ))}
            </Select>
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

export default function InstitutionReconciliationPage() {
  return (
    <Suspense>
      <InstitutionStudents />
    </Suspense>
  );
}
