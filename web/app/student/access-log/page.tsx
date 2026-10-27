"use client";

import { useQuery } from "@tanstack/react-query";
import { Eye, FileSearch, Network, ShieldCheck, UserCheck } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/ui/page";
import { EmptyState, ErrorState, Skeleton } from "@/components/States";
import { Button } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";

const ACTION_ICONS: Record<string, React.ReactNode> = {
  reveal_student_details: <Eye className="h-4 w-4" />,
  view_flag_detail: <FileSearch className="h-4 w-4" />,
  view_cluster: <Network className="h-4 w-4" />,
  verification_requested: <UserCheck className="h-4 w-4" />,
  verification_result_read: <ShieldCheck className="h-4 w-4" />,
};

const ACTION_LABELS: Record<string, string> = {
  reveal_student_details: "Opened your full details",
  view_flag_detail: "Opened a case file about you",
  view_cluster: "Viewed a cluster you appear in",
  verification_requested: "Asked you for consent to verify",
  verification_result_read: "Read your verification result",
};

export default function AccessLogPage() {
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["student-access-log", page],
    queryFn: () => api.studentAccessLog({ page, page_size: 25 }),
  });

  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;

  return (
    <>
      <PageHeader
        title="Who accessed my data"
        description="Every time someone opened your details, with the reason they gave. This log is written by the platform, not by them."
      />

      {query.isLoading ? (
        <Skeleton rows={4} height="h-20" />
      ) : (query.data?.items.length ?? 0) === 0 ? (
        <EmptyState
          title="Nobody has opened your details"
          description="If an AICTE officer reveals your record or an employer asks to verify you, it will appear here."
          icon={<ShieldCheck className="h-6 w-6" />}
        />
      ) : (
        <>
          <ol className="relative space-y-4 border-l border-border pl-7 sm:pl-8">
            {query.data!.items.map((row) => (
              <li key={row.id} className="relative">
                <span className="absolute -left-[2.3rem] flex h-7 w-7 items-center justify-center rounded-full border border-border bg-card text-muted-foreground sm:-left-[2.55rem]">
                  {ACTION_ICONS[row.action] ?? <Eye className="h-3.5 w-3.5" />}
                </span>
                <div className="rounded-lg border border-border bg-card p-4 shadow-card">
                  <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
                    <div className="min-w-0">
                      <p className="text-sm font-medium leading-snug">
                        {ACTION_LABELS[row.action] ?? row.action.replace(/_/g, " ")}
                      </p>
                      <p className="mt-0.5 text-xs text-muted-foreground">{row.actor_label}</p>
                    </div>
                    <span className="shrink-0 text-xs text-muted-foreground">{dateTime(row.at)}</span>
                  </div>
                  {row.reason && (
                    <div className="mt-3 rounded-md bg-secondary/60 p-3">
                      <p className="type-label">Reason given</p>
                      <p className="mt-1 text-sm leading-relaxed">{row.reason}</p>
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ol>

          {(query.data?.total ?? 0) > 25 && (
            <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
              <span>
                {query.data!.total} entries · page {page} of {query.data!.total_pages}
              </span>
              <span className="flex gap-2">
                <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                  Previous
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={page >= (query.data?.total_pages ?? 1)}
                  onClick={() => setPage(page + 1)}
                >
                  Next
                </Button>
              </span>
            </div>
          )}

          <p className="text-xs leading-relaxed text-muted-foreground">
            Officers are shown by role, not by name. An AICTE officer cannot open your details
            without typing a reason, and that reason appears above exactly as they wrote it.
          </p>
        </>
      )}
    </>
  );
}
