"use client";

/** "Was this you?" first — that card is the whole point of the student portal. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, HelpCircle, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/AppShell";
import { MaskedApaar } from "@/components/Masked";
import { StatusBadge } from "@/components/SeverityBadge";
import { ErrorState, LoadingSkeleton } from "@/components/States";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Label, Select, Spinner, Textarea } from "@/components/ui/primitives";
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

type Enrolment = StudentMe["enrolments"][number];

export default function StudentDashboardPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [disputing, setDisputing] = useState<Enrolment | null>(null);
  const [category, setCategory] = useState(DISPUTE_CATEGORIES[0].value);
  const [reason, setReason] = useState("");

  const query = useQuery({ queryKey: ["student-me"], queryFn: api.studentMe });

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
  if (query.isLoading || !query.data) return <LoadingSkeleton rows={6} />;

  const { student, enrolments, open_cases, pending_consents } = query.data;
  const unconfirmed = enrolments.filter((row) => row.confirmation === "unconfirmed");

  return (
    <>
      <PageHeader
        title={student.name ?? "My records"}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <MaskedApaar value={student.apaar_masked} />
            <span>·</span>
            <span>born {dateOnly(student.dob)}</span>
            {student.is_minor && <Badge tone="warning">under 18</Badge>}
            {student.apaar_status === "not_applicable" && (
              <Badge tone="neutral">APAAR not applicable</Badge>
            )}
          </span>
        }
      />

      {/* ------------------------------------------------- "Was this you?" */}
      {unconfirmed.length > 0 && (
        <div className="mb-5 space-y-3">
          {unconfirmed.map((enrolment) => (
            <Card key={enrolment.id} className="border-accent bg-accent/5">
              <CardContent className="pt-5">
                <p className="flex items-start gap-2 text-sm font-semibold">
                  <HelpCircle className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
                  Was this you?
                </p>
                <p className="mt-2 text-sm leading-relaxed">
                  You have been reported as enrolled in <strong>{enrolment.program}</strong> at{" "}
                  <strong>{enrolment.institution_name}</strong> for {enrolment.academic_year}
                  {enrolment.admitted_on ? `, admitted ${dateOnly(enrolment.admitted_on)}` : ""}. Is
                  that correct?
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    disabled={confirm.isPending}
                    onClick={() => confirm.mutate(enrolment.id)}
                  >
                    {confirm.isPending ? <Spinner /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                    Yes, that is correct
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setDisputing(enrolment);
                      setReason("");
                    }}
                  >
                    <AlertTriangle className="h-3.5 w-3.5" />
                    No — dispute this
                  </Button>
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  Disputing tells AICTE and the institution straight away. Nothing about your record
                  changes until AICTE looks at it.
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {open_cases.length > 0 && (
        <Card className="mb-5 border-red-200 bg-red-50/40">
          <CardHeader>
            <CardTitle className="text-red-900">Your open cases</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1.5 text-sm">
              {open_cases.map((item) => (
                <li key={item.flag_id} className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{flagLabel(item.type)}</span>
                  <StatusBadge status={item.status} />
                  <span className="text-xs text-muted-foreground">
                    raised {dateTime(item.created_at)}
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-red-900">
              AICTE has been notified and can see the case in their queue.
            </p>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>What institutions have reported about you</CardTitle>
          </CardHeader>
          <CardContent>
            {enrolments.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No institution has reported an enrolment for you yet.
              </p>
            ) : (
              <ul className="divide-y divide-border">
                {enrolments.map((enrolment) => (
                  <li key={enrolment.id} className="py-3">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="font-medium">{enrolment.institution_name}</p>
                        <p className="text-sm text-muted-foreground">
                          {enrolment.program} · {enrolment.mode === "online" ? "online / ODL" : "regular"}
                        </p>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {enrolment.academic_year} · year {enrolment.year_of_study} ·{" "}
                          {enrolment.admission_type} · {enrolment.status}
                          {enrolment.reported_by_upload_at &&
                            ` · reported ${dateTime(enrolment.reported_by_upload_at)}`}
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
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Consent requests</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-semibold tabular-nums">{pending_consents}</p>
              <p className="mt-1 text-sm text-muted-foreground">
                {pending_consents === 0
                  ? "Nobody is waiting on your consent."
                  : "waiting for your answer"}
              </p>
              <Button asChild size="sm" variant="outline" className="mt-3 w-full">
                <Link href="/student/consents">Open the consent manager</Link>
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ShieldCheck className="h-4 w-4" />
                Your privacy
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm text-muted-foreground">
              <p>
                Your phone number and email are never stored — only a keyed hash of them. Your APAAR
                ID, name and date of birth are encrypted.
              </p>
              <p>
                Every time anyone looks at your details it is logged, with their reason, and you can
                read that log.
              </p>
              <Button asChild size="sm" variant="outline" className="w-full">
                <Link href="/student/access-log">Who accessed my data</Link>
              </Button>
            </CardContent>
          </Card>
        </div>
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

          <div className="space-y-3">
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
            <p className="text-xs text-muted-foreground">
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
