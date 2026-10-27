"use client";

/** Request a verification. The verifier learns nothing until the student consents. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, Clock, ShieldOff, XCircle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Skeleton } from "@/components/States";
import { KpiCard, KpiRow, PageHeader, SectionCard } from "@/components/ui/page";
import { Button, Input, Label, Select, Spinner, Textarea } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { VerificationRequestStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATES: Record<string, { tone: string; icon: React.ReactNode; blurb: string }> = {
  pending: {
    tone: "border-amber-200 bg-amber-50 text-amber-900",
    icon: <Clock className="h-5 w-5" />,
    blurb: "Waiting for the student. Nothing has been shared with you yet.",
  },
  approved: {
    tone: "border-emerald-200 bg-emerald-50 text-emerald-900",
    icon: <BadgeCheck className="h-5 w-5" />,
    blurb: "The student consented. This is everything they agreed to share.",
  },
  denied: {
    tone: "border-slate-200 bg-slate-50 text-slate-700",
    icon: <XCircle className="h-5 w-5" />,
    blurb: "The student declined. No details were shared.",
  },
  expired: {
    tone: "border-slate-200 bg-slate-50 text-slate-700",
    icon: <Clock className="h-5 w-5" />,
    blurb: "The request expired before the student answered.",
  },
  revoked: {
    tone: "border-orange-200 bg-orange-50 text-orange-900",
    icon: <ShieldOff className="h-5 w-5" />,
    blurb: "The student withdrew consent, so the result no longer applies.",
  },
};

export default function VerifierHomePage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [apaar, setApaar] = useState("");
  const [purpose, setPurpose] = useState("");
  const [note, setNote] = useState("");
  const [requestId, setRequestId] = useState<number | null>(null);

  const purposes = useQuery({ queryKey: ["verifier-purposes"], queryFn: api.purposes });
  const history = useQuery({
    queryKey: ["verifier-requests", 1],
    queryFn: () => api.verificationRequests({ page: 1, page_size: 100 }),
  });

  const create = useMutation({
    mutationFn: () =>
      api.createVerification({ apaar: apaar.trim(), purpose, note: note.trim() || undefined }),
    onSuccess: (result) => {
      setRequestId(result.request_id);
      toast(result.message, "info");
      queryClient.invalidateQueries({ queryKey: ["verifier-requests"] });
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  // Poll while the request is pending, so the demo shows the state flipping live.
  const status = useQuery({
    queryKey: ["verification-request", requestId],
    queryFn: () => api.verificationRequest(requestId!),
    enabled: requestId !== null,
    refetchInterval: (query) =>
      (query.state.data as VerificationRequestStatus | undefined)?.status === "pending" ? 3000 : false,
  });

  const result = status.data;
  const state = result ? STATES[result.status] : null;
  const rows = history.data?.items ?? [];
  const counts = {
    total: history.data?.total ?? 0,
    pending: rows.filter((row) => row.status === "pending").length,
    approved: rows.filter((row) => row.status === "approved").length,
    refused: rows.filter((row) => ["denied", "expired", "revoked"].includes(row.status)).length,
  };

  return (
    <>
      <PageHeader
        title="New request"
        description="Ask a student to confirm an enrolment. They decide, and you never see more than verified, programme and year."
        actions={
          <Button asChild variant="outline">
            <Link href="/verifier/requests">My requests</Link>
          </Button>
        }
      />

      {history.isLoading ? (
        <Skeleton rows={1} height="h-[7.25rem]" />
      ) : (
        <KpiRow>
          <KpiCard label="Requests sent" value={counts.total} hint="All time" />
          <KpiCard
            label="Awaiting a student"
            value={counts.pending}
            hint="Nothing has been shared with you yet"
            tone={counts.pending > 0 ? "warning" : "default"}
          />
          <KpiCard
            label="Consented"
            value={counts.approved}
            hint="Verified, with programme and year"
            tone={counts.approved > 0 ? "positive" : "default"}
          />
          <KpiCard
            label="Declined or expired"
            value={counts.refused}
            hint="No details were shared"
          />
        </KpiRow>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <SectionCard title="Verify a student">
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              create.mutate();
            }}
          >
            <div className="space-y-1.5">
              <Label htmlFor="apaar">APAAR ID (12 digits)</Label>
              <Input
                id="apaar"
                value={apaar}
                onChange={(event) => setApaar(event.target.value)}
                placeholder="123456781234"
                className="font-mono"
                inputMode="numeric"
              />
              <p className="text-xs leading-relaxed text-muted-foreground">
                We hash this immediately — the platform never stores the ID you type.
              </p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="purpose">Purpose (required)</Label>
              <Select id="purpose" value={purpose} onChange={(event) => setPurpose(event.target.value)}>
                <option value="">Choose a purpose…</option>
                {(purposes.data?.purposes ?? []).map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
              <p className="text-xs leading-relaxed text-muted-foreground">
                The student is shown this purpose when they decide. Free text is not accepted.
              </p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="note">Your own reference (optional)</Label>
              <Textarea
                id="note"
                value={note}
                onChange={(event) => setNote(event.target.value)}
                placeholder="e.g. Offer-stage check for candidate ref #4471"
              />
            </div>
            <Button
              type="submit"
              size="lg"
              className="w-full"
              disabled={apaar.trim().length < 8 || !purpose || create.isPending}
            >
              {create.isPending && <Spinner />}
              Ask the student for consent
            </Button>
          </form>
        </SectionCard>

        {result && state ? (
          <SectionCard title="This request">
            <div className={cn("flex items-start gap-3 rounded-md border p-4", state.tone)}>
              <span className="mt-0.5 shrink-0">{state.icon}</span>
              <div className="min-w-0">
                <p className="text-sm font-semibold capitalize">{result.status}</p>
                <p className="mt-0.5 text-sm leading-relaxed">{state.blurb}</p>
              </div>
            </div>

            <dl className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <dt className="type-label">APAAR</dt>
                <dd className="mt-1 font-mono text-sm">{result.apaar_masked}</dd>
              </div>
              <div>
                <dt className="type-label">Requested</dt>
                <dd className="mt-1 text-sm">{dateTime(result.requested_at)}</dd>
              </div>
            </dl>

            {result.result ? (
              <div className="mt-5 rounded-md border border-border bg-secondary/50 p-4">
                <p className="type-label">Verification result</p>
                <p className="mt-1 text-2xl font-semibold">
                  {result.result.verified ? "Verified" : "Not verified"}
                </p>
                {result.result.program && (
                  <dl className="mt-3 space-y-1 text-sm">
                    <div>
                      <dt className="inline text-muted-foreground">Programme: </dt>
                      <dd className="inline font-medium">{result.result.program}</dd>
                    </div>
                    <div>
                      <dt className="inline text-muted-foreground">Academic year: </dt>
                      <dd className="inline font-medium">{result.result.academic_year}</dd>
                    </div>
                  </dl>
                )}
                <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                  That is the complete response. No name, date of birth, institution or contact
                  detail is ever returned to a verifier.
                </p>
              </div>
            ) : (
              result.status === "pending" && (
                <p className="mt-5 flex items-center gap-2 text-sm text-muted-foreground">
                  <Spinner /> Checking for the student&apos;s answer…
                </p>
              )
            )}
          </SectionCard>
        ) : (
          <SectionCard title="How this works">
            <ol className="space-y-4">
              {[
                "You submit an APAAR ID and a purpose from the fixed list.",
                "The student is asked, and sees exactly what would be shared.",
                "If they approve, you get verified yes/no, the programme and the academic year. If they decline, or do nothing, you get nothing.",
              ].map((step, index) => (
                <li key={index} className="flex gap-3">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                    {index + 1}
                  </span>
                  <span className="text-sm leading-relaxed">{step}</span>
                </li>
              ))}
            </ol>
            <p className="mt-5 rounded-md bg-secondary/60 p-4 text-xs leading-relaxed text-muted-foreground">
              An APAAR ID that does not exist produces exactly the same &ldquo;pending&rdquo;
              response as one that does, so this form cannot be used to find out which IDs are real.
            </p>
          </SectionCard>
        )}
      </div>
    </>
  );
}
