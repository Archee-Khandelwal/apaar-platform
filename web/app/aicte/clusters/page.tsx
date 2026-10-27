"use client";

import { useQuery } from "@tanstack/react-query";
import { Network, Users } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageHeader, SectionCard } from "@/components/ui/page";
import { SeverityBadge } from "@/components/SeverityBadge";
import { EmptyState, ErrorState, Skeleton } from "@/components/States";
import { Button, Select } from "@/components/ui/primitives";
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
        title="Ghost clusters"
        description="Which groups of students are linked by shared contact details — a family shares one guardian number across one to three students, a fabricated cohort shares two or three across dozens."
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
        <Skeleton rows={4} height="h-40" />
      ) : (query.data?.items.length ?? 0) === 0 ? (
        <EmptyState
          title={kind === "suspicious" ? "No clusters flagged" : "No healthy clusters stored"}
          description="Clusters are rebuilt whenever the detectors run."
          icon={<Network className="h-6 w-6" />}
        />
      ) : (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-3">
          {query.data!.items.map((cluster) => {
            const contacts = Object.entries(cluster.shared_attributes);
            return (
              <SectionCard
                key={cluster.cluster_id}
                className={cn(
                  "flex flex-col transition-shadow hover:shadow-raised",
                  cluster.severity === "critical" && "border-red-200",
                  cluster.severity === "high" && "border-orange-200",
                )}
                title={`Cluster #${cluster.cluster_id}`}
                actions={<SeverityBadge severity={cluster.severity} />}
                bodyClassName="flex flex-1 flex-col gap-4 p-5"
                footer={
                  <Button asChild size="sm" className="w-full">
                    <Link href={`/aicte/clusters/${cluster.cluster_id}`}>
                      <Network className="h-3.5 w-3.5" />
                      Investigate the graph
                    </Link>
                  </Button>
                }
              >
                <p className="text-sm leading-relaxed">{cluster.summary}</p>

                <dl className="grid grid-cols-2 gap-4">
                  <div className="min-w-0">
                    <dt className="type-label">Students</dt>
                    <dd className="mt-1 flex items-center gap-1.5 text-lg font-semibold tabular-nums">
                      <Users className="h-4 w-4 text-muted-foreground" />
                      {count(cluster.student_count)}
                    </dd>
                  </div>
                  <div className="min-w-0">
                    <dt className="type-label">Score</dt>
                    <dd className="mt-1 text-lg font-semibold tabular-nums">
                      {cluster.score.toFixed(0)}
                      <span className="ml-1 text-xs font-normal text-muted-foreground">of 100</span>
                    </dd>
                  </div>
                </dl>

                <div className="min-w-0">
                  <p className="type-label">Shared contacts</p>
                  <ul className="mt-1 space-y-0.5 text-sm">
                    {contacts.map(([key, value]) => (
                      <li key={key}>
                        {count(value)} {key.replace(/_/g, " ")}
                      </li>
                    ))}
                  </ul>
                </div>

                <div className="mt-auto min-w-0">
                  <p className="type-label">Institutions involved</p>
                  <ul className="mt-1 space-y-1 text-sm">
                    {cluster.institutions.map((institution) => (
                      <li key={institution.id} className="leading-snug">
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
              </SectionCard>
            );
          })}
        </div>
      )}
    </>
  );
}
