"use client";

/** The portal frame: per-role sidebar, role badge, and the synthetic-data banner. */
import {
  BadgeCheck,
  Building2,
  CircleUser,
  ClipboardList,
  Download,
  FileSpreadsheet,
  Flag,
  Gauge,
  GraduationCap,
  IdCard,
  LayoutDashboard,
  LineChart,
  ListChecks,
  LogOut,
  Network,
  ScrollText,
  Settings,
  ShieldCheck,
  Table2,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { RoleSwitcher } from "@/components/RoleSwitcher";
import { Button } from "@/components/ui/primitives";
import { useAuth } from "@/lib/auth";
import type { Role } from "@/lib/types";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: ReactNode;
}

const NAV: Record<Role, NavItem[]> = {
  institution: [
    { href: "/institution", label: "Dashboard", icon: <LayoutDashboard className="h-4 w-4" /> },
    { href: "/institution/upload", label: "Upload data", icon: <FileSpreadsheet className="h-4 w-4" /> },
    { href: "/institution/seat-matrix", label: "Seat matrix", icon: <Table2 className="h-4 w-4" /> },
    { href: "/institution/flags", label: "Flag inbox", icon: <Flag className="h-4 w-4" /> },
    { href: "/institution/students", label: "Students", icon: <Users className="h-4 w-4" /> },
    { href: "/institution/uploads", label: "Upload history", icon: <ClipboardList className="h-4 w-4" /> },
    { href: "/institution/certificate", label: "Compliance", icon: <BadgeCheck className="h-4 w-4" /> },
  ],
  aicte_officer: [
    { href: "/aicte", label: "National overview", icon: <LayoutDashboard className="h-4 w-4" /> },
    { href: "/aicte/flags", label: "Flag queue", icon: <Flag className="h-4 w-4" /> },
    { href: "/aicte/clusters", label: "Ghost clusters", icon: <Network className="h-4 w-4" /> },
    { href: "/aicte/institutions", label: "Institutions", icon: <Building2 className="h-4 w-4" /> },
    { href: "/aicte/risk", label: "Risk leaderboard", icon: <Gauge className="h-4 w-4" /> },
    { href: "/aicte/shortlist", label: "Inspection shortlist", icon: <ListChecks className="h-4 w-4" /> },
    { href: "/aicte/non-reporting", label: "Non-reporting", icon: <ScrollText className="h-4 w-4" /> },
    { href: "/aicte/reports", label: "Reports", icon: <LineChart className="h-4 w-4" /> },
  ],
  aicte_viewer: [
    { href: "/aicte", label: "National overview", icon: <LayoutDashboard className="h-4 w-4" /> },
    { href: "/aicte/flags", label: "Flag queue", icon: <Flag className="h-4 w-4" /> },
    { href: "/aicte/clusters", label: "Ghost clusters", icon: <Network className="h-4 w-4" /> },
    { href: "/aicte/institutions", label: "Institutions", icon: <Building2 className="h-4 w-4" /> },
    { href: "/aicte/risk", label: "Risk leaderboard", icon: <Gauge className="h-4 w-4" /> },
    { href: "/aicte/shortlist", label: "Inspection shortlist", icon: <ListChecks className="h-4 w-4" /> },
    { href: "/aicte/non-reporting", label: "Non-reporting", icon: <ScrollText className="h-4 w-4" /> },
    { href: "/aicte/reports", label: "Reports", icon: <LineChart className="h-4 w-4" /> },
  ],
  student: [
    { href: "/student", label: "My dashboard", icon: <LayoutDashboard className="h-4 w-4" /> },
    { href: "/student/records", label: "My records", icon: <GraduationCap className="h-4 w-4" /> },
    { href: "/student/access-log", label: "Who accessed my data", icon: <ShieldCheck className="h-4 w-4" /> },
    { href: "/student/consents", label: "Consent manager", icon: <ListChecks className="h-4 w-4" /> },
    { href: "/student/id-card", label: "Digital ID card", icon: <IdCard className="h-4 w-4" /> },
  ],
  verifier: [
    { href: "/verifier", label: "Verify a student", icon: <BadgeCheck className="h-4 w-4" /> },
    { href: "/verifier/requests", label: "My requests", icon: <ClipboardList className="h-4 w-4" /> },
    { href: "/verify", label: "Check a QR / token", icon: <ShieldCheck className="h-4 w-4" /> },
  ],
  admin: [
    { href: "/admin", label: "Demo controls", icon: <Settings className="h-4 w-4" /> },
  ],
};

const ROLE_LABELS: Record<Role, string> = {
  institution: "Institution",
  aicte_officer: "AICTE Officer",
  aicte_viewer: "AICTE Analyst",
  student: "Student",
  verifier: "Verifier",
  admin: "Admin",
};

const ROLE_TONES: Record<Role, string> = {
  institution: "bg-sky-100 text-sky-900",
  aicte_officer: "bg-indigo-100 text-indigo-900",
  aicte_viewer: "bg-violet-100 text-violet-900",
  student: "bg-emerald-100 text-emerald-900",
  verifier: "bg-amber-100 text-amber-900",
  admin: "bg-slate-200 text-slate-900",
};

export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const items = user ? NAV[user.role] : [];

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-30 border-b border-border bg-card/95 backdrop-blur">
        <div className="flex h-14 items-center gap-3 px-4">
          <Link href={user ? NAV[user.role][0].href : "/login"} className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded bg-primary text-xs font-bold text-primary-foreground">
              AP
            </span>
            <span className="hidden text-sm font-semibold sm:inline">APAAR Platform</span>
          </Link>

          <span className="hidden text-xs text-muted-foreground lg:inline">
            Student data &amp; verification · AICTE
          </span>

          <div className="ml-auto flex items-center gap-2">
            {user && (
              <span
                className={cn(
                  "hidden items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium sm:inline-flex",
                  ROLE_TONES[user.role],
                )}
              >
                <CircleUser className="h-3.5 w-3.5" />
                {ROLE_LABELS[user.role]}
              </span>
            )}
            <RoleSwitcher />
            {user && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  logout();
                  router.push("/login");
                }}
              >
                <LogOut className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Sign out</span>
              </Button>
            )}
          </div>
        </div>
        <p className="bg-amber-100 px-4 py-1 text-center text-xs font-medium text-amber-900">
          Prototype — all data is synthetic.
        </p>
      </header>

      <div className="flex">
        <aside className="hidden w-60 shrink-0 border-r border-border bg-card/60 md:block">
          <nav className="sticky top-[88px] space-y-0.5 p-3">
            {user && (
              <p className="px-2 pb-2 text-xs text-muted-foreground" title={user.username}>
                {user.display_name}
              </p>
            )}
            {items.map((item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "flex items-center gap-2 rounded-md px-2.5 py-2 text-sm transition-colors",
                    active
                      ? "bg-primary text-primary-foreground"
                      : "text-foreground hover:bg-muted",
                  )}
                >
                  {item.icon}
                  <span className="truncate">{item.label}</span>
                </Link>
              );
            })}
          </nav>
        </aside>

        <main className="min-w-0 flex-1 px-4 py-6 md:px-6">
          {/* Mobile / tablet navigation */}
          <nav className="mb-4 flex gap-1.5 overflow-x-auto pb-1 md:hidden">
            {items.map((item) => {
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "whitespace-nowrap rounded-full border px-3 py-1.5 text-xs",
                    active
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-card",
                  )}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
          {children}
        </main>
      </div>
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export { Download };
