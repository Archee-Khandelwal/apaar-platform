"use client";

/**
 * One navigation map for the whole app.
 *
 * Each role gets at most six destinations — anything rarer lives as a section or a
 * sub-tab inside one of them, so the sidebar never becomes a list of everything.
 */
import {
  BadgeCheck,
  Building2,
  FileCheck2,
  FileSearch,
  FileSpreadsheet,
  Flag,
  GraduationCap,
  IdCard,
  LayoutDashboard,
  ListChecks,
  Scale,
  ScrollText,
  ShieldCheck,
  Users,
} from "lucide-react";
import type { ComponentType } from "react";

import type { Role } from "./types";

export interface NavItem {
  href: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  /** Extra path prefixes that should light this item up, e.g. detail pages. */
  owns?: string[];
  /** Sibling pages shown as a tab strip inside this destination. */
  children?: { href: string; label: string; owns?: string[] }[];
}

const AICTE_OVERVIEW: NavItem = {
  href: "/aicte",
  label: "Overview",
  icon: LayoutDashboard,
  children: [
    { href: "/aicte", label: "Overview" },
    { href: "/aicte/retrieve", label: "Retrieve data" },
    { href: "/aicte/reports", label: "Reports" },
  ],
};
const AICTE_RECON: NavItem = { href: "/aicte/reconciliation", label: "Reconciliation", icon: Scale };
const AICTE_INSTITUTIONS: NavItem = { href: "/aicte/institutions", label: "Institutions", icon: Building2 };

export const NAV: Record<Role, NavItem[]> = {
  institution: [
    {
      href: "/institution",
      label: "Dashboard",
      icon: LayoutDashboard,
      children: [
        { href: "/institution", label: "Overview" },
        { href: "/institution/seat-matrix", label: "Seat matrix" },
      ],
    },
    { href: "/institution/upload", label: "Upload data", icon: FileSpreadsheet, owns: ["/institution/uploads"] },
    {
      href: "/institution/students",
      label: "Students",
      icon: Users,
      owns: ["/institution/documents"],
      children: [
        { href: "/institution/students", label: "Students" },
        { href: "/institution/documents", label: "Documents" },
      ],
    },
    {
      href: "/institution/reconciliation",
      label: "Reconciliation",
      icon: Scale,
      owns: ["/institution/flags"],
      children: [
        { href: "/institution/reconciliation", label: "Reconciliation" },
        { href: "/institution/flags", label: "Findings" },
      ],
    },
    { href: "/institution/certificates", label: "Degree certificates", icon: BadgeCheck },
    {
      href: "/institution/verify",
      label: "Verify a student",
      icon: ShieldCheck,
      children: [
        { href: "/institution/verify", label: "Verify a student" },
        { href: "/institution/verify/requests", label: "My requests" },
      ],
    },
  ],
  aicte_officer: [
    AICTE_OVERVIEW,
    { href: "/aicte/flags", label: "Flag queue", icon: Flag },
    { href: "/aicte/documents", label: "Document review", icon: FileCheck2 },
    AICTE_RECON,
    AICTE_INSTITUTIONS,
    { href: "/aicte/audit", label: "Audit log", icon: ScrollText },
  ],
  aicte_viewer: [AICTE_OVERVIEW, AICTE_RECON, AICTE_INSTITUTIONS],
  verifier: [
    { href: "/verifier", label: "Verify a student", icon: ShieldCheck },
    { href: "/verifier/requests", label: "My requests", icon: ListChecks },
  ],
  student: [
    { href: "/student/records", label: "My records", icon: GraduationCap },
    { href: "/student/consents", label: "Consent requests", icon: ShieldCheck },
    { href: "/student/access-log", label: "Who accessed my data", icon: FileSearch },
    { href: "/student/id-card", label: "Certificates & ID", icon: IdCard },
  ],
  // Admin has no portal: reset and reseed are CLI commands (scripts/tasks.py).
  admin: [],
};

/** Short names for the student's bottom tab bar, where space is tightest. */
export const SHORT_LABELS: Record<string, string> = {
  "/student/records": "Records",
  "/student/access-log": "Access",
  "/student/consents": "Consents",
  "/student/id-card": "Certificates",
};

/** The portal each role sees, used as the first breadcrumb. */
export const PORTAL_LABELS: Record<Role, string> = {
  institution: "Institution portal",
  aicte_officer: "AICTE portal",
  aicte_viewer: "AICTE portal",
  student: "Student portal",
  verifier: "Employer / Regulator portal",
  admin: "",
};

/** How well an item matches a path: the length of the matching prefix, or 0. */
function matchLength(item: NavItem, pathname: string): number {
  const paths = [item.href, ...(item.owns ?? [])];
  return paths.reduce((best, path) => {
    const hit = pathname === path || pathname.startsWith(`${path}/`);
    return hit ? Math.max(best, path.length) : best;
  }, 0);
}

/**
 * The one nav item a path belongs to. "/aicte" and "/aicte/institutions" both match
 * /aicte/institutions/1, so the longest match wins and only one item lights up.
 */
export function activeItem(role: Role, pathname: string): NavItem | undefined {
  let best: NavItem | undefined;
  let bestLength = 0;
  for (const item of NAV[role]) {
    const length = matchLength(item, pathname);
    if (length > bestLength) {
      best = item;
      bestLength = length;
    }
  }
  return best;
}

/** The crumb trail for the top bar: portal, then the current destination. */
export function breadcrumb(role: Role, pathname: string): string[] {
  const item = activeItem(role, pathname);
  const trail = [PORTAL_LABELS[role]];
  if (item) trail.push(item.label);
  // Sub-pages add a third crumb so the reader knows where they drilled in.
  if (item && pathname !== item.href) {
    const detail = DETAIL_CRUMBS.find(([prefix]) => pathname.startsWith(prefix));
    if (detail) trail.push(detail[1]);
  }
  return trail;
}

const DETAIL_CRUMBS: [string, string][] = [
  ["/aicte/institutions/", "Institution profile"],
  ["/institution/uploads", "Upload history"],
  ["/institution/documents/", "Student checklist"],
  ["/aicte/documents/", "Case"],
  ["/aicte/reconciliation/institution/", "Institution students"],
  ["/aicte/reconciliation/record/", "Record"],
];
