"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

import { OjbWordmark } from "@/components/logo";
import { NavLink } from "@/components/nav-link";

/** Nav links scoped to the current institution segment; the "All
 * universities" link reaches the global landing chooser from any uni page. */
export function SiteNav() {
  const t = useTranslations("common");
  const pathname = usePathname() ?? "/";
  const seg = pathname.split("/")[1] ?? "";
  const prefix = seg && seg !== "admin" ? `/${seg}` : "";
  if (!prefix) return null;
  return (
    <nav
      aria-label={t("nav.mainLabel")}
      className="order-last w-full whitespace-nowrap text-sm sm:order-none sm:w-auto"
    >
      <div className="flex items-center gap-4 overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden sm:gap-6 sm:overflow-visible sm:pb-0">
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
  const prefix = seg && seg !== "admin" ? `/${seg}` : "";
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
