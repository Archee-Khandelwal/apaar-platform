"use client";

/** Demo control panel: reseed the dataset and check the audit chain. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, RefreshCw, Rows3, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { ErrorState, KpiSkeleton, Skeleton } from "@/components/States";
import { KpiCard, KpiRow, PageHeader, SectionCard } from "@/components/ui/page";
import { Button, Spinner } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { flagLabel } from "@/lib/format";

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

  const status = useQuery({ queryKey: ["admin-status"], queryFn: api.adminStatus });

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

  if (status.isError) return <ErrorState error={status.error} onRetry={status.refetch} />;

  const counts = status.data?.counts ?? {};

  return (
    <>
      <PageHeader
        title="Demo controls"
        description="Reset the dataset and check the audit chain."
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
                description="Wipes every table and regenerates 40 institutions and roughly 15,000 students from seed 42, then runs every detector. Takes about 15 seconds, and anything uploaded during the demo is lost."
                button={
                  <Button onClick={() => reseed.mutate()} disabled={reseed.isPending}>
                    {reseed.isPending ? <Spinner /> : <Database className="h-4 w-4" />}
                    Reset &amp; reseed
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
