"use client";

/** The single sign-in page. The account's own role decides which dashboard opens. */
import { SyntheticNotice } from "@/components/SyntheticNotice";
import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button, Card, Input, Label, Spinner } from "@/components/ui/primitives";
import { ROLE_HOME, useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { login, logout, user, ready } = useAuth();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (ready && user && ROLE_HOME[user.role]) {
      router.replace(user.must_change_password ? "/account/password" : ROLE_HOME[user.role]);
    }
  }, [ready, user, router]);

  const mutation = useMutation({
    mutationFn: async () => {
      setError(null);
      return login(username.trim(), password);
    },
    onSuccess: (next) => {
      const home = ROLE_HOME[next.role];
      if (!home) {
        // Operator accounts have no portal; they work from the command line.
        logout();
        setError("This account cannot sign in to the portal.");
        return;
      }
      router.replace(next.must_change_password ? "/account/password" : home);
    },
    onError: (failure: Error) => setError(failure.message),
  });

  return (
    <main className="flex min-h-screen flex-col bg-background">

      <div className="flex flex-1 items-center justify-center px-4 py-10">
        <div className="w-full max-w-md">
          <div className="mb-6 flex items-center gap-3">
            <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-md bg-primary text-sm font-bold tracking-tight text-primary-foreground">
              AP
            </span>
            <div>
              <p className="text-base font-semibold leading-tight">All India Council for Technical Education</p>
              <p className="text-sm leading-tight text-muted-foreground">APAAR Student Data &amp; Verification Portal</p>
            </div>
          </div>

          <Card className="p-6">
            <h1 className="type-page-title">Sign in</h1>
            <form
              className="mt-4 space-y-4"
              onSubmit={(event) => {
                event.preventDefault();
                if (username.trim() && password) mutation.mutate();
              }}
            >
              <div className="space-y-1.5">
                <Label htmlFor="username">Username</Label>
                <Input
                  id="username"
                  autoComplete="username"
                  autoFocus
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
              </div>
              {error && (
                <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">
                  {error}
                </p>
              )}
              <Button type="submit" className="w-full" disabled={!username.trim() || !password || mutation.isPending}>
                {mutation.isPending && <Spinner />}
                Sign in
              </Button>
            </form>
          </Card>

          <p className="mt-6 text-center text-xs text-muted-foreground">
            Employer or regulator checking a certificate?{" "}
            <a href="/verify" className="font-medium text-primary underline-offset-2 hover:underline">
              Verify without signing in
            </a>
          </p>
        </div>
      </div>
      <SyntheticNotice />
    </main>
  );
}
