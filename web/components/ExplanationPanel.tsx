"use client";

/**
 * Renders a flag's explanation and structured evidence. Explainability is the product
 * (CLAUDE.md section 8), so this panel is deliberately generous: the plain-English
 * sentence first, then the evidence a human can check.
 */
import { ChevronRight } from "lucide-react";
import { useState } from "react";

import { SeverityBadge, StatusBadge } from "@/components/SeverityBadge";
import { Button } from "@/components/ui/primitives";
import { dateTime, flagLabel } from "@/lib/format";
import type { Flag, FlagDetail } from "@/lib/types";
import { cn } from "@/lib/utils";

const HIDDEN_KEYS = new Set(["student_ids", "student_ids_masked", "rows", "all_features"]);

function Value({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-muted-foreground">—</span>;
  if (typeof value === "boolean") return <span>{value ? "yes" : "no"}</span>;
  if (typeof value === "number" || typeof value === "string") return <span>{String(value)}</span>;
  if (Array.isArray(value)) {
    if (value.every((item) => typeof item !== "object")) return <span>{value.join(", ")}</span>;
    return (
      <ul className="space-y-1">
        {value.map((item, index) => (
          <li key={index} className="rounded border border-border bg-muted/40 p-2">
            <EvidenceGrid evidence={item as Record<string, unknown>} compact />
          </li>
        ))}
      </ul>
    );
  }
  return <EvidenceGrid evidence={value as Record<string, unknown>} compact />;
}

function EvidenceGrid({
  evidence,
  compact = false,
}: {
  evidence: Record<string, unknown>;
  compact?: boolean;
}) {
  const entries = Object.entries(evidence).filter(([key]) => !HIDDEN_KEYS.has(key));
  if (entries.length === 0) return null;
  return (
    <dl className={cn("grid gap-x-4 gap-y-1.5", compact ? "grid-cols-1 text-xs" : "sm:grid-cols-2 text-sm")}>
      {entries.map(([key, value]) => (
        <div key={key} className="min-w-0">
          <dt className="text-xs uppercase tracking-wide text-muted-foreground">
            {key.replace(/_/g, " ")}
          </dt>
          <dd className="break-words font-medium">
            <Value value={value} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function ExplanationPanel({
  flag,
  footer,
  className,
}: {
  flag: Flag | FlagDetail;
  footer?: React.ReactNode;
  className?: string;
}) {
  const [showRaw, setShowRaw] = useState(false);
  const evidence = (flag.evidence ?? {}) as Record<string, unknown>;
  const hasEvidence = Object.keys(evidence).length > 0;
  const history = "history" in flag ? flag.history : [];
  const related = "related_flags" in flag ? flag.related_flags : [];

  return (
    <div className={cn("space-y-5", className)}>
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <SeverityBadge severity={flag.severity} />
          <StatusBadge status={flag.status} />
          <span className="rounded bg-muted px-2 py-0.5 font-mono text-xs">{flagLabel(flag.type)}</span>
          {flag.academic_year && (
            <span className="text-xs text-muted-foreground">{flag.academic_year}</span>
          )}
        </div>
        <h3 className="mt-3 text-base font-semibold leading-snug">{flag.title}</h3>
        {flag.institution_name && (
          <p className="mt-1 text-sm text-muted-foreground">
            {flag.institution_name}
            {flag.state ? ` · ${flag.state}` : ""}
          </p>
        )}
      </div>

      <div className="rounded-lg border-l-4 border-accent bg-accent/5 p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-accent">Why this was flagged</p>
        <p className="mt-1.5 text-sm leading-relaxed">{flag.explanation}</p>
      </div>

      {hasEvidence ? (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Evidence
          </p>
          <EvidenceGrid evidence={evidence} />
          <Button
            size="sm"
            variant="ghost"
            className="mt-2 px-0 text-xs"
            onClick={() => setShowRaw((value) => !value)}
          >
            <ChevronRight className={cn("h-3 w-3 transition-transform", showRaw && "rotate-90")} />
            {showRaw ? "Hide" : "Show"} raw evidence
          </Button>
          {showRaw && (
            <pre className="mt-2 max-h-72 overflow-auto rounded-md bg-slate-900 p-3 text-xs text-slate-100">
              {JSON.stringify(evidence, null, 2)}
            </pre>
          )}
        </div>
      ) : (
        <p className="rounded-md bg-muted/50 p-3 text-xs text-muted-foreground">
          Evidence detail is available to AICTE officers. Analysts see aggregates and masked rows.
        </p>
      )}

      {related.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Related findings for this student
          </p>
          <div className="flex flex-wrap gap-2">
            {related.map((item) => (
              <span key={item.id} className="inline-flex items-center gap-1.5 rounded border border-border px-2 py-1 text-xs">
                <SeverityBadge severity={item.severity} showDot={false} />
                {flagLabel(item.type)}
              </span>
            ))}
          </div>
        </div>
      )}

      {flag.notes && flag.notes.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Case notes
          </p>
          <ul className="space-y-2">
            {flag.notes.map((note, index) => (
              <li key={index} className="rounded-md border border-border bg-muted/30 p-3 text-sm">
                <p>{note.note}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {note.author} · {dateTime(note.created_at)}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {history.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Case history
          </p>
          <ol className="space-y-1.5 text-xs text-muted-foreground">
            {history.map((item, index) => (
              <li key={index}>
                {dateTime(item.at)} — {item.actor ?? "system"} moved it from{" "}
                <strong>{item.from ?? "—"}</strong> to <strong>{item.to ?? "—"}</strong>
                {item.reason ? `: ${item.reason}` : ""}
              </li>
            ))}
          </ol>
        </div>
      )}

      <p className="text-xs text-muted-foreground">Raised {dateTime(flag.created_at)}</p>
      {footer}
    </div>
  );
}
