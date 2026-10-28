"use client";

/**
 * One shell for every role.
 *
 *   ┌──────────┬────────────────────────────────────────┐
 *   │ sidebar  │ top bar: breadcrumb · role · switch    │
 *   │ (role's  ├────────────────────────────────────────┤
 *   │  pages)  │ page: header, KPIs, content            │
 *   └──────────┴────────────────────────────────────────┘
 *
 * Below md the sidebar becomes a drawer. The student portal is mobile-first and
 * gets a bottom tab bar instead, because that is where it will actually be used.
 */
import { ChevronRight, KeyRound, LogOut, Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { NAV, PORTAL_LABELS, SHORT_LABELS, activeItem } from "@/lib/nav";
import type { Role } from "@/lib/types";
import { cn } from "@/lib/utils";

function Wordmark() {
  return (
    <span className="flex items-center gap-2.5">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary text-xs font-bold tracking-tight text-primary-foreground">
        AP
      </span>
      <span className="min-w-0">
        <span className="block truncate text-sm font-semibold leading-tight">AICTE · APAAR</span>
        <span className="block truncate text-[11px] leading-tight text-muted-foreground">
          Student data portal
        </span>
      </span>
    </span>
  );
}

function SidebarNav({ role, pathname, onNavigate }: { role: Role; pathname: string; onNavigate?: () => void }) {
  const current = activeItem(role, pathname);
  return (
    <nav className="space-y-1" aria-label="Navigation">
      {NAV[role].map((item) => {
        const active = item === current;
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-start gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
              active
                ? "bg-primary font-medium text-primary-foreground"
                : "text-foreground hover:bg-secondary",
            )}
          >
            <Icon className="mt-0.5 h-4 w-4 shrink-0" />
            {/* Labels wrap rather than truncate — no page name is ever cut off. */}
            <span className="min-w-0 leading-snug">{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

function SyntheticBanner({ className }: { className?: string }) {
  return (
    <p
      className={cn(
        "rounded-md bg-amber-100 px-3 py-2 text-center text-[11px] font-medium leading-snug text-amber-900",
        className,
      )}
    >
      Prototype — all data is synthetic.
    </p>
  );
}

function TabStrip({
  tabs,
  pathname,
}: {
  tabs: { href: string; label: string }[];
  pathname: string;
}) {
  // The longest matching tab wins, so "/institution" does not also light up for /institution/seat-matrix.
  const best = tabs.reduce(
    (found, tab) =>
      (pathname === tab.href || pathname.startsWith(`${tab.href}/`)) && tab.href.length > found.length
        ? tab.href
        : found,
    "",
  );
  return (
    <div className="-mt-2 mb-6 flex gap-1 overflow-x-auto border-b border-border">
      {tabs.map((tab) => (
        <Link
          key={tab.href}
          href={tab.href}
          aria-current={tab.href === best ? "page" : undefined}
          className={cn(
            "whitespace-nowrap border-b-2 px-3 py-2 text-sm transition-colors",
            tab.href === best
              ? "border-primary font-medium text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          {tab.label}
        </Link>
      ))}
    </div>
  );
}

/** Top-right: who is signed in, where they work, and the way out. */
function UserMenu() {
  const { user, logout } = useAuth();
  const router = useRouter();
  const institution = useQuery({
    queryKey: ["institution-me"],
    queryFn: api.institutionMe,
    enabled: user?.role === "institution",
    staleTime: Infinity,
  });
  if (!user) return null;
  const organisation =
    user.role === "institution"
      ? institution.data?.name
      : user.role.startsWith("aicte")
        ? "All India Council for Technical Education"
        : undefined;
  return (
    <div className="flex shrink-0 items-center gap-3">
      <div className="hidden min-w-0 text-right sm:block">
        <p className="truncate text-sm font-medium leading-tight">{user.display_name}</p>
        {organisation && <p className="truncate text-[11px] leading-tight text-muted-foreground">{organisation}</p>}
      </div>
      <Button asChild variant="ghost" size="icon" aria-label="Change password" title="Change password">
        <Link href="/account/password">
          <KeyRound className="h-4 w-4" />
        </Link>
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={() => {
          logout();
          router.push("/login");
        }}
      >
        <LogOut className="h-3.5 w-3.5" />
        Sign out
      </Button>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const pathname = usePathname();
  const [drawerOpen, setDrawerOpen] = useState(false);

  // A route change should never leave the drawer hanging open behind the page.
  useEffect(() => setDrawerOpen(false), [pathname]);

  if (!user) return null;
  const role = user.role;
  const current = activeItem(role, pathname);
  const trail = [PORTAL_LABELS[role], ...(current ? [current.label] : [])];
  const isStudent = role === "student";

  return (
    <div className="min-h-screen bg-background">
      {/* ------------------------------------------------------------ sidebar */}
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-sidebar flex-col border-r border-border bg-card lg:flex">
        <div className="flex h-topbar items-center border-b border-border px-4">
          <Link href={NAV[role][0].href} className="min-w-0">
            <Wordmark />
          </Link>
        </div>
        <div className="flex-1 overflow-y-auto p-3">
          <p className="px-3 pb-2 type-label">{PORTAL_LABELS[role]}</p>
          <SidebarNav role={role} pathname={pathname} />
        </div>
        <div className="space-y-3 border-t border-border p-3">
          <SyntheticBanner />
        </div>
      </aside>

      {/* ------------------------------------------------- mobile nav drawer */}
      {drawerOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            className="absolute inset-0 bg-slate-900/40"
            onClick={() => setDrawerOpen(false)}
          />
          <div className="absolute inset-y-0 left-0 flex w-[17rem] max-w-[85vw] flex-col bg-card shadow-raised">
            <div className="flex h-topbar items-center justify-between gap-2 border-b border-border px-4">
              <Wordmark />
              <Button variant="ghost" size="icon" onClick={() => setDrawerOpen(false)} aria-label="Close">
                <X className="h-4 w-4" />
              </Button>
            </div>
            <div className="flex-1 overflow-y-auto p-3">
              <p className="px-3 pb-2 type-label">{PORTAL_LABELS[role]}</p>
              <SidebarNav role={role} pathname={pathname} onNavigate={() => setDrawerOpen(false)} />
            </div>
            <div className="space-y-3 border-t border-border p-3">
              <SyntheticBanner />
            </div>
          </div>
        </div>
      )}

      {/* --------------------------------------------------- top bar + page */}
      <div className="lg:pl-sidebar">
        <header className="sticky top-0 z-30 border-b border-border bg-card/95 backdrop-blur">
          <div className="flex h-topbar items-center gap-3 px-4 sm:px-6">
            <Button
              variant="ghost"
              size="icon"
              className="lg:hidden"
              onClick={() => setDrawerOpen(true)}
              aria-label="Open navigation"
            >
              <Menu className="h-5 w-5" />
            </Button>

            {/* Breadcrumb: the last crumb is the page title. */}
            <nav aria-label="Breadcrumb" className="min-w-0 flex-1">
              <ol className="flex min-w-0 items-center gap-1.5 text-sm">
                {trail.map((crumb, index) => {
                  const last = index === trail.length - 1;
                  return (
                    <li key={crumb} className={cn("flex min-w-0 items-center gap-1.5", !last && "hidden sm:flex")}>
                      {index > 0 && (
                        <ChevronRight className="hidden h-3.5 w-3.5 shrink-0 text-muted-foreground sm:block" />
                      )}
                      <span
                        className={cn(
                          "truncate",
                          last ? "font-semibold text-foreground" : "text-muted-foreground",
                        )}
                      >
                        {crumb}
                      </span>
                    </li>
                  );
                })}
              </ol>
            </nav>

            <UserMenu />
          </div>
        </header>

        <main
          className={cn(
            "mx-auto w-full max-w-content px-4 py-6 sm:px-6 lg:py-8",
            // Room for the student's bottom tab bar.
            isStudent && "pb-24 md:pb-8",
          )}
        >
          {current?.children && <TabStrip tabs={current.children} pathname={pathname} />}
          <div className="space-y-6">{children}</div>
        </main>
      </div>

      {/* ------------------------------------------- student bottom tab bar */}
      {isStudent && (
        <nav
          aria-label="Student navigation"
          className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-4 border-t border-border bg-card pb-[env(safe-area-inset-bottom)] md:hidden"
        >
          {NAV[role].map((item) => {
            const active = item === activeItem(role, pathname);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex flex-col items-center gap-1 px-1 py-2.5 text-[10px] leading-tight transition-colors",
                  active ? "text-primary" : "text-muted-foreground",
                )}
              >
                <Icon className="h-5 w-5" />
                <span className="text-center">{SHORT_LABELS[item.href] ?? item.label}</span>
              </Link>
            );
          })}
        </nav>
      )}
    </div>
  );
}
