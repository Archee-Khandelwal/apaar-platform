"use client";

import { useQuery } from "@tanstack/react-query";
import { Network, Users } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/AppShell";
import { SeverityBadge } from "@/components/SeverityBadge";
import { EmptyState, ErrorState, LoadingSkeleton } from "@/components/States";
import { Button, Card, CardContent, Select } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { count } from "@/lib/format";
import { cn } from "@/lib/utils";

export default function ClustersPage() {
  const [kind, setKind] = useState<"suspicious" | "normal">("suspicious");
  const query = useQuery({
    queryKey: ["clusters", kind],
    queryFn: () => api.clusters({ kind, page_size: 50 }),
  });

  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;

  return (
    <>
      <PageHeader
        title="Ghost-student clusters"
        description="Students linked through shared contact details. A family shares one guardian number across one to three students; a fabricated cohort shares two or three numbers across dozens."
        actions={
          <Select
            value={kind}
            onChange={(event) => setKind(event.target.value as "suspicious" | "normal")}
            className="w-56"
          >
            <option value="suspicious">Flagged clusters</option>
            <option value="normal">Healthy family clusters</option>
          </Select>
        }
      />

      {query.isLoading ? (
        <LoadingSkeleton rows={4} />
      ) : (query.data?.items.length ?? 0) === 0 ? (
        <EmptyState
          title={kind === "suspicious" ? "No clusters flagged" : "No healthy clusters stored"}
          description="Clusters are rebuilt whenever the detectors run."
          icon={<Network className="h-6 w-6" />}
        />
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {query.data!.items.map((cluster) => {
            const contacts = Object.entries(cluster.shared_attributes);
            return (
              <Card
                key={cluster.cluster_id}
                className={cn(
                  "transition-shadow hover:shadow-md",
                  cluster.severity === "critical" && "border-red-300",
                  cluster.severity === "high" && "border-orange-300",
                )}
              >
                <CardContent className="pt-5">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">
                        Cluster #{cluster.cluster_id}
                      </p>
                      <p className="mt-1 flex items-baseline gap-1.5">
                        <span className="text-3xl font-semibold tabular-nums">
                          {cluster.score.toFixed(0)}
                        </span>
                        <span className="text-xs text-muted-foreground">/100 score</span>
                      </p>
                    </div>
                    <SeverityBadge severity={cluster.severity} />
                  </div>

                  <p className="mt-3 text-sm leading-relaxed">{cluster.summary}</p>

                  <dl className="mt-4 grid grid-cols-2 gap-2 text-sm">
                    <div>
                      <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                        Students
                      </dt>
                      <dd className="flex items-center gap-1.5 font-semibold tabular-nums">
                        <Users className="h-3.5 w-3.5 text-muted-foreground" />
                        {count(cluster.student_count)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                        Shared contacts
                      </dt>
                      <dd className="font-semibold tabular-nums">
                        {contacts.map(([key, value]) => (
                          <span key={key} className="mr-2 whitespace-nowrap text-xs font-normal">
                            {count(value)} {key.replace(/_/g, " ")}
                          </span>
                        ))}
                      </dd>
                    </div>
                  </dl>

                  <div className="mt-3">
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">
                      Institutions involved
                    </p>
                    <ul className="mt-1 space-y-0.5 text-sm">
                      {cluster.institutions.map((institution) => (
                        <li key={institution.id} className="truncate">
                          <Link
                            href={`/aicte/institutions/${institution.id}`}
                            className="hover:underline"
                          >
                            {institution.name}
                          </Link>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <Button asChild size="sm" className="mt-4 w-full">
                    <Link href={`/aicte/clusters/${cluster.cluster_id}`}>
                      <Network className="h-3.5 w-3.5" />
                      Investigate the graph
                    </Link>
                  </Button>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </>
  );
}
