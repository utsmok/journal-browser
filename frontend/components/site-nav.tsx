"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { NavLink } from "@/components/nav-link";

/** Nav links scoped to the current institution segment ("" on global pages). */
export function SiteNav() {
  const pathname = usePathname() ?? "/";
  const seg = pathname.split("/")[1] ?? "";
  // Global surfaces (admin, landing) carry no institution segment.
  const prefix = seg && seg !== "admin" ? `/${seg}` : "";
  return (
    <nav aria-label="Main" className="flex items-center gap-4 sm:gap-6 text-sm">
      <NavLink href={`${prefix}/`} label="Search" />
      <NavLink href={`${prefix}/deals`} label="Deals" />
      <NavLink href={`${prefix}/about`} label="About" />
    </nav>
  );
}

/** Brand link: back to the scoped search page (or the chooser). */
export function BrandLink() {
  const pathname = usePathname() ?? "/";
  const seg = pathname.split("/")[1] ?? "";
  const prefix = seg && seg !== "admin" ? `/${seg}` : "";
  return (
    <Link
      href={`${prefix}/`}
      className="font-heading whitespace-nowrap text-base sm:text-lg font-bold tracking-tight"
    >
      Journal Browser
    </Link>
  );
}
