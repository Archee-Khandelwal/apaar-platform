"use client";

/**
 * Two steps, not a wall of cards.
 *
 *   1. Pick a role from six tiles.
 *   2. The best demo account for that role is preselected; the rest are in a
 *      dropdown. One button signs in.
 *
 * Typing a username and password by hand is still possible, behind a disclosure,
 * because the platform is not really password-less — it just has demo accounts.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  Building2,
  ChevronRight,
  GraduationCap,
  ShieldCheck,
  Settings2,
  UserSearch,
  UserRoundCheck,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type ComponentType } from "react";

import { Button, Card, Input, Label, Select, Spinner } from "@/components/ui/primitives";
import { TechnicalDetails } from "@/components/ui/page";
import { api } from "@/lib/api";
import { ROLE_HOME, useAuth } from "@/lib/auth";
import { ROLE_BLURBS, ROLE_LABELS } from "@/lib/nav";
import type { DemoUser, Role } from "@/lib/types";

const ROLE_TILES: { role: Role; icon: ComponentType<{ className?: string }> }[] = [
  { role: "institution", icon: Building2 },
  { role: "aicte_officer", icon: ShieldCheck },
  { role: "aicte_viewer", icon: UserSearch },
  { role: "student", icon: GraduationCap },
  { role: "verifier", icon: UserRoundCheck },
  { role: "admin", icon: Settings2 },
];

/**
 * The account each role should open with in a demo. Everything else stays in the
 * dropdown, in the order the API returned it.
 */
const PREFERRED: Partial<Record<Role, string>> = {
  institution: "rathnapura1_admin",
  aicte_officer: "aicte_officer1",
  aicte_viewer: "aicte_viewer1",
  student: "student_ghost",
  verifier: "verifier_demo",
  admin: "admin",
};

/**
 * Demo labels arrive as one long sentence, e.g.
 * "Student — member of a ghost cluster (use this one to dispute) — Trivendri …".
 * The dropdown wants "username — what makes this account interesting", so we
 * take the middle clause and drop the role prefix and the institution tail.
 */
function accountBlurb(account: DemoUser): string {
  const parts = account.label.split(" — ").map((part) => part.trim());
  const middle = parts.length > 1 ? parts[1] : parts[0];
  return middle.replace(/\s*\(.*?\)\s*$/, "").trim() || parts[0];
}

export default function LoginPage() {
  const { login, user, ready } = useAuth();
  const router = useRouter();
  const [role, setRole] = useState<Role | null>(null);
  const [username, setUsername] = useState("");
  const [manual, setManual] = useState({ username: "", password: "demo1234" });
  const [error, setError] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["demo-users"],
    queryFn: api.demoUsers,
    staleTime: Infinity,
  });

  useEffect(() => {
    if (ready && user) router.replace(ROLE_HOME[user.role]);
  }, [ready, user, router]);

  const accounts = useMemo(
    () => (data?.users ?? []).filter((account) => account.role === role),
    [data, role],
  );

  /**
   * Pick the best account for the chosen role. This runs again when the account
   * list arrives, so picking a role before the fetch lands still ends up with a
   * selection rather than an empty dropdown.
   */
  useEffect(() => {
    if (!role || accounts.length === 0) return;
    if (accounts.some((account) => account.username === username)) return;
    const preferred = accounts.find((account) => account.username === PREFERRED[role]) ?? accounts[0];
    setUsername(preferred.username);
  }, [role, accounts, username]);

  const mutation = useMutation({
    mutationFn: async (credentials: { username: string; password: string }) => {
      setError(null);
      return login(credentials.username, credentials.password);
    },
    onSuccess: (next) => router.replace(ROLE_HOME[next.role]),
    onError: (failure: Error) => setError(failure.message),
  });

  function chooseRole(next: Role) {
    setRole(next);
    setUsername("");
    setError(null);
  }

  const selected = accounts.find((account) => account.username === username);

  return (
    <main className="min-h-screen bg-background">
      <p className="bg-amber-100 px-4 py-2 text-center text-xs font-medium text-amber-900">
        Prototype — all data is synthetic.
      </p>

      <div className="mx-auto w-full max-w-3xl px-4 py-10 sm:py-14">
        <div className="text-center">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">
            SIH26263 · AICTE
          </p>
          <h1 className="mt-3 text-2xl font-semibold tracking-tight sm:text-3xl">
            APAAR Student Data &amp; Verification Platform
          </h1>
          <p className="mx-auto mt-3 max-w-xl text-sm leading-relaxed text-muted-foreground">
            Student-level enrolment reporting keyed on APAAR ID, with automatic validation,
            explainable fraud detection and consent-based verification.
          </p>
        </div>

        {/* ------------------------------------------------- step 1: the role */}
        {!role && (
          <section className="mt-10">
            <h2 className="text-sm font-semibold">Choose how you want to sign in</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Each role sees a different portal, with different powers over the same data.
            </p>
            <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {ROLE_TILES.map(({ role: option, icon: Icon }) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => chooseRole(option)}
                  disabled={isLoading}
                  className="group flex h-full flex-col gap-2 rounded-lg border border-border bg-card p-5 text-left shadow-card transition-colors hover:border-primary hover:bg-primary/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
                >
                  <span className="flex h-10 w-10 items-center justify-center rounded-md bg-primary/10 text-primary">
                    <Icon className="h-5 w-5" />
                  </span>
                  <span className="flex items-center gap-1 text-sm font-semibold">
                    {ROLE_LABELS[option]}
                    <ChevronRight className="h-3.5 w-3.5 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                  </span>
                  {/* Full sentence, wrapped — never cut off. */}
                  <span className="text-xs leading-relaxed text-muted-foreground">
                    {ROLE_BLURBS[option]}
                  </span>
                </button>
              ))}
            </div>
            {isLoading && (
              <p className="mt-4 flex items-center justify-center gap-2 text-sm text-muted-foreground">
                <Spinner /> Loading demo accounts…
              </p>
            )}
          </section>
        )}

        {/* ---------------------------------------------- step 2: the account */}
        {role && (
          <section className="mt-10">
            <Button variant="ghost" size="sm" className="mb-3 px-2" onClick={() => setRole(null)}>
              <ArrowLeft className="h-3.5 w-3.5" />
              Choose a different role
            </Button>

            <Card className="p-6">
              <h2 className="text-sm font-semibold">
                Sign in as {ROLE_LABELS[role]}
              </h2>
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                {ROLE_BLURBS[role]}
              </p>

              <form
                className="mt-5 space-y-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  mutation.mutate({ username, password: "demo1234" });
                }}
              >
                <div className="space-y-1.5">
                  <Label htmlFor="account">Demo account</Label>
                  <Select
                    id="account"
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    className="h-10"
                  >
                    {accounts.map((account) => (
                      <option key={account.username} value={account.username}>
                        {account.username} — {accountBlurb(account)}
                      </option>
                    ))}
                  </Select>
                  {selected && (
                    <p className="text-xs leading-relaxed text-muted-foreground">
                      {selected.label}
                    </p>
                  )}
                  {accounts.length === 0 && (
                    <p className="flex items-center gap-2 text-xs text-muted-foreground">
                      {isLoading ? (
                        <>
                          <Spinner /> Loading demo accounts…
                        </>
                      ) : (
                        <>
                          No demo accounts found. Run <code className="font-mono">make reset</code>{" "}
                          to seed the database, then reload.
                        </>
                      )}
                    </p>
                  )}
                </div>

                {error && (
                  <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                    {error}
                  </p>
                )}

                <Button
                  type="submit"
                  size="lg"
                  className="w-full"
                  disabled={mutation.isPending || !username}
                >
                  {mutation.isPending && <Spinner />}
                  Enter
                </Button>
              </form>

              <TechnicalDetails label="Sign in with a username and password instead" className="mt-5">
                <form
                  className="space-y-3"
                  onSubmit={(event) => {
                    event.preventDefault();
                    mutation.mutate(manual);
                  }}
                >
                  <div className="space-y-1.5">
                    <Label htmlFor="manual-username">Username</Label>
                    <Input
                      id="manual-username"
                      value={manual.username}
                      autoComplete="username"
                      placeholder="aicte_officer1"
                      onChange={(event) =>
                        setManual((current) => ({ ...current, username: event.target.value }))
                      }
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="manual-password">Password</Label>
                    <Input
                      id="manual-password"
                      type="password"
                      value={manual.password}
                      autoComplete="current-password"
                      onChange={(event) =>
                        setManual((current) => ({ ...current, password: event.target.value }))
                      }
                    />
                  </div>
                  <Button
                    type="submit"
                    variant="outline"
                    className="w-full"
                    disabled={mutation.isPending || !manual.username}
                  >
                    Sign in
                  </Button>
                </form>
              </TechnicalDetails>
            </Card>
          </section>
        )}

        <p className="mt-6 flex flex-wrap items-center justify-center gap-x-1.5 gap-y-1 text-center text-xs text-muted-foreground">
          <ShieldCheck className="h-3.5 w-3.5 shrink-0" />
          <span>All demo passwords:</span>
          <code className="rounded bg-secondary px-1.5 py-0.5 font-mono text-foreground">demo1234</code>
        </p>
        <p className="mt-2 text-center text-xs text-muted-foreground">
          Contact details are never stored in this system — only keyed hashes.
        </p>
      </div>
    </main>
  );
}
