"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Spinner } from "@/components/ui/primitives";
import { ROLE_HOME, useAuth } from "@/lib/auth";

export default function HomePage() {
  const { user, ready } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!ready) return;
    router.replace(user ? ROLE_HOME[user.role] : "/login");
  }, [ready, user, router]);

  return (
    <main className="flex min-h-screen items-center justify-center gap-2 text-sm text-muted-foreground">
      <Spinner /> Loading…
    </main>
  );
}
