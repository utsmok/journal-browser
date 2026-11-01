"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const NAV_GROUPS: { label: string; items: { href: string; label: string }[] }[] = [
  { label: "Overview", items: [{ href: "/admin", label: "Dashboard" }] },
  {
    label: "Data",
    items: [
      { href: "/admin/runs", label: "Harvest runs" },
      { href: "/admin/deals", label: "Deals" },
      { href: "/admin/identities", label: "Author identities" },
      { href: "/admin/work-identities", label: "Work identities" },
    ],
  },
  {
    label: "Operations",
    items: [
      { href: "/admin/feedback", label: "Feedback" },
      { href: "/admin/audit", label: "Audit log" },
    ],
  },
  {
    label: "Configuration",
    items: [
      { href: "/admin/institutions", label: "Institution settings" },
      { href: "/admin/settings", label: "Global settings" },
    ],
  },
];

function NavLink({ href, label, className }: { href: string; label: string; className?: string }) {
  const pathname = usePathname();
  const active = href === "/admin" ? pathname === "/admin" : pathname.startsWith(href);
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "block rounded-[var(--radius)] px-2 py-1.5 text-sm transition-colors",
        active
          ? "bg-[var(--secondary)] font-medium text-[var(--secondary-foreground)]"
          : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]",
        className,
      )}
    >
      {label}
    </Link>
  );
}

/**
 * Chrome for the admin section: grouped navigation with an active state,
 * desktop sidebar, horizontally scrolling top nav on small screens, and the
 * sign-out affordance. The login gate lives in app/admin/layout.tsx.
 */
export function AdminShell({
  onSignOut,
  children,
}: {
  onSignOut: () => void;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen lg:flex">
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r bg-[var(--card)] px-3 py-4 lg:flex">
        <Link href="/" className="mb-4 block px-2 text-sm font-semibold hover:underline">
          Journal admin
        </Link>
        <nav aria-label="Admin" className="flex-1 space-y-5 overflow-y-auto">
          {NAV_GROUPS.map((group) => (
            <div key={group.label}>
              <p className="px-2 pb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                {group.label}
              </p>
              <div className="space-y-0.5">
                {group.items.map((item) => (
                  <NavLink key={item.href} href={item.href} label={item.label} />
                ))}
              </div>
            </div>
          ))}
        </nav>
        <Button variant="outline" size="sm" className="mt-4 w-full" onClick={onSignOut}>
          Sign out
        </Button>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="border-b lg:hidden">
          <div className="flex items-center justify-between px-4 pt-3">
            <Link href="/" className="text-sm font-semibold">
              Journal admin
            </Link>
            <Button variant="outline" size="sm" onClick={onSignOut}>
              Sign out
            </Button>
          </div>
          <nav aria-label="Admin" className="flex gap-1 overflow-x-auto px-2 py-2">
            {NAV_GROUPS.flatMap((group) => group.items).map((item) => (
              <NavLink
                key={item.href}
                href={item.href}
                label={item.label}
                className="whitespace-nowrap"
              />
            ))}
          </nav>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 lg:px-8">{children}</main>
      </div>
    </div>
  );
}

/** Page title plus an optional lede, with right-aligned actions. */
export function PageHeader({
  title,
  lede,
  children,
}: {
  title: string;
  lede?: string;
  children?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold">{title}</h1>
        {lede && <p className="mt-1 text-sm text-[var(--muted-foreground)]">{lede}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}
