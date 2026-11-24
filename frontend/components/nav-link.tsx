"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

/** Header nav link with an active-page indicator. */
export function NavLink({
  href,
  label,
  exact = false,
  alsoMatchPrefixes,
}: {
  href: string;
  label: string;
  exact?: boolean;
  alsoMatchPrefixes?: string[];
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
        // py-1.5 keeps the tap target at ≥24px (WCAG 2.5.8).
        "inline-flex items-center rounded-sm py-1.5 underline-offset-4 hover:text-white/80 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70",
        active ? "font-semibold text-white underline" : "text-white/85",
      )}
    >
      {label}
    </Link>
  );
}
