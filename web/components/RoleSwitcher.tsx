"use client";

/**
 * Demo-only: jump to another seeded account.
 *
 * Each account has its own password (in demo_credentials.csv, never sent by the API),
 * so switching signs this session out and opens the sign-in form with that account
 * already selected.
 */
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, UserCog } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button, Spinner } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ROLE_LABELS } from "@/lib/nav";
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

/** Institutions run to 40; only the first few are useful in a demo. */
const MAX_PER_ROLE: Partial<Record<Role, number>> = { institution: 6 };

export function RoleSwitcher() {
  const { logout, user } = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["demo-users"],
    queryFn: api.demoUsers,
    staleTime: Infinity,
  });

  function switchTo(account: DemoUser) {
    setOpen(false);
    logout();
    router.push(`/login?u=${encodeURIComponent(account.username)}`);
  }

  const grouped = ROLE_ORDER.map((role) => ({
    role,
    users: (data?.users ?? []).filter((account) => account.role === role),
  })).filter((group) => group.users.length > 0);

  return (
    <div className="relative shrink-0">
      <Button variant="outline" size="sm" onClick={() => setOpen((value) => !value)}>
        <UserCog className="h-3.5 w-3.5" />
        <span className="hidden sm:inline">Switch account</span>
        <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
      </Button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-50 mt-2 max-h-[70vh] w-[19rem] max-w-[calc(100vw-2rem)] overflow-y-auto rounded-lg border border-border bg-card p-2 shadow-raised">
            <p className="px-2 py-1.5 text-xs leading-relaxed text-muted-foreground">
              Signs you out and opens the sign-in form for that account. Each password is in{" "}
              <code className="font-mono text-foreground">demo_credentials.csv</code>.
            </p>
            {isLoading && (
              <p className="flex items-center gap-2 p-3 text-sm text-muted-foreground">
                <Spinner /> Loading accounts…
              </p>
            )}
            {grouped.map((group) => {
              const limit = MAX_PER_ROLE[group.role] ?? group.users.length;
              return (
                <div key={group.role} className="mt-2">
                  <p className="px-2 pb-1 type-label">{ROLE_LABELS[group.role]}</p>
                  {group.users.slice(0, limit).map((account) => (
                    <button
                      key={account.username}
                      type="button"
                      onClick={() => switchTo(account)}
                      className={cn(
                        "flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-secondary",
                        user?.username === account.username && "bg-secondary",
                      )}
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block font-mono text-xs font-medium">{account.username}</span>
                        <span className="block text-xs leading-snug text-muted-foreground">
                          {account.label}
                        </span>
                      </span>
                    </button>
                  ))}
                  {group.users.length > limit && (
                    <p className="px-2 py-1 text-xs text-muted-foreground">
                      …and {group.users.length - limit} more {ROLE_LABELS[group.role].toLowerCase()}{" "}
                      accounts.
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
