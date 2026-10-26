"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRight, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { Button, Card, Input, Label, Spinner } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { ROLE_HOME, useAuth } from "@/lib/auth";
import type { DemoUser, Role } from "@/lib/types";
import { cn } from "@/lib/utils";

const ROLE_ORDER: Role[] = [
  "aicte_officer",
  "aicte_viewer",
  "institution",
  "student",
  "verifier",
  "admin",
];

const ROLE_BLURB: Record<Role, string> = {
  aicte_officer: "Full case powers: flag details, reveal with a reason, case management.",
  aicte_viewer: "Aggregates and masked rows only, with counts below 5 suppressed.",
  institution: "Upload data and see only your own students, flags and seat matrix.",
  student: "See what was reported about you, dispute it, and control who may verify you.",
  verifier: "Request a verification; you learn nothing until the student consents.",
  admin: "Reseed the demo, load scenarios, verify the audit chain.",
};

export default function LoginPage() {
  const { login, user, ready } = useAuth();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("demo1234");
  const [error, setError] = useState<string | null>(null);

  const { data } = useQuery({ queryKey: ["demo-users"], queryFn: api.demoUsers, staleTime: Infinity });

  useEffect(() => {
    if (ready && user) router.replace(ROLE_HOME[user.role]);
  }, [ready, user, router]);

  const mutation = useMutation({
    mutationFn: async (credentials: { username: string; password: string }) => {
      setError(null);
      return login(credentials.username, credentials.password);
    },
    onSuccess: (next) => router.replace(ROLE_HOME[next.role]),
    onError: (failure: Error) => setError(failure.message),
  });

  const grouped = useMemo(() => {
    const users = data?.users ?? [];
    return ROLE_ORDER.map((role) => ({
      role,
      users: users.filter((account) => account.role === role),
    })).filter((group) => group.users.length > 0);
  }, [data]);

  function signIn(account: DemoUser) {
    setUsername(account.username);
    setPassword(account.password);
    mutation.mutate({ username: account.username, password: account.password });
  }

  return (
    <main className="min-h-screen bg-gradient-to-b from-slate-50 to-slate-100">
      <p className="bg-amber-100 px-4 py-1.5 text-center text-xs font-medium text-amber-900">
        Prototype — all data is synthetic.
      </p>

      <div className="mx-auto grid max-w-6xl gap-6 px-4 py-10 lg:grid-cols-[1fr_1.15fr]">
        <div>
          <p className="text-xs font-semibold uppercase tracking-widest text-accent">
            SIH26263 · AICTE
          </p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">
            APAAR Student Data &amp; Verification Platform
          </h1>
          <p className="mt-3 max-w-prose text-sm leading-relaxed text-muted-foreground">
            Student-level enrolment reporting keyed on APAAR ID, with automatic validation,
            explainable fraud detection and consent-based verification. AICTE sees a risk-ranked
            national view; a college sees only its own data; a student sees and controls theirs.
          </p>

          <Card className="mt-6 p-5">
            <form
              className="space-y-3"
              onSubmit={(event) => {
                event.preventDefault();
                mutation.mutate({ username, password });
              }}
            >
              <div className="space-y-1.5">
                <Label htmlFor="username">Username</Label>
                <Input
                  id="username"
                  value={username}
                  autoComplete="username"
                  onChange={(event) => setUsername(event.target.value)}
                  placeholder="aicte_officer1"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  autoComplete="current-password"
                  onChange={(event) => setPassword(event.target.value)}
                />
              </div>
              {error && (
                <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>
              )}
              <Button type="submit" className="w-full" disabled={mutation.isPending || !username}>
                {mutation.isPending && <Spinner />}
                Sign in
              </Button>
            </form>
            <p className="mt-3 flex items-start gap-1.5 text-xs text-muted-foreground">
              <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              Every demo password is <code className="font-mono">demo1234</code>. Contact details
              are never stored in this system — only keyed hashes.
            </p>
          </Card>
        </div>

        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Demo accounts — one click to sign in
          </h2>
          <div className="mt-3 space-y-4">
            {grouped.map((group) => (
              <div key={group.role}>
                <p className="text-xs font-semibold">{ROLE_BLURB[group.role]}</p>
                <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
                  {group.users.slice(0, group.role === "institution" ? 4 : 8).map((account) => (
                    <button
                      key={account.username}
                      type="button"
                      onClick={() => signIn(account)}
                      disabled={mutation.isPending}
                      className={cn(
                        "group flex items-center justify-between gap-2 rounded-md border border-border bg-card px-3 py-2 text-left transition-colors hover:border-primary hover:bg-primary/5 disabled:opacity-60",
                      )}
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium">{account.label}</span>
                        <span className="block truncate font-mono text-xs text-muted-foreground">
                          {account.username}
                        </span>
                      </span>
                      <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                    </button>
                  ))}
                </div>
                {group.role === "institution" && group.users.length > 4 && (
                  <p className="mt-1.5 text-xs text-muted-foreground">
                    {group.users.length - 4} more institution accounts exist; any of them works.
                  </p>
                )}
              </div>
            ))}
            {grouped.length === 0 && (
              <p className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
                No demo accounts found. Run <code className="font-mono">make reset</code> to seed the
                database, then reload.
              </p>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
