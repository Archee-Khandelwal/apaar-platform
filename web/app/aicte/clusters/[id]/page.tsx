"use client";

/** The headline investigation screen: one cluster's graph, full width, with a side panel. */
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Users } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { MaskedApaar } from "@/components/Masked";
import { RevealButton } from "@/components/RevealButton";
import { ErrorState, Skeleton } from "@/components/States";
import {
  ExplanationNote,
  FieldList,
  KpiCard,
  KpiRow,
  PageHeader,
  SectionCard,
} from "@/components/ui/page";
import { Button } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import type { GraphNode } from "@/lib/types";

// Cytoscape touches the DOM directly, so it must not render on the server.
const ClusterGraph = dynamic(() => import("@/components/ClusterGraph").then((m) => m.ClusterGraph), {
  ssr: false,
  loading: () => <Skeleton rows={6} height="h-16" />,
});
const ClusterLegend = dynamic(
  () => import("@/components/ClusterGraph").then((m) => m.ClusterLegend),
  { ssr: false },
);

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
  if (query.isLoading || !query.data) return <Skeleton rows={6} height="h-28" />;

  const cluster = query.data;
  const metrics = cluster.metrics as Record<string, unknown>;
  const reasons = (metrics.reasons as string[] | undefined) ?? [];
  const students = cluster.nodes.filter((node) => node.data.type === "student");
  const contacts = cluster.nodes.filter((node) => node.data.type !== "student");
  // Students in a ghost cluster usually share one institution; naming it once is enough.
  const institutions = Array.from(
    new Set(students.map((node) => node.data.institution ?? "—")),
  );

  return (
    <>
      <div>
        <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2">
          <Link href="/aicte/clusters">
            <ArrowLeft className="h-3.5 w-3.5" />
            All clusters
          </Link>
        </Button>
        <PageHeader
          title={`Cluster #${cluster.cluster_id}`}
          description="Whether these students are one family sharing a contact, or a fabricated cohort."
          actions={
            <Button variant={compare ? "default" : "outline"} onClick={() => setCompare((value) => !value)}>
              {compare ? "Hide" : "Compare with"} a normal cluster
            </Button>
          }
        />
      </div>

      <ExplanationNote title="What the detector saw">
        <p>{cluster.summary}</p>
        {reasons.length > 0 && (
          <ul className="mt-2 space-y-1">
            {reasons.map((reason, index) => (
              <li key={index}>• {reason}</li>
            ))}
          </ul>
        )}
      </ExplanationNote>

      <KpiRow className="xl:grid-cols-5">
        <KpiCard
          label="Severity"
          value={cluster.severity}
          hint={`Score ${cluster.score.toFixed(0)} of 100`}
          tone={cluster.severity === "critical" || cluster.severity === "high" ? "critical" : "warning"}
        />
        <KpiCard label="Students" value={students.length} hint="All linked into one component" />
        <KpiCard label="Shared contacts" value={contacts.length} hint="Phone numbers or emails, hashed" />
        <KpiCard
          label="Students per contact"
          value={(metrics.students_per_contact as number)?.toFixed?.(1) ?? "—"}
          hint="A family normally has one contact for up to three students"
        />
        <KpiCard
          label="Institutions"
          value={(metrics.institutions_involved as number) ?? institutions.length}
          hint={institutions.length === 1 ? institutions[0] : "Across several institutions"}
        />
      </KpiRow>

      {/* The graph gets the full content width; detail sits beside it. */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <SectionCard
          title={compare ? "Flagged cluster" : "The link graph"}
          description="Each line is a contact detail shared between a student and a hashed phone number or email."
          bodyClassName="space-y-4 p-5"
        >
          <ClusterGraph cluster={cluster} onSelectStudent={setSelected} height={compare ? 420 : 520} />
          <ClusterLegend cluster={cluster} />
        </SectionCard>

        <div className="min-w-0 space-y-6">
          {selected ? (
            <SectionCard title="Selected student">
              <FieldList
                columns={1}
                fields={[
                  { label: "APAAR", value: <MaskedApaar value={selected.apaar_masked} /> },
                  { label: "Name", value: selected.label },
                  { label: "Institution", value: selected.institution },
                  { label: "Programme", value: `${selected.program} · ${selected.academic_year}` },
                ]}
              />
              <div className="mt-5 flex flex-wrap gap-2">
                {selected.student_id && <RevealButton studentId={selected.student_id} />}
                <Button variant="ghost" size="sm" onClick={() => setSelected(null)}>
                  Clear selection
                </Button>
              </div>
            </SectionCard>
          ) : (
            <SectionCard
              title="Shared contacts"
              description="How many students each shared contact detail reaches."
              bodyClassName="p-0"
            >
              <ul className="divide-y divide-border">
                {contacts.map((contact) => (
                  <li
                    key={contact.data.id}
                    className="flex items-center justify-between gap-3 px-5 py-3 text-sm"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="h-3 w-3 shrink-0 rotate-45 bg-sky-600" aria-hidden />
                      <span className="min-w-0 leading-snug">{contact.data.label}</span>
                    </span>
                    <span className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap text-xs text-muted-foreground">
                      <Users className="h-3 w-3" />
                      {contact.data.degree} students
                    </span>
                  </li>
                ))}
              </ul>
              <p className="px-5 py-3 text-xs leading-relaxed text-muted-foreground">
                Contacts are numbered, never shown: the platform stores only a keyed hash of a phone
                number or email, so even an officer cannot read them back.
              </p>
            </SectionCard>
          )}

          {compare && (
            <SectionCard title="A normal family, for comparison">
              {normal.isLoading && <Skeleton rows={4} />}
              {normal.isError && <ErrorState error={normal.error} />}
              {normal.data && (
                <>
                  <p className="mb-3 text-sm leading-relaxed text-muted-foreground">
                    {normal.data.summary}
                  </p>
                  <ClusterGraph cluster={normal.data} height={280} />
                </>
              )}
            </SectionCard>
          )}
        </div>
      </div>

      <SectionCard
        title={`Students in this cluster (${students.length})`}
        description={
          institutions.length === 1
            ? `All at ${institutions[0]}.`
            : `Across ${institutions.length} institutions.`
        }
        footer={
          <p className="text-xs text-muted-foreground">
            Opening this cluster was written to the access log, and so is every reveal.
          </p>
        }
        bodyClassName="p-0"
      >
        <div className="max-h-[30rem] overflow-auto">
          <table className="w-full table-fixed text-sm">
            <thead className="sticky top-0 z-10 bg-secondary/90 backdrop-blur">
              <tr>
                <th className="w-[20%] border-b border-border px-5 py-3 text-left type-label">APAAR</th>
                <th className="w-[20%] border-b border-border px-4 py-3 text-left type-label">Name</th>
                {institutions.length > 1 && (
                  <th className="w-[28%] border-b border-border px-4 py-3 text-left type-label">
                    Institution
                  </th>
                )}
                <th className="border-b border-border px-4 py-3 text-left type-label">Programme</th>
                <th className="w-[14%] border-b border-border px-5 py-3 text-right type-label" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {students.map((student) => (
                <tr key={student.data.id}>
                  <td className="px-5 py-2.5">
                    <MaskedApaar value={student.data.apaar_masked} />
                  </td>
                  <td className="px-4 py-2.5">{student.data.label}</td>
                  {institutions.length > 1 && (
                    <td className="px-4 py-2.5 leading-snug">{student.data.institution}</td>
                  )}
                  <td className="px-4 py-2.5 text-xs leading-snug text-muted-foreground">
                    {student.data.program} · {student.data.academic_year}
                  </td>
                  <td className="px-5 py-2.5 text-right">
                    {student.data.student_id && (
                      <RevealButton studentId={student.data.student_id} label="Reveal" />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>
    </>
  );
}
