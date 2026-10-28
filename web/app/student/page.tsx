"use client";

/** What institutions reported about the student, who accessed it, and pending consents. */
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { MaskedApaar } from "@/components/Masked";
import { StatusBadge } from "@/components/SeverityBadge";
import { ErrorState, Skeleton } from "@/components/States";
import { PageHeader, SectionCard } from "@/components/ui/page";
import { Badge, Button } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateOnly, dateTime, flagLabel } from "@/lib/format";

const ACCESS_LABELS: Record<string, string> = {
  reveal_student_details: "Opened your full details",
  view_flag_detail: "Opened a case file about you",
  verification_requested: "Asked you for consent to verify",
  verification_result_read: "Read your verification result",
};

export default function StudentHomePage() {
  const query = useQuery({ queryKey: ["student-me"], queryFn: api.studentMe });
  const access = useQuery({
    queryKey: ["student-access-log", 1],
    queryFn: () => api.studentAccessLog({ page: 1, page_size: 3 }),
  });

  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;
  if (query.isLoading || !query.data) return <Skeleton rows={6} height="h-24" />;

  const { student, enrolments, open_cases, pending_consents } = query.data;

  return (
    <>
      <PageHeader
        title={student.name ?? "My APAAR record"}
        description={
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <MaskedApaar value={student.apaar_masked} />
            <span aria-hidden>·</span>
            <span>born {dateOnly(student.dob)}</span>
            {student.is_minor && <Badge tone="warning">under 18</Badge>}
            {student.apaar_status === "not_applicable" && (
              <Badge tone="neutral">APAAR not applicable</Badge>
            )}
          </span>
        }
      />

      {open_cases.length > 0 && (
        <SectionCard title="Your correction requests">
          <ul className="space-y-2">
            {open_cases.map((item) => (
              <li key={item.flag_id} className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-medium">{flagLabel(item.type)}</span>
                <StatusBadge status={item.status} />
                <span className="text-xs text-muted-foreground">raised {dateTime(item.created_at)}</span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
            Each request goes to the institution that reported the record; AICTE can see it too.
          </p>
        </SectionCard>
      )}

      <SectionCard
        title="What institutions have reported about you"
        actions={
          <Button asChild size="sm" variant="outline">
            <Link href="/student/records">My records</Link>
          </Button>
        }
        bodyClassName="p-0"
      >
        {enrolments.length === 0 ? (
          <p className="p-5 text-sm text-muted-foreground">
            No institution has reported an enrolment for you yet.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {enrolments.map((enrolment) => (
              <li key={enrolment.id} className="flex flex-wrap items-start justify-between gap-3 p-5">
                <div className="min-w-0 flex-1 space-y-1">
                  <p className="text-sm font-medium">{enrolment.institution_name}</p>
                  <p className="text-sm text-muted-foreground">
                    {enrolment.program} · {enrolment.mode === "online" ? "online / ODL" : "regular"}
                  </p>
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    {enrolment.academic_year} · year {enrolment.year_of_study} ·{" "}
                    {enrolment.admission_type} · {enrolment.status}
                  </p>
                </div>
                <Badge tone={enrolment.status === "admitted" || enrolment.status === "completed" ? "success" : "neutral"}>
                  {enrolment.status}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <SectionCard
          title="Recent access to your data"
          description="Every time someone opens your details it is logged, with their reason."
          bodyClassName="p-0"
          footer={
            <Button asChild size="sm" variant="outline" className="w-full">
              <Link href="/student/access-log">
                Who accessed my data
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </Button>
          }
        >
          {access.isLoading ? (
            <div className="p-5">
              <Skeleton rows={2} />
            </div>
          ) : (access.data?.items.length ?? 0) === 0 ? (
            <p className="flex items-start gap-2 p-5 text-sm text-muted-foreground">
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
              Nobody has opened your details.
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {access.data!.items.map((row) => (
                <li key={row.id} className="space-y-1 p-4">
                  <p className="text-sm font-medium">
                    {ACCESS_LABELS[row.action] ?? row.action.replace(/_/g, " ")}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {row.actor_label} · {dateTime(row.at)}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </SectionCard>

        <SectionCard
          title="Consent requests"
          description="Nobody can verify you without your consent, and you can withdraw it any time."
          footer={
            <Button asChild size="sm" variant={pending_consents > 0 ? "default" : "outline"} className="w-full">
              <Link href="/student/consents">
                {pending_consents > 0 ? "Answer them now" : "Open the consent manager"}
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </Button>
          }
        >
          <p className="text-4xl font-semibold tabular-nums">{pending_consents}</p>
          <p className="mt-1.5 text-sm text-muted-foreground">
            {pending_consents === 0
              ? "Nobody is waiting on your consent."
              : `waiting for your answer`}
          </p>
          <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
            A verifier only ever learns whether you are enrolled, your programme and the year —
            never your name, date of birth or contact details.
          </p>
        </SectionCard>
      </div>

    </>
  );
}
