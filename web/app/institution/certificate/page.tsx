"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, BadgeCheck, Download } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/AppShell";
import { ErrorState, LoadingSkeleton } from "@/components/States";
import { Button, Card, CardContent, CardHeader, CardTitle, Select } from "@/components/ui/primitives";
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
        title="Compliance certificate"
        description="Issued when no high or critical finding is open against your institution for the year."
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
        <LoadingSkeleton rows={3} />
      ) : query.data?.eligible ? (
        <Card className="border-emerald-300 bg-emerald-50/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-emerald-900">
              <BadgeCheck className="h-5 w-5" />
              Eligible for {year}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-emerald-900">
              Your data for {year} is reported and validated, with no open high or critical finding.
              The certificate carries a signed reference so it can be checked back against the
              platform.
            </p>
            <Button onClick={openCertificate}>
              <Download className="h-4 w-4" />
              Open printable certificate
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card className="border-amber-300 bg-amber-50/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-amber-900">
              <AlertTriangle className="h-5 w-5" />
              Not available for {year} yet
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <ul className="space-y-1.5 text-sm text-amber-900">
              {(query.data?.reasons ?? []).map((reason) => (
                <li key={reason}>• {reason}</li>
              ))}
            </ul>
            {(query.data?.blocking_flags ?? []).length > 0 && (
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-amber-900">
                  Findings to clear first
                </p>
                <ul className="mt-1 space-y-1 text-sm">
                  {query.data!.blocking_flags.map((flag) => (
                    <li key={flag.id} className="font-mono text-xs">
                      #{flag.id} · {flag.type}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <Button asChild variant="outline">
              <Link href="/institution/flags">Open the flag inbox</Link>
            </Button>
            <p className="text-xs text-amber-900">
              The button above is the only way forward: a certificate cannot be issued while a
              serious finding is open.
            </p>
          </CardContent>
        </Card>
      )}
    </>
  );
}
