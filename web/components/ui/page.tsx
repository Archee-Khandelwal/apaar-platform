"use client";

/**
 * The page template every screen is built from.
 *
 * PageHeader  — title + the one-line question the page answers, primary action right.
 * KpiRow/KpiCard — the numbers that matter, directly under the header.
 * SectionCard — a titled block of content.
 * TechnicalDetails — ids, rule codes and hashes, collapsed behind plain English.
 *
 * Pages compose these and nothing else, so spacing and type stay on the grid.
 */
import { ChevronRight } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { count } from "@/lib/format";
import type { Suppressible } from "@/lib/types";
import { cn } from "@/lib/utils";

export function PageHeader({
  title,
  description,
  actions,
  className,
}: {
  /** The page name. Short — the breadcrumb in the top bar repeats it. */
  title: string;
  /** One line saying what question this page answers. */
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("flex flex-wrap items-start justify-between gap-x-6 gap-y-3", className)}>
      <div className="min-w-0 max-w-3xl">
        <h1 className="type-page-title">{title}</h1>
        {description && <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

/** The KPI strip. Four cards at 1440, two at 768, one on a phone. */
export function KpiRow({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4", className)}>
      {children}
    </div>
  );
}

const KPI_TONES = {
  default: "border-border",
  positive: "border-emerald-200 bg-emerald-50/50",
  warning: "border-amber-200 bg-amber-50/50",
  critical: "border-red-200 bg-red-50/50",
} as const;

const KPI_VALUE_TONES = {
  default: "text-foreground",
  positive: "text-emerald-700",
  warning: "text-amber-700",
  critical: "text-red-700",
} as const;

export function KpiCard({
  label,
  value,
  hint,
  icon,
  tone = "default",
  className,
}: {
  label: string;
  value: Suppressible | string | null | undefined;
  /** One short line of context. It wraps rather than truncating. */
  hint?: ReactNode;
  icon?: ReactNode;
  tone?: keyof typeof KPI_TONES;
  className?: string;
}) {
  const display =
    typeof value === "number" || typeof value === "string" ? count(value as Suppressible) : "—";
  // A word or phrase gets a smaller size than a figure, so a KPI row stays even.
  const isPhrase = display.length > 7;

  return (
    <div className={cn("rounded-lg border bg-card p-4 shadow-card", KPI_TONES[tone], className)}>
      <div className="flex items-start justify-between gap-3">
        <p className="type-label min-w-0">{label}</p>
        {icon && <span className="shrink-0 text-muted-foreground">{icon}</span>}
      </div>
      <p
        className={cn(
          "mt-2 font-semibold tracking-tight",
          isPhrase ? "text-xl leading-snug first-letter:uppercase" : "text-3xl tabular-nums",
          KPI_VALUE_TONES[tone],
        )}
      >
        {display}
      </p>
      {hint && <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function SectionCard({
  title,
  description,
  actions,
  footer,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={cn("min-w-0 rounded-lg border border-border bg-card shadow-card", className)}>
      {(title || actions) && (
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 border-b border-border px-5 py-4">
          <div className="min-w-0">
            {title && <h2 className="type-section-title">{title}</h2>}
            {description && (
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{description}</p>
            )}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={cn("p-5", bodyClassName)}>{children}</div>
      {footer && <div className="border-t border-border px-5 py-3">{footer}</div>}
    </section>
  );
}

/**
 * Ids, rule codes, hashes and raw JSON belong here — never in the first thing a
 * reader sees. Uses <details> so it works without JavaScript and prints open.
 */
export function TechnicalDetails({
  children,
  label = "Technical details",
  className,
}: {
  children: ReactNode;
  label?: string;
  className?: string;
}) {
  return (
    <details className={cn("group rounded-md border border-border bg-muted/40", className)}>
      <summary className="flex cursor-pointer list-none items-center gap-1.5 px-3 py-2 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground">
        <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90" />
        {label}
      </summary>
      <div className="border-t border-border px-3 py-2.5">{children}</div>
    </details>
  );
}

/** A label/value pair list, used inside SectionCard bodies. */
export function FieldList({
  fields,
  columns = 2,
  className,
}: {
  fields: { label: string; value: ReactNode }[];
  columns?: 1 | 2 | 3;
  className?: string;
}) {
  const cols = { 1: "sm:grid-cols-1", 2: "sm:grid-cols-2", 3: "sm:grid-cols-2 lg:grid-cols-3" }[columns];
  return (
    <dl className={cn("grid grid-cols-1 gap-x-6 gap-y-4", cols, className)}>
      {fields.map((field) => (
        <div key={field.label} className="min-w-0">
          <dt className="type-label">{field.label}</dt>
          <dd className="mt-1 break-words text-sm font-medium">{field.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * The "why" box. Explainability is a judged feature, so the plain-English
 * sentence gets its own treatment wherever it appears.
 */
export function ExplanationNote({
  title = "Why this was flagged",
  children,
  className,
}: {
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("rounded-md border-l-[3px] border-primary bg-primary/[0.04] p-4", className)}>
      <p className="type-label text-primary">{title}</p>
      <div className="mt-1.5 text-sm leading-relaxed">{children}</div>
    </div>
  );
}

/**
 * Sub-tabs for a destination that holds more than one view — used where a role's
 * sidebar is capped at six items but the view still deserves its own page.
 */
export function SubTabs({ tabs, current }: { tabs: { href: string; label: string }[]; current: string }) {
  return (
    <nav className="flex flex-wrap gap-1 rounded-lg border border-border bg-card p-1 shadow-card">
      {tabs.map((tab) => {
        const active = tab.href === current;
        return (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm transition-colors",
              active ? "bg-primary font-medium text-primary-foreground" : "hover:bg-secondary",
            )}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
