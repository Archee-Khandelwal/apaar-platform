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
        "flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-card/50 px-6 py-12 text-center",
        className,
      )}
    >
      <span className="text-muted-foreground">{icon ?? <Inbox className="h-6 w-6" />}</span>
      <p className="text-sm font-medium">{title}</p>
      {description && <p className="max-w-md text-sm text-muted-foreground">{description}</p>}
      {action}
    </div>
  );
}

export function LoadingSkeleton({ rows = 4, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)} aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          className="h-10 animate-pulse rounded-md bg-muted"
          style={{ animationDelay: `${index * 60}ms` }}
        />
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
        "flex flex-col items-center gap-3 rounded-lg border border-red-200 bg-red-50 px-6 py-8 text-center",
        className,
      )}
    >
      <AlertTriangle className="h-6 w-6 text-red-600" />
      <div>
        <p className="text-sm font-medium text-red-900">Could not load this</p>
        <p className="mt-1 text-sm text-red-800">{message}</p>
      </div>
      {onRetry && (
        <Button size="sm" variant="outline" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}
