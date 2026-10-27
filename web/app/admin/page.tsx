"use client";

/** Demo control panel: reseed the dataset and inject one scenario live. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, PlayCircle, RefreshCw, Rows3, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { ErrorState, KpiSkeleton, Skeleton } from "@/components/States";
import { KpiCard, KpiRow, PageHeader, SectionCard } from "@/components/ui/page";
import { Button, Spinner } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { flagLabel } from "@/lib/format";
import { useState } from "react";

/** The four counts a judge actually asks about, in plain English. */
const HEADLINE_COUNTS: { key: string; label: string; hint: string }[] = [
  { key: "institutions", label: "Institutions", hint: "AICTE-approved colleges in the dataset" },
  { key: "students", label: "Students", hint: "Student records, all synthetic" },
  { key: "enrolments", label: "Enrolments", hint: "Student-level enrolment rows" },
  { key: "flags", label: "Flags", hint: "Findings raised by the detectors" },
];

/**
 * One demo control: a button with a sentence saying exactly what pressing it does.
 */
function ControlAction({
  title,
  description,
  button,
}: {
  title: string;
  description: string;
  button: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3 py-4 first:pt-0 last:pb-0">
      <div className="min-w-0 flex-1 space-y-1">
        <p className="text-sm font-medium">{title}</p>
        <p className="text-sm leading-relaxed text-muted-foreground">{description}</p>
      </div>
      <div className="shrink-0">{button}</div>
    </div>
  );
}

export default function AdminPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
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

  const detectors = useMutation({
    mutationFn: api.runDetectors,
    onSuccess: () => {
      toast("Detectors re-run. Flags are updated in place, never duplicated.", "success");
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

  if (status.isError) return <ErrorState error={status.error} onRetry={status.refetch} />;

  const counts = status.data?.counts ?? {};

  return (
    <>
      <PageHeader
        title="Demo controls"
        description="Reset the dataset, re-run the detectors, or inject one fraud scenario live during a demo."
        actions={
          <Button variant="outline" onClick={() => status.refetch()} disabled={status.isFetching}>
            <RefreshCw className="h-4 w-4" />
            Refresh
          </Button>
        }
      />

      {status.isLoading || !status.data ? (
        <>
          <KpiSkeleton />
          <Skeleton rows={3} height="h-32" />
        </>
      ) : (
        <>
          <KpiRow>
            {HEADLINE_COUNTS.map((item) => (
              <KpiCard
                key={item.key}
                label={item.label}
                value={counts[item.key] ?? 0}
                hint={item.hint}
                icon={<Rows3 className="h-4 w-4" />}
              />
            ))}
          </KpiRow>

          <SectionCard
            title="Dataset"
            description={`Current academic year: ${status.data.current_academic_year}.`}
          >
            <div className="divide-y divide-border">
              <ControlAction
                title="Reset and reseed the demo data"
                description="Wipes every table and regenerates 40 institutions and roughly 15,000 students from seed 42, then runs every detector. Takes about 15 seconds, and anything you injected during the demo is lost."
                button={
                  <Button onClick={() => reseed.mutate()} disabled={reseed.isPending}>
                    {reseed.isPending ? <Spinner /> : <Database className="h-4 w-4" />}
                    Reset &amp; reseed
                  </Button>
                }
              />
              <ControlAction
                title="Re-run the detectors"
                description="Re-scores every institution and refreshes the findings against the data that is already there. Existing flags are updated in place, never duplicated, so it is safe to press twice."
                button={
                  <Button
                    variant="outline"
                    onClick={() => detectors.mutate()}
                    disabled={detectors.isPending}
                  >
                    {detectors.isPending ? <Spinner /> : <RefreshCw className="h-4 w-4" />}
                    Re-run detectors
                  </Button>
                }
              />
              <ControlAction
                title="Check the audit chain"
                description="Verifies the hash chain over the audit log and runs a tamper test that edits a row in a copy, to show the break being caught."
                button={
                  <Button asChild variant="outline">
                    <Link href="/admin/audit">
                      <ShieldCheck className="h-4 w-4" />
                      Open audit log
                    </Link>
                  </Button>
                }
              />
            </div>
          </SectionCard>

          <SectionCard
            title="Inject a scenario live"
            description="Each one adds its students to the current database and re-runs the detectors, so a finding appears while you are presenting."
          >
            {scenarios.isLoading ? (
              <Skeleton rows={3} />
            ) : (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {(scenarios.data?.scenarios ?? []).map((scenario) => (
                  <button
                    key={scenario.name}
                    type="button"
                    onClick={() => loadScenario.mutate(scenario.name)}
                    disabled={loadScenario.isPending}
                    className="flex h-full flex-col gap-2 rounded-md border border-border bg-card p-4 text-left transition-colors hover:border-primary hover:bg-primary/[0.03] disabled:opacity-60"
                  >
                    <span className="flex items-start justify-between gap-2">
                      <span className="text-sm font-medium leading-snug">{scenario.label}</span>
                      {busyScenario === scenario.name ? (
                        <Spinner className="mt-0.5 shrink-0" />
                      ) : (
                        <PlayCircle className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                      )}
                    </span>
                    <span className="text-xs leading-relaxed text-muted-foreground">
                      Raises {scenario.flag_types.map(flagLabel).join(", ")}.
                    </span>
                  </button>
                ))}
              </div>
            )}
          </SectionCard>

          <SectionCard
            title="Flags currently in the database"
            description="What the detectors have found across every institution."
          >
            <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {Object.entries(status.data.flags_by_type).map(([type, total]) => (
                <li
                  key={type}
                  className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2 text-sm"
                >
                  <span className="min-w-0 leading-snug">{flagLabel(type)}</span>
                  <span className="shrink-0 font-semibold tabular-nums">{total}</span>
                </li>
              ))}
            </ul>
          </SectionCard>
        </>
      )}
    </>
  );
}
