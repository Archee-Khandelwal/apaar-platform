"use client";

/** Demo-only: log in as any seeded account in one click. */
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { ChevronDown, UserCog } from "lucide-react";
import { useState } from "react";

import { Button, Spinner } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { ROLE_HOME, useAuth } from "@/lib/auth";
import type { DemoUser, Role } from "@/lib/types";
import { cn } from "@/lib/utils";

const ROLE_GROUPS: { role: Role; label: string }[] = [
  { role: "aicte_officer", label: "AICTE Officer" },
  { role: "aicte_viewer", label: "AICTE Analyst" },
  { role: "institution", label: "Institutions" },
  { role: "student", label: "Students" },
  { role: "verifier", label: "Verifiers" },
  { role: "admin", label: "Admin" },
];

export function RoleSwitcher() {
  const { login, user } = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["demo-users"],
    queryFn: api.demoUsers,
    staleTime: Infinity,
  });

  async function switchTo(account: DemoUser) {
    setBusy(account.username);
    try {
      const next = await login(account.username, account.password);
      setOpen(false);
      router.push(ROLE_HOME[next.role]);
      router.refresh();
    } finally {
      setBusy(null);
    }
  }

  const grouped = ROLE_GROUPS.map((group) => ({
    ...group,
    users: (data?.users ?? []).filter((account) => account.role === group.role),
  })).filter((group) => group.users.length > 0);

  return (
    <div className="relative">
      <Button variant="outline" size="sm" onClick={() => setOpen((value) => !value)}>
        <UserCog className="h-3.5 w-3.5" />
        <span className="hidden sm:inline">Switch role</span>
        <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
      </Button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-50 mt-2 max-h-[70vh] w-80 overflow-y-auto rounded-lg border border-border bg-card p-2 shadow-lg">
            <p className="px-2 py-1.5 text-xs text-muted-foreground">
              Demo accounts — every password is <code className="font-mono">demo1234</code>.
            </p>
            {isLoading && (
              <p className="flex items-center gap-2 p-3 text-sm text-muted-foreground">
                <Spinner /> Loading accounts…
              </p>
            )}
            {grouped.map((group) => (
              <div key={group.role} className="mt-1">
                <p className="px-2 py-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {group.label}
                </p>
                {group.users.slice(0, group.role === "institution" ? 6 : 10).map((account) => (
                  <button
                    key={account.username}
                    type="button"
                    onClick={() => switchTo(account)}
                    disabled={busy !== null}
                    className={cn(
                      "flex w-full items-start gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-muted disabled:opacity-60",
                      user?.username === account.username && "bg-muted",
                    )}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{account.label}</span>
                      <span className="block truncate font-mono text-xs text-muted-foreground">
                        {account.username}
                      </span>
                    </span>
                    {busy === account.username && <Spinner className="mt-1" />}
                  </button>
                ))}
                {group.role === "institution" && group.users.length > 6 && (
                  <p className="px-2 py-1 text-xs text-muted-foreground">
                    …and {group.users.length - 6} more institution accounts (see the login page).
                  </p>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
