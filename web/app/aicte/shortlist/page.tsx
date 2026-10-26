"use client";

import { useQuery } from "@tanstack/react-query";
import { ClipboardCheck, Download } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/AppShell";
import { SeverityBadge } from "@/components/SeverityBadge";
import { EmptyState, ErrorState, LoadingSkeleton } from "@/components/States";
import { Button, Card, CardContent, Select } from "@/components/ui/primitives";
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
        title="Recommended for physical inspection"
        description={
          query.data
            ? `Top ${query.data.items.length} by risk for ${query.data.academic_year}, generated ${dateTime(query.data.generated_at)}`
            : "Ranked by risk, with what to check on site."
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
        <LoadingSkeleton rows={5} />
      ) : (query.data?.items.length ?? 0) === 0 ? (
        <EmptyState title="Nothing to inspect" description="No institution carries enough risk to shortlist." />
      ) : (
        <div className="space-y-3">
          {query.data!.items.map((row) => (
            <Card key={row.institution_id}>
              <CardContent className="pt-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="flex items-start gap-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-bold text-primary-foreground">
                      {row.rank}
                    </span>
                    <div>
                      <Link
                        href={`/aicte/institutions/${row.institution_id}`}
                        className="font-semibold hover:underline"
                      >
                        {row.name}
                      </Link>
                      <p className="text-xs text-muted-foreground">{row.state}</p>
                    </div>
                  </div>
                  <span className="inline-flex items-center gap-2">
                    <span className="text-lg font-semibold tabular-nums">{row.risk_score.toFixed(1)}</span>
                    <SeverityBadge severity={row.band} />
                  </span>
                </div>

                <div className="mt-4 grid gap-4 md:grid-cols-2">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Why it is on the list
                    </p>
                    <ol className="mt-1.5 space-y-1 text-sm">
                      {row.reasons.map((reason, index) => (
                        <li key={index} className="flex gap-2">
                          <span className="text-muted-foreground">{index + 1}.</span>
                          <span>{reason}</span>
                        </li>
                      ))}
                    </ol>
                  </div>
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      What to check on site
                    </p>
                    <ul className="mt-1.5 space-y-1 text-sm">
                      {row.suggested_checks.map((check) => (
                        <li key={check} className="flex gap-2">
                          <ClipboardCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
                          <span>{check}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
