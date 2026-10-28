"use client";

/** Public QR / token check. No login, and no portal shell. */
import { useMutation } from "@tanstack/react-query";
import { BadgeCheck, CircleSlash, Clock, HelpCircle, ShieldX } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Button, Card, Input, Label, Spinner } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { DocumentCheck, TokenCheck, TokenState } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATES: Record<
  TokenState,
  { label: string; blurb: string; tone: string; icon: React.ReactNode }
> = {
  genuine: {
    label: "Genuine",
    blurb: "This token was issued by the platform and the student's consent is still active.",
    tone: "border-emerald-200 bg-emerald-50 text-emerald-900",
    icon: <BadgeCheck className="h-10 w-10" />,
  },
  expired: {
    label: "Expired",
    blurb: "This token was valid but has passed its expiry. Ask for a fresh one.",
    tone: "border-amber-200 bg-amber-50 text-amber-900",
    icon: <Clock className="h-10 w-10" />,
  },
  revoked: {
    label: "Revoked",
    blurb: "The student has withdrawn consent, so this token no longer verifies anything.",
    tone: "border-orange-200 bg-orange-50 text-orange-900",
    icon: <CircleSlash className="h-10 w-10" />,
  },
  invalid: {
    label: "Invalid",
    blurb: "This is not a token issued by the platform, or it has been altered.",
    tone: "border-red-200 bg-red-50 text-red-900",
    icon: <ShieldX className="h-10 w-10" />,
  },
};

/** Public check of a signed degree certificate (the QR on the paper opens /verify?doc=...). */
function DocumentResult({ doc }: { doc: string }) {
  const [result, setResult] = useState<DocumentCheck | null>(null);
  const mutation = useMutation({ mutationFn: api.checkDocument, onSuccess: setResult });
  useEffect(() => {
    mutation.mutate(doc);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc]);

  const genuine = result?.state === "genuine";
  const revoked = result?.state === "revoked";
  const claims = result?.claims ?? {};
  return (
    <div
      className={cn(
        "mt-6 rounded-lg border p-6 text-center",
        genuine && "border-emerald-200 bg-emerald-50 text-emerald-900",
        revoked && "border-orange-200 bg-orange-50 text-orange-900",
        result?.state === "invalid" && "border-red-200 bg-red-50 text-red-900",
      )}
    >
      {!result && <Spinner />}
      {result && (
        <>
          <div className="flex justify-center">
            {genuine ? <BadgeCheck className="h-10 w-10" /> : revoked ? <CircleSlash className="h-10 w-10" /> : <ShieldX className="h-10 w-10" />}
          </div>
          <p className="mt-3 text-2xl font-semibold capitalize tracking-tight">{result.state}</p>
          <p className="mx-auto mt-1 max-w-sm text-sm">
            {genuine && "This document was issued by the platform and has not been altered."}
            {revoked && "The issuing institution has withdrawn this document."}
            {result.state === "invalid" && "This is not a document issued by the platform, or it has been altered."}
          </p>
          {(genuine || revoked) && (
            <dl className="mx-auto mt-5 grid max-w-sm gap-3 text-left sm:grid-cols-2">
              <div>
                <dt className="text-xs uppercase tracking-wide opacity-70">Serial</dt>
                <dd className="font-mono text-sm font-medium">{result.serial}</dd>
              </div>
              {Object.entries(claims).map(([key, value]) => (
                <div key={key}>
                  <dt className="text-xs uppercase tracking-wide opacity-70">{key.replace(/_/g, " ")}</dt>
                  <dd className="break-words text-sm font-medium">{String(value)}</dd>
                </div>
              ))}
            </dl>
          )}
          <p className="mt-5 text-xs opacity-70">Checked {dateTime(result.checked_at)}</p>
        </>
      )}
    </div>
  );
}

function VerifyInner() {
  const params = useSearchParams();
  const doc = params.get("doc");
  const [token, setToken] = useState(params.get("token") ?? "");
  const [result, setResult] = useState<TokenCheck | null>(null);

  const mutation = useMutation({
    mutationFn: (value: string) => api.checkToken(value.trim()),
    onSuccess: setResult,
  });

  useEffect(() => {
    const initial = params.get("token");
    if (initial) mutation.mutate(initial);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const state = result ? STATES[result.state] : null;

  if (doc) {
    return (
      <main className="min-h-screen bg-background">
        <p className="bg-amber-100 px-4 py-2 text-center text-xs font-medium text-amber-900">
          Prototype � all data is synthetic.
        </p>
        <div className="mx-auto max-w-xl px-4 py-10 sm:py-14">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">Public verification</p>
          <h1 className="mt-2 type-page-title">Degree certificate check</h1>
          <DocumentResult doc={doc} />
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-background">
      <p className="bg-amber-100 px-4 py-2 text-center text-xs font-medium text-amber-900">
        Prototype — all data is synthetic.
      </p>
      <div className="mx-auto max-w-xl px-4 py-10 sm:py-14">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">
          Public verification
        </p>
        <h1 className="mt-2 type-page-title">Verify a QR or token</h1>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
          Paste the token from a student&apos;s digital ID card. The check tells you whether the
          token is genuine and, if the student has consented, their programme and academic year —
          nothing else.
        </p>

        <Card className="mt-6 p-6">
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (token.trim()) mutation.mutate(token);
            }}
          >
            <div className="space-y-1.5">
              <Label htmlFor="token">Token</Label>
              <Input
                id="token"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                placeholder="v1.9931.88.1793038869.a3f9c2…"
                className="font-mono text-xs"
              />
            </div>
            <Button type="submit" className="w-full" disabled={!token.trim() || mutation.isPending}>
              {mutation.isPending && <Spinner />}
              Check this token
            </Button>
          </form>
        </Card>

        {result && state && (
          <div className={cn("mt-6 rounded-lg border p-6 text-center", state.tone)}>
            <div className="flex justify-center">{state.icon}</div>
            <p className="mt-3 text-2xl font-semibold tracking-tight">{state.label}</p>
            <p className="mx-auto mt-1 max-w-sm text-sm">{state.blurb}</p>

            {result.state === "genuine" && result.verified && (
              <dl className="mx-auto mt-5 grid max-w-sm gap-3 text-left sm:grid-cols-2">
                <div>
                  <dt className="text-xs uppercase tracking-wide opacity-70">Programme</dt>
                  <dd className="text-sm font-medium">{result.program}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wide opacity-70">Academic year</dt>
                  <dd className="text-sm font-medium">{result.academic_year}</dd>
                </div>
                {result.institution_name && (
                  <div className="sm:col-span-2">
                    <dt className="text-xs uppercase tracking-wide opacity-70">Institution</dt>
                    <dd className="text-sm font-medium">{result.institution_name}</dd>
                  </div>
                )}
              </dl>
            )}

            {result.state === "genuine" && !result.verified && (
              <p className="mt-4 text-sm">
                The token is genuine, but there is no active enrolment to confirm.
              </p>
            )}

            <p className="mt-5 text-xs opacity-70">Checked {dateTime(result.checked_at)}</p>
          </div>
        )}

        <p className="mt-8 flex items-start gap-2 text-xs leading-relaxed text-muted-foreground">
          <HelpCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          No name, date of birth or contact detail is ever returned by this check, and every check
          is written to the platform&apos;s audit trail.
        </p>
      </div>
    </main>
  );
}

export default function VerifyPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center gap-2 text-sm text-muted-foreground">
          <Spinner /> Loading…
        </main>
      }
    >
      <VerifyInner />
    </Suspense>
  );
}
