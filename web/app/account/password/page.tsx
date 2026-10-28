"use client";

/**
 * Change password. Reached from the sidebar, or forced straight after an admin reset —
 * in which case the temporary password unlocks nothing else until this form is done.
 */
import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, KeyRound } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button, Card, Input, Label, Spinner } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { ROLE_HOME, useAuth } from "@/lib/auth";

export default function ChangePasswordPage() {
  const { user, ready, passwordChanged } = useAuth();
  const router = useRouter();
  const { toast } = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (ready && !user) router.replace("/login");
  }, [ready, user, router]);

  const mutation = useMutation({
    mutationFn: () => api.changePassword(current, next),
    onSuccess: (result) => {
      passwordChanged(result.access_token);
      toast("Password changed. Every other session has been signed out.", "success");
      router.replace(user ? ROLE_HOME[user.role] : "/login");
    },
    onError: (failure: Error) => setError(failure.message),
  });

  if (!user) return null;
  const forced = Boolean(user.must_change_password);
  const mismatch = confirm.length > 0 && confirm !== next;

  return (
    <main className="min-h-screen bg-background">
      <p className="bg-amber-100 px-4 py-2 text-center text-xs font-medium text-amber-900">
        Prototype — all data is synthetic.
      </p>
      <div className="mx-auto w-full max-w-md px-4 py-12">
        {!forced && (
          <Button asChild variant="ghost" size="sm" className="mb-3 -ml-2">
            <Link href={ROLE_HOME[user.role]}>
              <ArrowLeft className="h-3.5 w-3.5" />
              Back
            </Link>
          </Button>
        )}
        <Card className="p-6">
          <p className="flex items-center gap-2 text-base font-semibold">
            <KeyRound className="h-5 w-5 text-primary" />
            {forced ? "Set a new password" : "Change password"}
          </p>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            {forced
              ? "An administrator reset this account. Choose your own password to continue."
              : `Signed in as ${user.username}. Changing it signs out every other session.`}
          </p>

          <form
            className="mt-5 space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              setError(null);
              mutation.mutate();
            }}
          >
            <div className="space-y-1.5">
              <Label htmlFor="current">{forced ? "Temporary password" : "Current password"}</Label>
              <Input
                id="current"
                type="password"
                autoComplete="current-password"
                value={current}
                onChange={(event) => setCurrent(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="new">New password</Label>
              <Input
                id="new"
                type="password"
                autoComplete="new-password"
                value={next}
                onChange={(event) => setNext(event.target.value)}
              />
              <p className="text-xs leading-relaxed text-muted-foreground">
                At least 10 characters, mixing three of: lower case, upper case, digits, symbols.
                It must not contain your username.
              </p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="confirm">Repeat the new password</Label>
              <Input
                id="confirm"
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
              />
              {mismatch && <p className="text-xs text-red-700">The two new passwords differ.</p>}
            </div>

            {error && (
              <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                {error}
              </p>
            )}

            <Button
              type="submit"
              className="w-full"
              disabled={mutation.isPending || !current || !next || next !== confirm}
            >
              {mutation.isPending && <Spinner />}
              Save new password
            </Button>
          </form>
        </Card>
      </div>
    </main>
  );
}
