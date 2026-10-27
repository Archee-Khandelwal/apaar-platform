"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, BadgeCheck, Download } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageHeader, SectionCard, TechnicalDetails } from "@/components/ui/page";
import { ErrorState, Skeleton } from "@/components/States";
import { Button, Select } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";

const YEARS = ["2026-27", "2025-26"];

export default function CertificatePage() {
  const { toast } = useToast();
  const [year, setYear] = useState(YEARS[0]);
  const query = useQuery({
    queryKey: ["certificate-eligibility", year],
    queryFn: () => api.certificateEligibility(year),
  });

  async function openCertificate() {
    try {
      const html = await api.certificateHtml(year);
      const win = window.open("", "_blank");
      if (!win) {
        toast("Allow pop-ups to open the certificate.", "warning");
        return;
      }
      win.document.write(html);
      win.document.close();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Could not open the certificate.", "danger");
    }
  }

  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;

  return (
    <>
      <PageHeader
        title="Certificate"
        description="Whether your institution can be issued a compliance certificate for the year, and what is standing in the way."
        actions={
          <Select value={year} onChange={(event) => setYear(event.target.value)} className="w-36">
            {YEARS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </Select>
        }
      />

      {query.isLoading ? (
        <Skeleton rows={3} height="h-24" />
      ) : query.data?.eligible ? (
        <SectionCard
          className="border-emerald-200"
          title={
            <span className="flex items-center gap-2 text-emerald-900">
              <BadgeCheck className="h-5 w-5" />
              Eligible for {year}
            </span>
          }
        >
          <p className="max-w-2xl text-sm leading-relaxed">
            Your data for {year} is reported and validated, with no open high or critical finding.
            The certificate carries a signed reference, so anyone holding it can check it back
            against the platform.
          </p>
          <Button className="mt-5" onClick={openCertificate}>
            <Download className="h-4 w-4" />
            Open printable certificate
          </Button>
        </SectionCard>
      ) : (
        <SectionCard
          className="border-amber-200"
          title={
            <span className="flex items-center gap-2 text-amber-900">
              <AlertTriangle className="h-5 w-5" />
              Not available for {year} yet
            </span>
          }
        >
          <p className="text-sm font-medium">What is blocking it</p>
          <ul className="mt-2 max-w-2xl space-y-2 text-sm leading-relaxed text-muted-foreground">
            {(query.data?.reasons ?? []).map((reason) => (
              <li key={reason}>• {reason}</li>
            ))}
          </ul>

          <Button asChild variant="outline" className="mt-5">
            <Link href="/institution/flags">Open your flags</Link>
          </Button>
          <p className="mt-3 max-w-2xl text-xs leading-relaxed text-muted-foreground">
            Resolving the findings above is the only way forward: a certificate cannot be issued
            while a serious finding is open against your institution.
          </p>

          {(query.data?.blocking_flags ?? []).length > 0 && (
            <TechnicalDetails label="Blocking flag references" className="mt-5">
              <ul className="space-y-1">
                {query.data!.blocking_flags.map((flag) => (
                  <li key={flag.id} className="font-mono text-xs text-muted-foreground">
                    #{flag.id} · {flag.type}
                  </li>
                ))}
              </ul>
            </TechnicalDetails>
          )}
        </SectionCard>
      )}
    </>
  );
}
