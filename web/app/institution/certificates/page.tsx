"use client";

/** Issue degree certificates (APAAR ID + student ID + verification QR) for completed enrolments. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, FileDown } from "lucide-react";

import { EmptyState, ErrorState, Skeleton } from "@/components/States";
import { PageHeader, SectionCard } from "@/components/ui/page";
import { Badge, Button } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";

export default function CertificatesPage() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["degree-certificates"], queryFn: api.degreeCertificates });
  const issue = useMutation({
    mutationFn: api.issueDegreeCertificate,
    onSuccess: (out) => {
      queryClient.invalidateQueries({ queryKey: ["degree-certificates"] });
      api.openDegreeCertificate(out.serial);
    },
  });

  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  const items = query.data?.items ?? [];

  return (
    <>
      <PageHeader
        title="Degree certificates"
        description="Issue a signed certificate for a completed enrolment. It prints the APAAR ID beside the student ID and carries a QR that anyone can check on the public verify page."
      />
      <SectionCard
        title="Completed enrolments"
        description="Only students you have marked as completed can receive a certificate."
      >
        {query.isLoading ? (
          <Skeleton rows={3} />
        ) : items.length === 0 ? (
          <EmptyState
            title="No completed enrolments"
            description="Mark students as completed in an upload to issue certificates."
          />
        ) : (
          <ul className="divide-y divide-border">
            {items.map((row) => (
              <li key={row.enrolment_id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium">
                    {row.name_masked}{" "}
                    <span className="font-mono text-xs text-muted-foreground">{row.apaar_masked}</span>
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Student ID <span className="font-mono">{row.student_number}</span> · {row.program} ·{" "}
                    {row.academic_year}
                  </p>
                </div>
                {row.certificate ? (
                  <div className="flex items-center gap-2">
                    <Badge tone={row.certificate.status === "valid" ? "success" : "danger"}>
                      {row.certificate.serial} · {row.certificate.status} · {dateTime(row.certificate.issued_at)}
                    </Badge>
                    {row.certificate.status === "valid" && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => api.openDegreeCertificate(row.certificate!.serial)}
                      >
                        <FileDown className="h-4 w-4" /> Open PDF
                      </Button>
                    )}
                  </div>
                ) : (
                  <Button size="sm" disabled={issue.isPending} onClick={() => issue.mutate(row.enrolment_id)}>
                    <BadgeCheck className="h-4 w-4" /> Issue certificate
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
        {issue.isError && <p className="mt-3 text-sm text-red-700">{(issue.error as Error).message}</p>}
      </SectionCard>
    </>
  );
}
