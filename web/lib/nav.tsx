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
  FileSearch,
  FileSpreadsheet,
  Flag,
  GraduationCap,
  Home,
  IdCard,
  LayoutDashboard,
  LineChart,
  ListChecks,
  ScrollText,
  Settings2,
  ShieldCheck,
  Table2,
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
}

export const NAV: Record<Role, NavItem[]> = {
  institution: [
    { href: "/institution", label: "Dashboard", icon: LayoutDashboard },
    { href: "/institution/upload", label: "Upload data", icon: FileSpreadsheet, owns: ["/institution/uploads"] },
    { href: "/institution/students", label: "Students", icon: Users },
    { href: "/institution/seat-matrix", label: "Seat matrix", icon: Table2 },
    { href: "/institution/flags", label: "Flags", icon: Flag },
  ],
  aicte_officer: [
    { href: "/aicte", label: "Overview", icon: LayoutDashboard },
    { href: "/aicte/flags", label: "Flag queue", icon: Flag },
    { href: "/aicte/institutions", label: "Institutions", icon: Building2 },
    { href: "/aicte/reports", label: "Reports", icon: LineChart },
  ],
  aicte_viewer: [
    { href: "/aicte", label: "Overview", icon: LayoutDashboard },
    { href: "/aicte/institutions", label: "Institutions", icon: Building2 },
    { href: "/aicte/reports", label: "Reports", icon: LineChart },
  ],
  student: [
    { href: "/student", label: "Home", icon: Home },
    { href: "/student/records", label: "My records", icon: GraduationCap },
    { href: "/student/access-log", label: "Who accessed my data", icon: FileSearch },
    { href: "/student/consents", label: "Consents", icon: ShieldCheck },
    { href: "/student/id-card", label: "ID card", icon: IdCard },
  ],
  verifier: [
    { href: "/verifier", label: "New request", icon: BadgeCheck },
    { href: "/verifier/requests", label: "My requests", icon: ListChecks },
    { href: "/verify", label: "Verify a QR", icon: ShieldCheck },
  ],
  admin: [
    { href: "/admin", label: "Demo controls", icon: Settings2 },
    { href: "/admin/audit", label: "Audit log", icon: ScrollText },
  ],
};

/** Short names for the student's bottom tab bar, where space is tightest. */
export const SHORT_LABELS: Record<string, string> = {
  "/student": "Home",
  "/student/records": "Records",
  "/student/access-log": "Access",
  "/student/consents": "Consents",
  "/student/id-card": "ID card",
};

export const ROLE_LABELS: Record<Role, string> = {
  institution: "Institution",
  aicte_officer: "AICTE Officer",
  aicte_viewer: "AICTE Analyst",
  student: "Student",
  verifier: "Verifier",
  admin: "Admin",
};

/** The portal each role sees, used as the first breadcrumb. */
export const PORTAL_LABELS: Record<Role, string> = {
  institution: "Institution portal",
  aicte_officer: "AICTE monitoring",
  aicte_viewer: "AICTE monitoring",
  student: "My APAAR",
  verifier: "Verification",
  admin: "Demo operations",
};

export const ROLE_BLURBS: Record<Role, string> = {
  institution: "Upload your student data and answer findings about it.",
  aicte_officer: "Investigate findings, reveal with a reason, manage cases.",
  aicte_viewer: "Aggregates and masked rows, with small counts suppressed.",
  student: "See what was reported about you and control who may verify it.",
  verifier: "Ask a student to confirm an enrolment — with their consent.",
  admin: "Reseed the demo and check the audit chain.",
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
];
