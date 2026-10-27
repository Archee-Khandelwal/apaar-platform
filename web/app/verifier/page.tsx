"use client";

/** Request a verification. The verifier learns nothing until the student consents. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, Clock, Info, ShieldOff, XCircle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/AppShell";
import { Button, Card, CardContent, CardHeader, CardTitle, Input, Label, Select, Spinner, Textarea } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { VerificationRequestStatus } from "@/lib/types";

const STATE_TONES: Record<string, { tone: string; icon: React.ReactNode; blurb: string }> = {
  pending: {
    tone: "border-amber-300 bg-amber-50 text-amber-900",
    icon: <Clock className="h-5 w-5" />,
    blurb: "Waiting for the student. Nothing has been shared with you yet.",
  },
  approved: {
    tone: "border-emerald-300 bg-emerald-50 text-emerald-900",
    icon: <BadgeCheck className="h-5 w-5" />,
    blurb: "The student consented. This is everything they agreed to share.",
  },
  denied: {
    tone: "border-slate-300 bg-slate-50 text-slate-700",
    icon: <XCircle className="h-5 w-5" />,
    blurb: "The student declined. No details were shared.",
  },
  expired: {
    tone: "border-slate-300 bg-slate-50 text-slate-700",
    icon: <Clock className="h-5 w-5" />,
    blurb: "The request expired before the student answered.",
  },
  revoked: {
    tone: "border-orange-300 bg-orange-50 text-orange-900",
    icon: <ShieldOff className="h-5 w-5" />,
    blurb: "The student withdrew consent, so the result no longer applies.",
  },
};

export default function VerifierPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [apaar, setApaar] = useState("");
  const [purpose, setPurpose] = useState("");
  const [note, setNote] = useState("");
  const [requestId, setRequestId] = useState<number | null>(null);

  const purposes = useQuery({ queryKey: ["verifier-purposes"], queryFn: api.purposes });

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
  const state = result ? STATE_TONES[result.status] : null;
  const chosenPurpose = purposes.data?.purposes.find((item) => item.value === purpose);

  return (
    <>
      <PageHeader
        title="Verify a student"
        description="Enter an APAAR ID and why you need to verify it. The student decides; you never see more than verified, programme and year."
        actions={
          <Button asChild variant="outline">
            <Link href="/verifier/requests">My requests</Link>
          </Button>
        }
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>New verification request</CardTitle>
          </CardHeader>
          <CardContent>
            <form
              className="space-y-3"
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
                <p className="text-xs text-muted-foreground">
                  We hash this immediately — the platform never stores the ID you type.
                </p>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="purpose">Purpose (required)</Label>
                <Select
                  id="purpose"
                  value={purpose}
                  onChange={(event) => setPurpose(event.target.value)}
                >
                  <option value="">Choose a purpose…</option>
                  {(purposes.data?.purposes ?? []).map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
                <p className="text-xs text-muted-foreground">
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
                className="w-full"
                disabled={apaar.trim().length < 8 || !purpose || create.isPending}
              >
                {create.isPending && <Spinner />}
                Ask the student for consent
              </Button>
            </form>
          </CardContent>
        </Card>

        <div className="space-y-4">
          {result && state ? (
            <Card className={state.tone.replace(/text-\S+/, "")}>
              <CardContent className="pt-5">
                <div className="flex items-start gap-3">
                  <span className={state.tone.split(" ").find((cls) => cls.startsWith("text-"))}>
                    {state.icon}
                  </span>
                  <div className="min-w-0">
                    <p className="text-lg font-semibold capitalize">{result.status}</p>
                    <p className="text-sm">{state.blurb}</p>
                  </div>
                </div>

                <dl className="mt-4 grid gap-3 sm:grid-cols-2">
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-muted-foreground">APAAR</dt>
                    <dd className="font-mono text-sm">{result.apaar_masked}</dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                      Requested
                    </dt>
                    <dd className="text-sm">{dateTime(result.requested_at)}</dd>
                  </div>
                </dl>

                {result.result ? (
                  <div className="mt-4 rounded-md border border-border bg-card p-4">
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Verification result
                    </p>
                    <p className="mt-1 text-2xl font-semibold">
                      {result.result.verified ? "Verified" : "Not verified"}
                    </p>
                    {result.result.program && (
                      <dl className="mt-2 space-y-1 text-sm">
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
                    <p className="mt-3 text-xs text-muted-foreground">
                      That is the complete response. No name, date of birth, institution or contact
                      detail is ever returned to a verifier.
                    </p>
                  </div>
                ) : (
                  result.status === "pending" && (
                    <p className="mt-4 flex items-center gap-2 text-sm">
                      <Spinner /> Checking for the student&apos;s answer…
                    </p>
                  )
                )}
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Info className="h-4 w-4" />
                  How this works
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm text-muted-foreground">
                <p>
                  <strong>1.</strong> You submit an APAAR ID and a purpose
                  {chosenPurpose ? ` (${chosenPurpose.label})` : ""}.
                </p>
                <p>
                  <strong>2.</strong> The student is asked, and sees exactly what would be shared.
                </p>
                <p>
                  <strong>3.</strong> If they approve, you get verified yes/no, the programme and the
                  academic year. If they decline, or do nothing, you get nothing.
                </p>
                <p className="rounded-md bg-muted/50 p-3 text-xs">
                  An APAAR ID that does not exist produces exactly the same &ldquo;pending&rdquo;
                  response as one that does, so this form cannot be used to find out which IDs are
                  real.
                </p>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
