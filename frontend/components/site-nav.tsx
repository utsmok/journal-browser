"use client";

import { ChevronDown } from "lucide-react";
import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { NavLink } from "@/components/nav-link";
import { useInstitutionsDirectory } from "@/hooks/use-api";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { instFromSegment } from "@/lib/global-segments";
import { cn } from "@/lib/utils";

const menuItem =
  "block rounded-[calc(var(--radius)-2px)] px-3 text-left transition-colors hover:bg-[var(--muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]";

/** Dropdown menu for broad bibliometric / research-intelligence views
 * (currently Collaboration partners, with room for future explorer modules).
 * Below the `lg` breakpoint it collapses into a plain drawer row: the menu has
 * one destination, so a second tap adds nothing. */
function DataExplorerMenu({ prefix }: { prefix: string }) {
  const t = useTranslations("common");
  const pathname = usePathname() ?? "/";
  const [open, setOpen] = React.useState(false);
  const containerRef = React.useRef<HTMLDivElement>(null);

  const partnersHref = `${prefix}/collaborations`;
  const active = pathname.startsWith(partnersHref);

  React.useEffect(() => {
    setOpen(false);
  }, [pathname]);

  React.useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={containerRef} className="relative">
      <NavLink href={partnersHref} label={t("nav.dataExplorerPartners")} className="lg:hidden" />
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "relative hidden items-center gap-1 rounded-sm py-2 transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70 lg:inline-flex",
          active
            ? "font-semibold text-white after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:rounded-full after:bg-[var(--primary)]"
            : "text-white/80",
        )}
      >
        {t("nav.dataExplorer")}
        <ChevronDown
          aria-hidden
          className={cn("size-3.5 transition-transform", open && "rotate-180")}
        />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute left-0 top-full z-50 mt-1.5 w-64 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-1.5 text-[var(--card-foreground)] shadow-lg"
        >
          <Link
            role="menuitem"
            href={partnersHref}
            onClick={() => setOpen(false)}
            className={cn(menuItem, "py-2", active && "bg-[var(--muted)]")}
          >
            <span className="block text-sm font-medium text-[var(--foreground)]">
              {t("nav.dataExplorerPartners")}
            </span>
            <span className="block whitespace-normal text-xs text-[var(--muted-foreground)]">
              {t("nav.dataExplorerPartnersDesc")}
            </span>
          </Link>
        </div>
      )}
    </div>
  );
}

/** Nav links scoped to the current institution segment. From the `lg`
 * breakpoint they sit in the header bar; below it they are rows of the menu
 * drawer. Without an institution segment (chooser, /data-pipeline) the nav
 * stays minimal instead of disappearing. */
export function SiteNav() {
  const t = useTranslations("common");
  const pathname = usePathname() ?? "/";
  const seg = pathname.split("/")[1] ?? "";
  const inst = instFromSegment(seg);
  const prefix = inst && `/${inst}`;
  if (!prefix) {
    if (pathname === "/") return null;
    return (
      <nav aria-label={t("nav.mainLabel")} className="w-full text-sm lg:w-auto">
        <div className="flex flex-col lg:flex-row lg:flex-wrap lg:items-center lg:gap-x-6">
          <NavLink href="/" label={t("nav.allUniversities")} />
        </div>
      </nav>
    );
  }
  return (
    <nav aria-label={t("nav.mainLabel")} className="w-full whitespace-nowrap text-sm lg:w-auto">
      <div className="flex flex-col lg:flex-row lg:flex-wrap lg:items-center lg:gap-x-5">
        <NavLink
          href={`${prefix}/`}
          label={t("nav.search")}
          exact
          alsoMatchPrefixes={[`${prefix}/guide`, `${prefix}/journals`]}
        />
        <NavLink href={`${prefix}/publisher`} label={t("nav.publishers")} />
        <NavLink href={`${prefix}/orgunit`} label={t("nav.faculties")} />
        <NavLink href={`${prefix}/author`} label={t("nav.authors")} />
        <NavLink href={`${prefix}/funders`} label={t("nav.funders")} />
        <NavLink href={`${prefix}/deals`} label={t("nav.deals")} />
        <DataExplorerMenu prefix={prefix} />
      </div>
    </nav>
  );
}

/** Utility link to About for the active institution. */
export function AboutUtilityLink() {
  const t = useTranslations("common");
  const pathname = usePathname() ?? "/";
  const seg = pathname.split("/")[1] ?? "";
  const inst = instFromSegment(seg);
  if (!inst) return null;
  return <NavLink href={`/${inst}/about`} label={t("nav.about")} />;
}

/** Compact university switcher pill next to the logo; replaces the top-nav
 * "All universities" link and makes the active institution unmistakable. */
function InstitutionSwitcher({ inst }: { inst: string }) {
  const t = useTranslations("common");
  const site = useSiteMeta();
  const directory = useInstitutionsDirectory();
  const [open, setOpen] = React.useState(false);
  const containerRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    setOpen(false);
  }, [inst]);

  React.useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const label = site.short || inst.toUpperCase();
  const entries = directory.data ?? [];

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={`${t("nav.switchInstitution")} (${label})`}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex min-h-11 items-center gap-1 rounded-full border border-white/25 bg-white/10 px-2.5 text-xs font-semibold text-white transition-colors hover:bg-white/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70 lg:min-h-0 lg:py-0.5"
      >
        <span>{label}</span>
        <ChevronDown
          aria-hidden
          className={cn("size-3 transition-transform", open && "rotate-180")}
        />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-1.5 w-60 max-w-[calc(100vw-2rem)] rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-1.5 text-[var(--card-foreground)] shadow-lg sm:left-0 sm:right-auto"
        >
          {entries.map((entry) => (
            <Link
              key={entry.code}
              role="menuitem"
              href={`/${entry.code}/`}
              onClick={() => setOpen(false)}
              className={cn(
                menuItem,
                "flex min-h-11 items-center justify-between gap-2 text-xs lg:min-h-0 lg:py-1.5",
                entry.code === inst && "bg-[var(--muted)] font-semibold",
              )}
            >
              <span className="truncate text-[var(--foreground)]">{entry.name}</span>
              <span className="shrink-0 uppercase text-[var(--muted-foreground)]">
                {entry.short_name || entry.code}
              </span>
            </Link>
          ))}
          {entries.length > 0 && <div className="my-1 border-t border-[var(--border)]" />}
          <Link
            role="menuitem"
            href="/"
            onClick={() => setOpen(false)}
            className={cn(
              menuItem,
              "flex min-h-11 items-center text-xs font-medium text-[var(--primary-text)] lg:min-h-0 lg:py-1.5",
            )}
          >
            {t("nav.allUniversities")}
          </Link>
        </div>
      )}
    </div>
  );
}

/** Brand link + optional institution pill: back to the scoped search page (or chooser). */
export function BrandLink() {
  const t = useTranslations("common");
  const pathname = usePathname() ?? "/";
  const seg = pathname.split("/")[1] ?? "";
  const inst = instFromSegment(seg);
  const prefix = inst ? `/${inst}` : "";
  return (
    <div className="flex items-center gap-2.5 whitespace-nowrap">
      <Link
        href={`${prefix}/`}
        aria-label={t("appTitle")}
        className="flex min-h-11 items-center whitespace-nowrap lg:min-h-0"
      >
        {/* The header bar is dark in both themes, so its wordmark is a static
            file; only the landing hero needs the theme-aware inline copy. */}
        <Image
          src="/ojb-wordmark-header.svg"
          alt=""
          width={972}
          height={542}
          priority
          className="h-10 w-auto"
        />
      </Link>
      {inst && (
        <>
          <span aria-hidden className="hidden h-5 w-px bg-white/20 sm:inline-block" />
          <InstitutionSwitcher inst={inst} />
        </>
      )}
    </div>
  );
}
