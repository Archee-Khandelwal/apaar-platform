"use client";

import { AppShell } from "@/components/AppShell";
import { Spinner } from "@/components/ui/primitives";
import { useRequireRole } from "@/lib/auth";
import type { Role } from "@/lib/types";

/** Wraps a role's section: guards the route, then renders it inside the portal shell. */
export function RoleGuard({ roles, children }: { roles: Role[]; children: React.ReactNode }) {
  const { allowed, ready } = useRequireRole(roles);

  if (!ready || !allowed) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-2 text-sm text-muted-foreground">
        <Spinner /> Checking your session…
      </div>
    );
  }
  return <AppShell>{children}</AppShell>;
}
