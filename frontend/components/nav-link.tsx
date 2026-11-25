"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

/** Header nav link with a bottom accent bar for the active section. Below the
 * `lg` breakpoint it is a full-width row of the menu drawer; from `lg` it sits
 * inline, where py-2 keeps the tap target generous while aligning with the
 * header baseline. */
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
        "relative flex min-h-11 w-full items-center rounded-[var(--radius)] px-3 py-2.5 text-base transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70 lg:inline-flex lg:min-h-0 lg:w-auto lg:rounded-sm lg:px-0 lg:py-2 lg:text-sm lg:hover:bg-transparent",
        active
          ? "bg-white/10 font-semibold text-white lg:bg-transparent lg:after:absolute lg:after:inset-x-0 lg:after:bottom-0 lg:after:h-0.5 lg:after:rounded-full lg:after:bg-[var(--primary)]"
          : "text-white/80",
        className,
      )}
    >
      {label}
    </Link>
  );
}
