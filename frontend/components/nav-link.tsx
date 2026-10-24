"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

/** Header nav link with an active-page indicator. */
export function NavLink({ href, label }: { href: string; label: string }) {
  const pathname = usePathname();
  const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
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
