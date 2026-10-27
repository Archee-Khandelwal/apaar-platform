"use client";

import { AlertTriangle, Inbox } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

export function EmptyState({
  title,
  description,
  action,
  icon,
  className,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border bg-card px-6 py-14 text-center",
        className,
      )}
    >
      <span className="flex h-10 w-10 items-center justify-center rounded-full bg-secondary text-muted-foreground">
        {icon ?? <Inbox className="h-5 w-5" />}
      </span>
      <div className="max-w-md space-y-1">
        <p className="text-sm font-semibold">{title}</p>
        {description && <p className="text-sm leading-relaxed text-muted-foreground">{description}</p>}
      </div>
      {action}
    </div>
  );
}

/**
 * The skeleton loader. `aria-busy` is what the screenshot script waits on, so
 * every loading placeholder in the app must go through this component.
 */
export function Skeleton({
  rows = 4,
  className,
  height = "h-11",
}: {
  rows?: number;
  className?: string;
  height?: string;
}) {
  return (
    <div className={cn("space-y-3", className)} aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          className={cn("animate-pulse rounded-md bg-secondary", height)}
          style={{ animationDelay: `${index * 60}ms` }}
        />
      ))}
    </div>
  );
}

/** Kept under its original name so existing pages read the same. */
export const LoadingSkeleton = Skeleton;

/** The KPI strip while it loads, so the page does not jump when numbers arrive. */
export function KpiSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-busy="true" aria-label="Loading">
      {Array.from({ length: count }).map((_, index) => (
        <div key={index} className="h-[7.25rem] animate-pulse rounded-lg bg-secondary" />
      ))}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}) {
  const message = error instanceof Error ? error.message : "Something went wrong.";
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-3 rounded-lg border border-red-200 bg-red-50 px-6 py-10 text-center",
        className,
      )}
    >
      <AlertTriangle className="h-6 w-6 text-red-600" />
      <div className="max-w-md">
        <p className="text-sm font-semibold text-red-900">Could not load this</p>
        <p className="mt-1 text-sm leading-relaxed text-red-800">{message}</p>
      </div>
      {onRetry && (
        <Button size="sm" variant="outline" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}
