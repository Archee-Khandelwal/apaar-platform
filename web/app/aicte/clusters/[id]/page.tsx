"use client";

/** The headline investigation screen: one cluster's graph, side by side with a normal family. */
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Info, Users } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { PageHeader } from "@/components/AppShell";
import { MaskedApaar } from "@/components/Masked";
import { RevealButton } from "@/components/RevealButton";
import { SeverityBadge } from "@/components/SeverityBadge";
import { ErrorState, LoadingSkeleton } from "@/components/States";
import { Button, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import type { GraphNode } from "@/lib/types";

// Cytoscape touches the DOM directly, so it must not render on the server.
const ClusterGraph = dynamic(() => import("@/components/ClusterGraph").then((m) => m.ClusterGraph), {
  ssr: false,
  loading: () => <LoadingSkeleton rows={8} />,
});

export default function ClusterDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const [selected, setSelected] = useState<GraphNode["data"] | null>(null);
  const [compare, setCompare] = useState(false);

  const query = useQuery({
    queryKey: ["cluster", id],
    queryFn: () => api.cluster(id),
    enabled: Number.isFinite(id),
  });
  const normal = useQuery({
    queryKey: ["cluster-normal", id],
    queryFn: () => api.normalCluster(id),
    enabled: compare && Number.isFinite(id),
  });

  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;
  if (query.isLoading || !query.data) return <LoadingSkeleton rows={10} />;

  const cluster = query.data;
  const metrics = cluster.metrics as Record<string, unknown>;
  const reasons = (metrics.reasons as string[] | undefined) ?? [];
  const students = cluster.nodes.filter((node) => node.data.type === "student");
  const contacts = cluster.nodes.filter((node) => node.data.type !== "student");

  return (
    <>
      <Button asChild variant="ghost" size="sm" className="mb-2 px-0">
        <Link href="/aicte/clusters">
          <ArrowLeft className="h-3.5 w-3.5" />
          All clusters
        </Link>
      </Button>

      <PageHeader
        title={`Cluster #${cluster.cluster_id}`}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <SeverityBadge severity={cluster.severity} />
            <span>score {cluster.score.toFixed(0)}/100</span>
          </span>
        }
        actions={
          <Button variant={compare ? "default" : "outline"} onClick={() => setCompare((value) => !value)}>
            {compare ? "Hide" : "Compare with"} a normal cluster
          </Button>
        }
      />

      <div className="rounded-lg border-l-4 border-accent bg-accent/5 p-4">
        <p className="text-sm font-medium leading-relaxed">{cluster.summary}</p>
        {reasons.length > 0 && (
          <ul className="mt-2 space-y-1 text-sm">
            {reasons.map((reason, index) => (
              <li key={index} className="flex gap-2">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
                <span>{reason}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ["Students", students.length],
          ["Shared contacts", contacts.length],
          ["Students per contact", (metrics.students_per_contact as number)?.toFixed?.(1) ?? "—"],
          ["Institutions", (metrics.institutions_involved as number) ?? 1],
        ].map(([label, value]) => (
          <div key={label as string} className="rounded-lg border border-border bg-card p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {label as string}
            </p>
            <p className="mt-1.5 text-2xl font-semibold tabular-nums">{String(value)}</p>
          </div>
        ))}
      </div>

      <div className={`mt-4 grid gap-4 ${compare ? "xl:grid-cols-2" : "lg:grid-cols-3"}`}>
        <Card className={compare ? undefined : "lg:col-span-2"}>
          <CardHeader>
            <CardTitle>Flagged cluster</CardTitle>
          </CardHeader>
          <CardContent>
            <ClusterGraph cluster={cluster} onSelectStudent={setSelected} height={compare ? 380 : 480} />
          </CardContent>
        </Card>

        {compare && (
          <Card>
            <CardHeader>
              <CardTitle>A normal family, for comparison</CardTitle>
            </CardHeader>
            <CardContent>
              {normal.isLoading && <LoadingSkeleton rows={6} />}
              {normal.isError && <ErrorState error={normal.error} />}
              {normal.data && (
                <>
                  <p className="mb-2 text-sm text-muted-foreground">{normal.data.summary}</p>
                  <ClusterGraph cluster={normal.data} height={380} />
                </>
              )}
            </CardContent>
          </Card>
        )}

        {!compare && (
          <Card>
            <CardHeader>
              <CardTitle>{selected ? "Selected student" : "Shared contacts"}</CardTitle>
            </CardHeader>
            <CardContent>
              {selected ? (
                <div className="space-y-3">
                  <dl className="space-y-2 text-sm">
                    <div>
                      <dt className="text-xs uppercase tracking-wide text-muted-foreground">APAAR</dt>
                      <dd>
                        <MaskedApaar value={selected.apaar_masked} />
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs uppercase tracking-wide text-muted-foreground">Name</dt>
                      <dd>{selected.label}</dd>
                    </div>
                    <div>
                      <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                        Institution
                      </dt>
                      <dd>{selected.institution}</dd>
                    </div>
                    <div>
                      <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                        Programme
                      </dt>
                      <dd>
                        {selected.program} · {selected.academic_year}
                      </dd>
                    </div>
                  </dl>
                  {selected.student_id && <RevealButton studentId={selected.student_id} />}
                  <Button variant="ghost" size="sm" onClick={() => setSelected(null)}>
                    Clear selection
                  </Button>
                </div>
              ) : (
                <>
                  <ul className="space-y-2">
                    {contacts.map((contact) => (
                      <li
                        key={contact.data.id}
                        className="flex items-center justify-between gap-2 rounded border border-border px-2.5 py-2 text-sm"
                      >
                        <span className="flex items-center gap-2">
                          <span className="h-3 w-3 rotate-45 bg-sky-500" />
                          {contact.data.label}
                        </span>
                        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                          <Users className="h-3 w-3" />
                          {contact.data.degree} students
                        </span>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-3 text-xs text-muted-foreground">
                    Contacts are numbered, never shown: the platform stores only a keyed hash of a
                    phone number or email, so even an officer cannot read them back.
                  </p>
                  <p className="mt-2 text-xs text-muted-foreground">
                    Click any student in the graph for their masked detail.
                  </p>
                </>
              )}
            </CardContent>
          </Card>
        )}
      </div>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>Students in this cluster ({students.length})</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="py-1.5 text-left font-semibold">APAAR</th>
                  <th className="py-1.5 text-left font-semibold">Name</th>
                  <th className="py-1.5 text-left font-semibold">Institution</th>
                  <th className="py-1.5 text-left font-semibold">Programme</th>
                  <th className="py-1.5 text-right font-semibold" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {students.map((student) => (
                  <tr key={student.data.id}>
                    <td className="py-1.5">
                      <MaskedApaar value={student.data.apaar_masked} />
                    </td>
                    <td className="py-1.5">{student.data.label}</td>
                    <td className="py-1.5">{student.data.institution}</td>
                    <td className="py-1.5 text-xs">
                      {student.data.program} · {student.data.academic_year}
                    </td>
                    <td className="py-1.5 text-right">
                      {student.data.student_id && (
                        <RevealButton studentId={student.data.student_id} label="Reveal" />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            Opening this cluster was written to the access log, and so is every reveal.
          </p>
        </CardContent>
      </Card>
    </>
  );
}
