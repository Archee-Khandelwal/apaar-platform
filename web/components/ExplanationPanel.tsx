"use client";

/**
 * A flag's case file: the plain-English reason first, then the evidence a human
 * can check, then notes and history. Ids, raw JSON and anything else that is only
 * meaningful to a developer sits behind "Technical details".
 *
 * Explainability is a judged feature (CLAUDE.md section 8), so nothing here is
 * allowed to appear without its explanation.
 */
import { SeverityBadge, StatusBadge } from "@/components/SeverityBadge";
import { DialogTitle } from "@/components/ui/dialog";
import { ExplanationNote, TechnicalDetails } from "@/components/ui/page";
import { dateTime, flagLabel } from "@/lib/format";
import type { Flag, FlagDetail } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Keys that are either huge or meaningless to a reader. */
const HIDDEN_KEYS = new Set(["student_ids", "student_ids_masked", "rows", "all_features"]);

/** Keys that are identifiers rather than evidence, so they go behind the fold. */
const TECHNICAL_KEYS = /(^|_)(id|ids|hash|rule|code|version|key)$/;

/** Detector codes come through as snake_case; a reader wants "not found". */
const CODE = /^[a-z0-9]+(?:_[a-z0-9]+)+$/;

function Value({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-muted-foreground">—</span>;
  if (typeof value === "boolean") return <span>{value ? "yes" : "no"}</span>;
  if (typeof value === "string") return <span>{CODE.test(value) ? value.replace(/_/g, " ") : value}</span>;
  if (typeof value === "number") return <span>{String(value)}</span>;
  if (Array.isArray(value)) {
    if (value.every((item) => typeof item !== "object")) return <span>{value.join(", ")}</span>;
    return (
      <ul className="space-y-2">
        {value.map((item, index) => (
          <li key={index} className="rounded-md border border-border bg-secondary/40 p-3">
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
    <dl className={cn("grid gap-x-6 gap-y-3", compact ? "grid-cols-1 text-xs" : "text-sm sm:grid-cols-2")}>
      {entries.map(([key, value]) => (
        <div key={key} className="min-w-0">
          <dt className="type-label">{key.replace(/_/g, " ")}</dt>
          <dd className="mt-0.5 break-words font-medium">
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
  /** Inside a dialog the flag's title must also be the dialog's accessible name. */
  asDialogTitle = false,
}: {
  flag: Flag | FlagDetail;
  footer?: React.ReactNode;
  className?: string;
  asDialogTitle?: boolean;
}) {
  const evidence = (flag.evidence ?? {}) as Record<string, unknown>;
  const readable = Object.fromEntries(
    Object.entries(evidence).filter(([key]) => !TECHNICAL_KEYS.test(key)),
  );
  const technical = Object.fromEntries(
    Object.entries(evidence).filter(([key]) => TECHNICAL_KEYS.test(key)),
  );
  const hasEvidence = Object.keys(evidence).length > 0;
  const history = "history" in flag ? flag.history : [];
  const related = "related_flags" in flag ? flag.related_flags : [];
  const Heading = asDialogTitle ? DialogTitle : "h3";

  return (
    <div className={cn("space-y-6", className)}>
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <SeverityBadge severity={flag.severity} />
          <StatusBadge status={flag.status} />
          <span className="rounded bg-secondary px-2 py-0.5 text-xs font-medium">
            {flagLabel(flag.type)}
          </span>
          {flag.academic_year && (
            <span className="text-xs text-muted-foreground">{flag.academic_year}</span>
          )}
        </div>
        <Heading className="mt-3 text-base font-semibold leading-snug">{flag.title}</Heading>
        {flag.institution_name && (
          <p className="mt-1 text-sm text-muted-foreground">
            {flag.institution_name}
            {flag.state ? ` · ${flag.state}` : ""}
          </p>
        )}
      </div>

      <ExplanationNote>{flag.explanation}</ExplanationNote>

      {hasEvidence ? (
        <div className="space-y-4">
          <div>
            <p className="mb-3 type-label">Evidence</p>
            <EvidenceGrid evidence={readable} />
          </div>
          <TechnicalDetails>
            {Object.keys(technical).length > 0 && (
              <div className="mb-3">
                <EvidenceGrid evidence={technical} compact />
              </div>
            )}
            <pre className="max-h-72 overflow-auto rounded-md bg-slate-900 p-3 text-xs leading-relaxed text-slate-100">
              {JSON.stringify(evidence, null, 2)}
            </pre>
          </TechnicalDetails>
        </div>
      ) : (
        <p className="rounded-md bg-secondary/60 p-4 text-xs leading-relaxed text-muted-foreground">
          Evidence detail is available to AICTE officers. Analysts see aggregates and masked rows.
        </p>
      )}

      {related.length > 0 && (
        <div>
          <p className="mb-2 type-label">Related findings for this student</p>
          <ul className="flex flex-wrap gap-2">
            {related.map((item) => (
              <li
                key={item.id}
                className="inline-flex items-center gap-2 rounded-md border border-border px-2.5 py-1.5 text-xs"
              >
                <SeverityBadge severity={item.severity} showDot={false} />
                {flagLabel(item.type)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {flag.notes && flag.notes.length > 0 && (
        <div>
          <p className="mb-2 type-label">Case notes</p>
          <ul className="space-y-2">
            {flag.notes.map((note, index) => (
              <li key={index} className="rounded-md border border-border bg-secondary/40 p-3 text-sm">
                <p className="leading-relaxed">{note.note}</p>
                <p className="mt-1.5 text-xs text-muted-foreground">
                  {note.author} · {dateTime(note.created_at)}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {history.length > 0 && (
        <div>
          <p className="mb-2 type-label">Case history</p>
          <ol className="space-y-1.5 text-xs leading-relaxed text-muted-foreground">
            {history.map((item, index) => (
              <li key={index}>
                {dateTime(item.at)} — {item.actor ?? "system"} moved it from{" "}
                <strong className="font-medium">{item.from ?? "—"}</strong> to{" "}
                <strong className="font-medium">{item.to ?? "—"}</strong>
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
