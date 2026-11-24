"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

/** Header nav link with a bottom accent bar for the active section. */
export function NavLink({
  href,
  label,
  exact = false,
  alsoMatchPrefixes,
  className,
}: {
  href: string;
  label: string;
  exact?: boolean;
  alsoMatchPrefixes?: string[];
  className?: string;
}) {
  const pathname = usePathname() ?? "/";
  const cleanHref = href.length > 1 && href.endsWith("/") ? href.slice(0, -1) : href;
  const cleanPath =
    pathname.length > 1 && pathname.endsWith("/") ? pathname.slice(0, -1) : pathname;
  const active =
    href === "/"
      ? pathname === "/"
      : exact
        ? cleanPath === cleanHref ||
          Boolean(alsoMatchPrefixes?.some((p) => cleanPath.startsWith(p)))
        : cleanPath === cleanHref || cleanPath.startsWith(`${cleanHref}/`);
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        // py-2 keeps the tap target generous while aligning cleanly with the header baseline.
        "relative inline-flex items-center rounded-sm py-2 transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70",
        active
          ? "font-semibold text-white after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:rounded-full after:bg-[var(--primary)]"
          : "text-white/80",
        className,
      )}
    >
      {label}
    </Link>
  );
}
