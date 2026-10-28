"use client";

/**
 * One record side by side: what the institution submitted, the APAAR registry's answer
 * and the documents on the left; AICTE's own records and the six checks on the right.
 * Identifiers are masked; an officer can reveal them with a logged reason.
 */
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { VerificationBadge } from "@/components/DocumentStatusBadge";
import { MaskedApaar, MaskedName } from "@/components/Masked";
import { CheckBadge, ReconBadge } from "@/components/ReconBadge";
import { RevealButton } from "@/components/RevealButton";
import { ErrorState, LoadingSkeleton } from "@/components/States";
import { FieldList, PageHeader, SectionCard } from "@/components/ui/page";
import { Badge } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dateOnly, dateTime } from "@/lib/format";
import type { VerificationStatus } from "@/lib/types";

const text = (value: unknown) => (value === null || value === undefined || value === "" ? "—" : String(value).replace(/_/g, " "));

export default function ReconciliationRecordPage() {
  const params = useParams<{ id: string }>();
  const { user } = useAuth();
  const query = useQuery({ queryKey: ["recon-record", params.id], queryFn: () => api.reconRecord(Number(params.id)) });

  if (query.isLoading) return <LoadingSkeleton rows={8} />;
  if (query.isError || !query.data) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  const record = query.data;
  const submitted = record.submitted;

  return (
    <>
      <Link href={`/aicte/reconciliation/institution/${record.institution_id}?year=${record.academic_year}`} className="mb-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-3.5 w-3.5" /> {record.institution_name}
      </Link>
      <PageHeader
        title="Student record"
        description={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <MaskedApaar value={record.apaar_masked} />
            <MaskedName value={record.name_masked} />
            <ReconBadge status={record.overall} />
            <span>{record.programme}, {record.academic_year}. Checked {dateTime(record.computed_at)}.</span>
          </span>
        }
        actions={user?.role === "aicte_officer" ? <RevealButton studentId={record.student_id} /> : undefined}
      />

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="space-y-5">
          <SectionCard title="Submitted by the institution" description={record.institution_name}>
            <FieldList
              fields={[
                { label: "Programme", value: record.programme },
                { label: "Admission type", value: text(record.admission_type) },
                { label: "Year of study", value: record.year_of_study },
                { label: "Admitted on", value: dateOnly(String(submitted.admitted_on ?? "")) },
                { label: "Enrolment status", value: text(submitted.enrolment_status) },
                { label: "Category", value: text(submitted.category) },
                { label: "Nationality status", value: text(submitted.nationality_status).toUpperCase() },
                { label: "Gender", value: text(submitted.gender) },
                { label: "Birth year", value: text(submitted.dob_year) },
                { label: "Minor", value: submitted.is_minor ? "Yes: parental consent required" : "No" },
              ]}
            />
          </SectionCard>

          <SectionCard title="APAAR registry" description="Format check plus a lookup in the (mock) registry.">
            <p className="text-sm font-medium">{record.apaar.result}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              APAAR status reported: {text(record.apaar.apaar_status)} · registry answer: {text(record.apaar.registry_status)}
            </p>
          </SectionCard>

          <SectionCard title="Documents" description="What this student's admission requires, and where each stands.">
            <ul className="divide-y divide-border text-sm">
              {record.documents.map((item) => (
                <li key={item.doc_type} className="flex items-center justify-between gap-3 py-2">
                  <span>{item.label}</span>
                  {item.status === "missing" ? <Badge>missing</Badge> : <VerificationBadge status={item.status as VerificationStatus} />}
                </li>
              ))}
              {record.documents.length === 0 && <li className="py-2 text-xs text-muted-foreground">No documents are required.</li>}
            </ul>
          </SectionCard>
        </div>

        <div className="space-y-5">
          <SectionCard title="AICTE's records" description="Imported or seeded by AICTE. The institution cannot change them.">
            <FieldList
              fields={[
                { label: "Institution approval", value: text(record.master.institution_status) },
                { label: "Approval reference", value: record.master.institution_reference ?? "—" },
                { label: "Programme for the year", value: text(record.master.programme_status) },
                { label: "Approved intake", value: record.master.approved_intake ?? "—" },
              ]}
            />
            {Object.keys(record.master.supernumerary_caps).length > 0 && (
              <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
                Supernumerary caps:{" "}
                {Object.entries(record.master.supernumerary_caps).map(([key, value]) => `${key.replace(/_/g, " ")} ${value}`).join(", ")}.
              </p>
            )}
          </SectionCard>

          <SectionCard title="The six checks" description="Any fail rejects the record; any review leaves it for review.">
            <ol className="space-y-4">
              {record.checks.map((check) => (
                <li key={check.check}>
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm font-medium">{check.label}</p>
                    <CheckBadge result={check.result} />
                  </div>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{check.message}</p>
                  {check.fix && check.result !== "pass" && (
                    <p className="mt-1 text-xs leading-relaxed"><span className="font-medium">To resolve:</span> {check.fix}</p>
                  )}
                </li>
              ))}
            </ol>
          </SectionCard>
        </div>
      </div>
    </>
  );
}
