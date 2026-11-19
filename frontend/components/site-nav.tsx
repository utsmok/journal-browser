"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

import { OjbWordmark } from "@/components/logo";
import { NavLink } from "@/components/nav-link";
import { instFromSegment } from "@/lib/global-segments";

/** Nav links scoped to the current institution segment; the "All
 * universities" link reaches the global landing chooser from any uni page.
 * Without an institution segment (chooser, /data-pipeline) the nav stays
 * minimal instead of disappearing: links wrap on phones rather than
 * truncating in a scrollbar-hidden row. */
export function SiteNav() {
  const t = useTranslations("common");
  const pathname = usePathname() ?? "/";
  const seg = pathname.split("/")[1] ?? "";
  const inst = instFromSegment(seg);
  const prefix = inst && `/${inst}`;
  if (!prefix) {
    // The chooser is the nav target itself; other global pages (such as
    // /data-pipeline) keep one visible way back.
    if (pathname === "/") return null;
    return (
      <nav
        aria-label={t("nav.mainLabel")}
        className="order-last w-full text-sm sm:order-none sm:w-auto"
      >
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 sm:gap-x-6">
          <NavLink href="/" label={t("nav.allUniversities")} />
        </div>
      </nav>
    );
  }
  return (
    <nav
      aria-label={t("nav.mainLabel")}
      className="order-last w-full whitespace-nowrap text-sm sm:order-none sm:w-auto"
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 sm:gap-x-6">
        <NavLink href={`${prefix}/`} label={t("nav.search")} />
        <NavLink href={`${prefix}/deals`} label={t("nav.deals")} />
        <NavLink href={`${prefix}/funders`} label={t("nav.funders")} />
        <NavLink href={`${prefix}/publisher`} label={t("nav.publishers")} />
        <NavLink href={`${prefix}/author`} label={t("nav.authors")} />
        <NavLink href={`${prefix}/orgunit`} label={t("nav.faculties")} />
        <NavLink href={`${prefix}/about`} label={t("nav.about")} />
        <NavLink href="/" label={t("nav.allUniversities")} />
      </div>
    </nav>
  );
}

/** Brand link: back to the scoped search page (or the chooser). */
export function BrandLink() {
  const t = useTranslations("common");
  const pathname = usePathname() ?? "/";
  const seg = pathname.split("/")[1] ?? "";
  const prefix = instFromSegment(seg) && `/${instFromSegment(seg)}`;
  return (
    <Link
      href={`${prefix}/`}
      aria-label={t("appTitle")}
      className="flex items-center whitespace-nowrap"
    >
      <OjbWordmark className="h-11 w-auto" />
    </Link>
  );
}
