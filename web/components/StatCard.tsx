"use client";

import type { ReactNode } from "react";

import { count } from "@/lib/format";
import type { Suppressible } from "@/lib/types";
import { cn } from "@/lib/utils";

export function StatCard({
  label,
  value,
  hint,
  icon,
  tone = "default",
  className,
}: {
  label: string;
  value: Suppressible | string | null | undefined;
  hint?: ReactNode;
  icon?: ReactNode;
  tone?: "default" | "warning" | "danger" | "success";
  className?: string;
}) {
  const tones = {
    default: "border-border",
    warning: "border-amber-300 bg-amber-50/60",
    danger: "border-red-300 bg-red-50/60",
    success: "border-emerald-300 bg-emerald-50/60",
  } as const;

  const display = typeof value === "number" || typeof value === "string" ? count(value as Suppressible) : "—";

  return (
    <div className={cn("rounded-lg border bg-card p-4 shadow-sm", tones[tone], className)}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
        {icon && <span className="text-muted-foreground">{icon}</span>}
      </div>
      <p className="mt-2 text-2xl font-semibold tabular-nums tracking-tight">{display}</p>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
