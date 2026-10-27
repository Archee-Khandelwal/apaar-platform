"use client";

import { useQuery } from "@tanstack/react-query";
import { ClipboardCheck, Download } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageHeader, SectionCard } from "@/components/ui/page";
import { SeverityBadge } from "@/components/SeverityBadge";
import { EmptyState, ErrorState, Skeleton } from "@/components/States";
import { Button, Select } from "@/components/ui/primitives";
import { api, download } from "@/lib/api";
import { dateTime } from "@/lib/format";

export default function ShortlistPage() {
  const [limit, setLimit] = useState(10);
  const query = useQuery({
    queryKey: ["aicte-shortlist", limit],
    queryFn: () => api.shortlist(limit),
  });

  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;

  return (
    <>
      <PageHeader
        title="Inspection shortlist"
        description={
          query.data
            ? `Which institutions to visit first for ${query.data.academic_year}, and what to check when you get there. Generated ${dateTime(query.data.generated_at)}.`
            : "Which institutions to visit first, and what to check when you get there."
        }
        actions={
          <div className="flex items-center gap-2">
            <Select
              value={String(limit)}
              onChange={(event) => setLimit(Number(event.target.value))}
              className="w-28"
            >
              {[5, 10, 20, 50].map((option) => (
                <option key={option} value={option}>
                  Top {option}
                </option>
              ))}
            </Select>
            <Button
              variant="outline"
              onClick={() =>
                download("/aicte/inspection-shortlist.csv", "inspection_shortlist.csv", { limit })
              }
            >
              <Download className="h-4 w-4" />
              Export CSV
            </Button>
          </div>
        }
      />

      {query.isLoading ? (
        <Skeleton rows={4} height="h-40" />
      ) : (query.data?.items.length ?? 0) === 0 ? (
        <EmptyState title="Nothing to inspect" description="No institution carries enough risk to shortlist." />
      ) : (
        <div className="space-y-6">
          {query.data!.items.map((row) => (
            <SectionCard
              key={row.institution_id}
              title={
                <span className="flex items-start gap-3">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-bold text-primary-foreground">
                    {row.rank}
                  </span>
                  <Link
                    href={`/aicte/institutions/${row.institution_id}`}
                    className="min-w-0 leading-snug hover:underline"
                  >
                    {row.name}
                  </Link>
                </span>
              }
              description={row.state}
              actions={
                <span className="inline-flex items-center gap-2">
                  <span className="text-lg font-semibold tabular-nums">{row.risk_score.toFixed(1)}</span>
                  <SeverityBadge severity={row.band} />
                </span>
              }
            >
              <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
                <div>
                  <p className="type-label">Why it is on the list</p>
                  <ol className="mt-2 space-y-2">
                    {row.reasons.map((reason, index) => (
                      <li key={index} className="flex gap-2 text-sm leading-relaxed">
                        <span className="text-muted-foreground">{index + 1}.</span>
                        <span>{reason}</span>
                      </li>
                    ))}
                  </ol>
                </div>
                <div>
                  <p className="type-label">What to check on site</p>
                  <ul className="mt-2 space-y-2">
                    {row.suggested_checks.map((check) => (
                      <li key={check} className="flex gap-2 text-sm leading-relaxed">
                        <ClipboardCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                        <span>{check}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </SectionCard>
          ))}
        </div>
      )}
    </>
  );
}
