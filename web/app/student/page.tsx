"use client";

/** "Was this you?" first — that card is the whole point of the student portal. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, CheckCircle2, HelpCircle, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { MaskedApaar } from "@/components/Masked";
import { StatusBadge } from "@/components/SeverityBadge";
import { ErrorState, Skeleton } from "@/components/States";
import { PageHeader, SectionCard } from "@/components/ui/page";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge, Button, Label, Select, Spinner, Textarea } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { dateOnly, dateTime, flagLabel } from "@/lib/format";
import type { StudentMe } from "@/lib/types";

const DISPUTE_CATEGORIES = [
  { value: "not_my_enrolment", label: "I never enrolled at this institution" },
  { value: "wrong_program", label: "The programme is wrong" },
  { value: "wrong_year", label: "The year is wrong" },
  { value: "already_cancelled", label: "I cancelled this admission" },
  { value: "other", label: "Something else" },
];

const ACCESS_LABELS: Record<string, string> = {
  reveal_student_details: "Opened your full details",
  view_flag_detail: "Opened a case file about you",
  view_cluster: "Viewed a cluster you appear in",
  verification_requested: "Asked you for consent to verify",
  verification_result_read: "Read your verification result",
};

type Enrolment = StudentMe["enrolments"][number];

export default function StudentHomePage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [disputing, setDisputing] = useState<Enrolment | null>(null);
  const [category, setCategory] = useState(DISPUTE_CATEGORIES[0].value);
  const [reason, setReason] = useState("");

  const query = useQuery({ queryKey: ["student-me"], queryFn: api.studentMe });
  const access = useQuery({
    queryKey: ["student-access-log", 1],
    queryFn: () => api.studentAccessLog({ page: 1, page_size: 3 }),
  });

  const confirm = useMutation({
    mutationFn: (id: number) => api.confirmEnrolment(id),
    onSuccess: () => {
      toast("Thank you — this enrolment is confirmed.", "success");
      queryClient.invalidateQueries({ queryKey: ["student-me"] });
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  const dispute = useMutation({
    mutationFn: () => api.disputeEnrolment(disputing!.id, { reason: reason.trim(), category }),
    onSuccess: (result) => {
      toast(result.message, "warning");
      setDisputing(null);
      setReason("");
      queryClient.invalidateQueries({ queryKey: ["student-me"] });
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;
  if (query.isLoading || !query.data) return <Skeleton rows={6} height="h-24" />;

  const { student, enrolments, open_cases, pending_consents } = query.data;
  const unconfirmed = enrolments.filter((row) => row.confirmation === "unconfirmed");

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

      {/* ------------------------------------------------- "Was this you?" */}
      {unconfirmed.map((enrolment) => (
        <div
          key={enrolment.id}
          className="rounded-lg border-2 border-primary/30 bg-primary/[0.04] p-5 shadow-card"
        >
          <p className="flex items-center gap-2 text-base font-semibold">
            <HelpCircle className="h-5 w-5 shrink-0 text-primary" />
            Was this you?
          </p>
          <p className="mt-3 text-sm leading-relaxed">
            You have been reported as enrolled in <strong>{enrolment.program}</strong> at{" "}
            <strong>{enrolment.institution_name}</strong> for {enrolment.academic_year}
            {enrolment.admitted_on ? `, admitted ${dateOnly(enrolment.admitted_on)}` : ""}.
          </p>
          <div className="mt-4 flex flex-col gap-2 sm:flex-row">
            <Button
              className="sm:w-auto"
              disabled={confirm.isPending}
              onClick={() => confirm.mutate(enrolment.id)}
            >
              {confirm.isPending ? <Spinner /> : <CheckCircle2 className="h-4 w-4" />}
              Yes, that is correct
            </Button>
            <Button
              variant="outline"
              className="sm:w-auto"
              onClick={() => {
                setDisputing(enrolment);
                setReason("");
              }}
            >
              <AlertTriangle className="h-4 w-4" />
              No — dispute this
            </Button>
          </div>
          <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
            Disputing tells AICTE and the institution straight away. Nothing about your record
            changes until AICTE looks at it.
          </p>
        </div>
      ))}

      {open_cases.length > 0 && (
        <SectionCard title="Your open cases" className="border-red-200">
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
            AICTE has been notified and can see each case in their queue.
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
                <Badge
                  tone={
                    enrolment.confirmation === "confirmed"
                      ? "success"
                      : enrolment.confirmation === "disputed"
                        ? "danger"
                        : "warning"
                  }
                >
                  {enrolment.confirmation}
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

      <Dialog open={Boolean(disputing)} onOpenChange={(open) => !open && setDisputing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Dispute this enrolment</DialogTitle>
            <DialogDescription>
              {disputing && (
                <>
                  {disputing.program} at {disputing.institution_name}, {disputing.academic_year}.
                </>
              )}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="category">What is wrong?</Label>
              <Select id="category" value={category} onChange={(event) => setCategory(event.target.value)}>
                {DISPUTE_CATEGORIES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="reason">Tell AICTE what happened (at least 10 characters)</Label>
              <Textarea
                id="reason"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="e.g. I never applied to or joined this institution."
              />
            </div>
            <p className="text-xs leading-relaxed text-muted-foreground">
              This raises a critical case with AICTE and the institution. Your enrolment record is
              not altered until AICTE resolves it.
            </p>
          </div>

          <DialogFooter>
            <Button variant="ghost" onClick={() => setDisputing(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={reason.trim().length < 10 || dispute.isPending}
              onClick={() => dispute.mutate()}
            >
              {dispute.isPending && <Spinner />}
              Submit dispute
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
