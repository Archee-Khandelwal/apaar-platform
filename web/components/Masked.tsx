"use client";

/**
 * Masked identifiers. These components exist so no page ever interpolates an APAAR ID
 * or a name directly: the API only sends masked values anyway (CLAUDE.md section 5
 * rule 6), and a single component makes that visible in the code.
 */
import { cn } from "@/lib/utils";

export function MaskedApaar({ value, className }: { value?: string | null; className?: string }) {
  return (
    <span
      className={cn("font-mono text-xs tracking-tight text-foreground", className)}
      title="APAAR ID is masked by default"
    >
      {value || "XXXX-XXXX-XXXX"}
    </span>
  );
}

export function MaskedName({ value, className }: { value?: string | null; className?: string }) {
  return <span className={cn("text-sm", className)}>{value || "***"}</span>;
}

export function SuppressedHint() {
  return (
    <span
      className="cursor-help text-muted-foreground"
      title="Counts below 5 are suppressed for analysts so individuals cannot be identified"
    >
      &lt;5
    </span>
  );
}
