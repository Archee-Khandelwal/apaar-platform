"use client";

import type { FlagStatus, Severity } from "@/lib/types";
import { cn } from "@/lib/utils";

/** CLAUDE.md section 9: low=slate, medium=amber, high=orange, critical=red. */
const SEVERITY_STYLES: Record<Severity, string> = {
  low: "bg-slate-100 text-slate-700 ring-slate-300",
  medium: "bg-amber-100 text-amber-900 ring-amber-300",
  high: "bg-orange-100 text-orange-900 ring-orange-300",
  critical: "bg-red-100 text-red-800 ring-red-300",
};

export function SeverityBadge({
  severity,
  className,
  showDot = true,
}: {
  severity: Severity;
  className?: string;
  showDot?: boolean;
}) {
  const dots: Record<Severity, string> = {
    low: "bg-slate-500",
    medium: "bg-amber-500",
    high: "bg-orange-500",
    critical: "bg-red-600",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium capitalize ring-1 ring-inset",
        SEVERITY_STYLES[severity],
        className,
      )}
    >
      {showDot && <span className={cn("h-1.5 w-1.5 rounded-full", dots[severity])} />}
      {severity}
    </span>
  );
}

const STATUS_STYLES: Record<FlagStatus, string> = {
  open: "bg-sky-100 text-sky-900",
  under_review: "bg-violet-100 text-violet-900",
  escalated: "bg-orange-100 text-orange-900",
  dismissed: "bg-slate-100 text-slate-600",
  resolved: "bg-emerald-100 text-emerald-800",
};

export function StatusBadge({ status, className }: { status: FlagStatus; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        STATUS_STYLES[status],
        className,
      )}
    >
      {status.replace("_", " ")}
    </span>
  );
}
