"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { NavLink } from "@/components/nav-link";

/** Nav links scoped to the current institution segment; the "All
 * universities" link reaches the global landing chooser from any uni page. */
export function SiteNav() {
  const pathname = usePathname() ?? "/";
  const seg = pathname.split("/")[1] ?? "";
  const prefix = seg && seg !== "admin" ? `/${seg}` : "";
  if (!prefix) return null;
  return (
    <nav aria-label="Main" className="flex items-center gap-4 sm:gap-6 text-sm">
      <NavLink href={`${prefix}/`} label="Search" />
      <NavLink href={`${prefix}/author`} label="Authors" />
      <NavLink href={`${prefix}/publisher`} label="Publishers" />
      <NavLink href={`${prefix}/orgunit`} label="Faculties" />
      <NavLink href={`${prefix}/deals`} label="Deals" />
      <NavLink href={`${prefix}/about`} label="About" />
      <NavLink href="/" label="All universities" />
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
