"use client";

/** Demo control panel: reseed, inject one scenario, and prove the audit chain works. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Database, PlayCircle, RefreshCw, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/AppShell";
import { ErrorState, LoadingSkeleton } from "@/components/States";
import { Button, Card, CardContent, CardHeader, CardTitle, Spinner } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { flagLabel } from "@/lib/format";
import type { TamperResult } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function AdminPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [tamper, setTamper] = useState<TamperResult | null>(null);
  const [busyScenario, setBusyScenario] = useState<string | null>(null);

  const status = useQuery({ queryKey: ["admin-status"], queryFn: api.adminStatus });
  const scenarios = useQuery({ queryKey: ["admin-scenarios"], queryFn: api.adminScenarios });

  function refreshAll() {
    queryClient.invalidateQueries();
  }

  const reseed = useMutation({
    mutationFn: () => api.reseed(),
    onSuccess: (result) => {
      toast(
        `Reseeded ${result.counts.students} students across ${result.counts.institutions} institutions in ${(result.duration_ms / 1000).toFixed(1)}s.`,
        "success",
      );
      refreshAll();
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  const loadScenario = useMutation({
    mutationFn: (name: string) => api.loadScenario(name),
    onMutate: (name) => setBusyScenario(name),
    onSuccess: (result) => {
      const gained = Object.entries(result.flags_after)
        .map(([type, after]) => `${flagLabel(type)} ${result.flags_before[type]} → ${after}`)
        .join(", ");
      toast(`${result.label}: added ${result.added.students} students. ${gained}`, "success");
      refreshAll();
    },
    onError: (error: Error) => toast(error.message, "danger"),
    onSettled: () => setBusyScenario(null),
  });

  const verify = useMutation({
    mutationFn: api.verifyAudit,
    onSuccess: (result) => {
      toast(
        result.ok
          ? `Audit chain verified across ${result.rows_checked} rows.`
          : `Chain broken at row ${(result.first_broken_row as { id?: number } | null)?.id}.`,
        result.ok ? "success" : "danger",
      );
      queryClient.invalidateQueries({ queryKey: ["admin-status"] });
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  const runTamper = useMutation({
    mutationFn: api.tamperTest,
    onSuccess: (result) => {
      setTamper(result);
      toast(result.detected ? "Tampering detected, as it should be." : "Tampering was NOT detected.", result.detected ? "success" : "danger");
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  const detectors = useMutation({
    mutationFn: api.runDetectors,
    onSuccess: () => {
      toast("Detectors re-run. Flags are updated in place, never duplicated.", "success");
      refreshAll();
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  if (status.isError) return <ErrorState error={status.error} onRetry={status.refetch} />;

  return (
    <>
      <PageHeader
        title="Demo controls"
        description="Reseed the dataset, inject a single scenario live, and prove the audit chain detects tampering."
        actions={
          <Button variant="outline" onClick={() => status.refetch()} disabled={status.isFetching}>
            <RefreshCw className="h-4 w-4" />
            Refresh
          </Button>
        }
      />

      {status.isLoading || !status.data ? (
        <LoadingSkeleton rows={6} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-4">
            {Object.entries(status.data.counts).map(([key, value]) => (
              <div key={key} className="rounded-lg border border-border bg-card p-4">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {key}
                </p>
                <p className="mt-1.5 text-2xl font-semibold tabular-nums">
                  {value.toLocaleString("en-IN")}
                </p>
              </div>
            ))}
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Database className="h-4 w-4" />
                  Dataset
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-sm text-muted-foreground">
                  Reseeding wipes every table and regenerates 40 institutions and about 15,000
                  students from seed 42, then runs every detector. It takes roughly 15 seconds.
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button onClick={() => reseed.mutate()} disabled={reseed.isPending}>
                    {reseed.isPending && <Spinner />}
                    Reset &amp; reseed demo data
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => detectors.mutate()}
                    disabled={detectors.isPending}
                  >
                    {detectors.isPending && <Spinner />}
                    Re-run detectors
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Current academic year: {status.data.current_academic_year}
                </p>
              </CardContent>
            </Card>

            <Card className={status.data.audit.ok ? "border-emerald-300" : "border-red-300"}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <ShieldCheck className="h-4 w-4" />
                  Audit chain
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p
                  className={cn(
                    "flex items-center gap-2 text-sm font-medium",
                    status.data.audit.ok ? "text-emerald-700" : "text-red-700",
                  )}
                >
                  {status.data.audit.ok ? (
                    <CheckCircle2 className="h-4 w-4" />
                  ) : (
                    <AlertTriangle className="h-4 w-4" />
                  )}
                  {status.data.audit.ok
                    ? `Intact across ${status.data.audit.rows_total} rows`
                    : "The chain is broken"}
                </p>
                <p className="text-sm text-muted-foreground">
                  Each row stores <code className="font-mono text-xs">prev_hash</code> and{" "}
                  <code className="font-mono text-xs">
                    hash = sha256(prev_hash + canonical_json(row))
                  </code>
                  , so editing or deleting any row breaks every hash after it.
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button variant="outline" onClick={() => verify.mutate()} disabled={verify.isPending}>
                    {verify.isPending && <Spinner />}
                    Verify the chain
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => runTamper.mutate()}
                    disabled={runTamper.isPending}
                  >
                    {runTamper.isPending && <Spinner />}
                    Run the tamper test
                  </Button>
                </div>
                {tamper && (
                  <div
                    className={cn(
                      "rounded-md border p-3 text-sm",
                      tamper.detected
                        ? "border-emerald-300 bg-emerald-50 text-emerald-900"
                        : "border-red-300 bg-red-50 text-red-900",
                    )}
                  >
                    <p className="font-medium">
                      {tamper.detected ? "Detected" : "Not detected"} — row{" "}
                      {tamper.tampered_row_id} was edited in a copy of {tamper.copy_rows} rows.
                    </p>
                    <p className="mt-1 text-xs">{tamper.message}</p>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          <Card className="mt-4">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <PlayCircle className="h-4 w-4" />
                Inject a scenario live
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="mb-3 text-sm text-muted-foreground">
                Each button injects that scenario into the current database and re-runs the
                detectors, so you can show a finding appearing during the demo.
              </p>
              <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                {(scenarios.data?.scenarios ?? []).map((scenario) => (
                  <button
                    key={scenario.name}
                    type="button"
                    onClick={() => loadScenario.mutate(scenario.name)}
                    disabled={loadScenario.isPending}
                    className="flex items-start justify-between gap-2 rounded-md border border-border bg-card p-3 text-left transition-colors hover:border-primary hover:bg-primary/5 disabled:opacity-60"
                  >
                    <span className="min-w-0">
                      <span className="block text-sm font-medium">{scenario.label}</span>
                      <span className="block truncate font-mono text-xs text-muted-foreground">
                        {scenario.name}
                      </span>
                    </span>
                    {busyScenario === scenario.name && <Spinner className="mt-1" />}
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card className="mt-4">
            <CardHeader>
              <CardTitle>Flags in the database</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {Object.entries(status.data.flags_by_type).map(([type, count]) => (
                  <span
                    key={type}
                    className="inline-flex items-center gap-2 rounded border border-border px-2.5 py-1 text-xs"
                  >
                    {flagLabel(type)}
                    <span className="font-semibold tabular-nums">{count}</span>
                  </span>
                ))}
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </>
  );
}
