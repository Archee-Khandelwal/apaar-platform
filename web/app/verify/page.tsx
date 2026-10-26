"use client";

/** Public QR / token check. No login, and no portal shell. */
import { useMutation } from "@tanstack/react-query";
import { BadgeCheck, CircleSlash, Clock, HelpCircle, ShieldX } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Button, Card, Input, Label, Spinner } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { TokenCheck, TokenState } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATES: Record<
  TokenState,
  { label: string; blurb: string; tone: string; icon: React.ReactNode }
> = {
  genuine: {
    label: "Genuine",
    blurb: "This token was issued by the platform and the student's consent is still active.",
    tone: "border-emerald-300 bg-emerald-50 text-emerald-900",
    icon: <BadgeCheck className="h-10 w-10" />,
  },
  expired: {
    label: "Expired",
    blurb: "This token was valid but has passed its expiry. Ask for a fresh one.",
    tone: "border-amber-300 bg-amber-50 text-amber-900",
    icon: <Clock className="h-10 w-10" />,
  },
  revoked: {
    label: "Revoked",
    blurb: "The student has withdrawn consent, so this token no longer verifies anything.",
    tone: "border-orange-300 bg-orange-50 text-orange-900",
    icon: <CircleSlash className="h-10 w-10" />,
  },
  invalid: {
    label: "Invalid",
    blurb: "This is not a token issued by the platform, or it has been altered.",
    tone: "border-red-300 bg-red-50 text-red-900",
    icon: <ShieldX className="h-10 w-10" />,
  },
};

function VerifyInner() {
  const params = useSearchParams();
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

  return (
    <main className="min-h-screen bg-slate-50">
      <p className="bg-amber-100 px-4 py-1.5 text-center text-xs font-medium text-amber-900">
        Prototype — all data is synthetic.
      </p>
      <div className="mx-auto max-w-xl px-4 py-10">
        <p className="text-xs font-semibold uppercase tracking-widest text-accent">
          Public verification
        </p>
        <h1 className="mt-1 text-xl font-semibold tracking-tight">Check a student QR or token</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Paste the token from a student&apos;s digital ID card. The check tells you whether the
          token is genuine and, if the student has consented, their programme and academic year —
          nothing else.
        </p>

        <Card className="mt-5 p-5">
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
          <div className={cn("mt-5 rounded-lg border p-6 text-center", state.tone)}>
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

        <p className="mt-6 flex items-start gap-1.5 text-xs text-muted-foreground">
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
