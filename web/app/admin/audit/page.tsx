"use client";

/**
 * The audit chain, on its own page.
 *
 * Every audit row stores prev_hash and hash = sha256(prev_hash + canonical_json(row)),
 * so editing or deleting a row breaks every hash after it. This page proves that
 * claim rather than asserting it: verify the live chain, then run the tamper test.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Link2, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { ErrorState, KpiSkeleton } from "@/components/States";
import { KpiCard, KpiRow, PageHeader, SectionCard, TechnicalDetails } from "@/components/ui/page";
import { Button, Spinner } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { TamperResult } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function AuditLogPage() {
  const { toast } = useToast();
  const [tamper, setTamper] = useState<TamperResult | null>(null);

  const status = useQuery({ queryKey: ["admin-status"], queryFn: api.adminStatus });

  const verify = useMutation({
    mutationFn: api.verifyAudit,
    onSuccess: (result) => {
      toast(
        result.ok
          ? `Audit chain verified across ${result.rows_checked} rows.`
          : `Chain broken at row ${(result.first_broken_row as { id?: number } | null)?.id}.`,
        result.ok ? "success" : "danger",
      );
      status.refetch();
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  const runTamper = useMutation({
    mutationFn: api.tamperTest,
    onSuccess: (result) => {
      setTamper(result);
      toast(
        result.detected ? "Tampering detected, as it should be." : "Tampering was NOT detected.",
        result.detected ? "success" : "danger",
      );
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  if (status.isError) return <ErrorState error={status.error} onRetry={status.refetch} />;

  const audit = status.data?.audit;
  const lastVerified = verify.data;

  return (
    <>
      <PageHeader
        title="Audit log"
        description="Whether the audit trail has been altered since it was written, and proof that an alteration would be caught."
        actions={
          <Button onClick={() => verify.mutate()} disabled={verify.isPending}>
            {verify.isPending ? <Spinner /> : <ShieldCheck className="h-4 w-4" />}
            Verify the chain
          </Button>
        }
      />

      {status.isLoading || !audit ? (
        <KpiSkeleton count={3} />
      ) : (
        <>
          <KpiRow className="xl:grid-cols-3">
            <KpiCard
              label="Chain status"
              value={audit.ok ? "Intact" : "Broken"}
              hint={
                audit.ok
                  ? "Every row's hash matches the row before it"
                  : "A row no longer matches its recorded hash"
              }
              tone={audit.ok ? "positive" : "critical"}
              icon={audit.ok ? <CheckCircle2 className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
            />
            <KpiCard
              label="Rows in the log"
              value={audit.rows_total}
              hint="Every state change, reveal and consent decision"
              icon={<Link2 className="h-4 w-4" />}
            />
            <KpiCard
              label="Rows checked"
              value={lastVerified?.rows_checked ?? audit.rows_checked}
              hint={
                lastVerified
                  ? `Last verified ${dateTime(lastVerified.checked_at)}`
                  : "Press “Verify the chain” to re-check now"
              }
            />
          </KpiRow>

          <SectionCard
            title="How the chain works"
            description="Plain English first; the formula is under technical details."
          >
            <ol className="space-y-4">
              {[
                "Anything that changes the record — a flag moving status, an officer revealing a student, a consent being approved or withdrawn — writes one row to the audit log.",
                "Each row carries a fingerprint of itself and of the row before it, so the rows form a chain.",
                "Editing or deleting any row changes its fingerprint, and every fingerprint after it stops matching. There is no way to quietly rewrite history.",
              ].map((step, index) => (
                <li key={index} className="flex gap-3">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                    {index + 1}
                  </span>
                  <span className="text-sm leading-relaxed">{step}</span>
                </li>
              ))}
            </ol>

            <TechnicalDetails className="mt-5">
              <p className="text-xs leading-relaxed text-muted-foreground">
                Each row stores <code className="font-mono text-foreground">prev_hash</code> and{" "}
                <code className="font-mono text-foreground">
                  hash = sha256(prev_hash + canonical_json(row))
                </code>
                . Verification walks the table in insertion order and recomputes every hash.
                {audit.first_broken_row && (
                  <>
                    {" "}
                    First broken row:{" "}
                    <code className="font-mono text-foreground">
                      {JSON.stringify(audit.first_broken_row)}
                    </code>
                  </>
                )}
              </p>
            </TechnicalDetails>
          </SectionCard>

          <SectionCard
            title="Tamper test"
            description="Copies the log, edits one row in the copy, and re-verifies. The live audit log is never touched."
          >
            <Button
              variant="outline"
              onClick={() => runTamper.mutate()}
              disabled={runTamper.isPending}
            >
              {runTamper.isPending && <Spinner />}
              Run the tamper test
            </Button>

            {tamper && (
              <div
                className={cn(
                  "mt-4 rounded-md border p-4",
                  tamper.detected
                    ? "border-emerald-200 bg-emerald-50 text-emerald-900"
                    : "border-red-200 bg-red-50 text-red-900",
                )}
              >
                <p className="flex items-start gap-2 text-sm font-semibold">
                  {tamper.detected ? (
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                  ) : (
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  )}
                  {tamper.detected ? "Detected" : "Not detected"}
                </p>
                <p className="mt-1.5 text-sm leading-relaxed">{tamper.message}</p>
                <TechnicalDetails className="mt-3 border-current/20 bg-white/50">
                  <p className="text-xs leading-relaxed">
                    Edited row id {tamper.tampered_row_id} in a copy of {tamper.copy_rows} rows;
                    verification first failed at row {tamper.first_broken_row_id ?? "—"}.
                  </p>
                </TechnicalDetails>
              </div>
            )}
          </SectionCard>
        </>
      )}
    </>
  );
}
