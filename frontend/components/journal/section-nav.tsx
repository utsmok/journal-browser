"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import * as React from "react";

import { useInstitution } from "@/hooks/use-institution";
import { cn } from "@/lib/utils";

/** Store the latest directory URL + query string in sessionStorage so
 * sibling detail pages can return without losing active filters/facets. */
export function rememberDirectoryUrl(storageKey: string, url: string | null) {
  try {
    if (!url) sessionStorage.removeItem(storageKey);
    else sessionStorage.setItem(storageKey, url);
  } catch {
    // ignore storage errors in private browsing / SSR
  }
}

/** href for returning to the last viewed directory list in this tab,
 * falling back to `fallback`. */
export function useLastDirectoryHref(storageKey: string, fallback: string): string {
  const [href, setHref] = React.useState(fallback);
  React.useEffect(() => {
    try {
      setHref(sessionStorage.getItem(storageKey) ?? fallback);
    } catch {
      setHref(fallback);
    }
  }, [storageKey, fallback]);
  return href;
}

/** href for "Back to search": the last search this tab ran, else this
 * university's search home (never the global landing). */
export function useLastSearchHref(): string {
  const inst = useInstitution();
  return useLastDirectoryHref("jb-last-search", `/${inst}/`);
}

/** Highlight the id of the topmost section currently in view. */
export function useSectionSpy(ids: string[]) {
  const [active, setActive] = React.useState<string | null>(null);
  const key = ids.join(",");
  React.useEffect(() => {
    const els = key
      .split(",")
      .map((id) => document.getElementById(id))
      .filter((el): el is HTMLElement => el !== null);
    if (els.length === 0) return;
    const visible = new Set<Element>();
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) visible.add(entry.target);
          else visible.delete(entry.target);
        }
        // Topmost visible section wins; keep the last one across gaps.
        const top = [...visible].sort(
          (a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top,
        )[0];
        if (top) setActive(top.id);
      },
      // Only the band just below the sticky bar counts as "in view".
      { rootMargin: "-56px 0px -55% 0px" },
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [key]);
  return active;
}

export function SectionNav({
  sections,
  backHref: explicitBackHref,
  backFallback,
  backStorageKey = "jb-last-search",
  backLabel,
}: {
  sections: { id: string; label: string; hint?: string }[];
  backHref?: string;
  backFallback?: string;
  backStorageKey?: string;
  backLabel?: string;
}) {
  const active = useSectionSpy(sections.map((s) => s.id));
  const t = useTranslations("journals");
  const inst = useInstitution();
  // Muted-foreground/primary-text both fail 4.5:1 on the navy bar, so this
  // nav speaks in white and separates the active item with weight+underline.
  const storedBackHref = useLastDirectoryHref(backStorageKey, backFallback ?? `/${inst}/`);
  const backHref = explicitBackHref ?? storedBackHref;
  const resolvedBackLabel = backLabel ?? t("nav.backToSearch");
  return (
    <nav
      aria-label={t("nav.sections")}
      className="sticky top-0 z-40 border-b border-[var(--border)] bg-[var(--secondary)] text-[var(--secondary-foreground)]"
    >
      <div className="mx-auto flex max-w-screen-2xl items-center gap-3 overflow-x-auto px-4 py-2">
        <Link
          href={backHref}
          className="inline-flex min-h-11 shrink-0 items-center gap-1 text-sm text-white/80 hover:text-white min-[1024px]:min-h-0"
        >
          <ArrowLeft aria-hidden className="size-4" /> {resolvedBackLabel}
        </Link>
        <span aria-hidden className="h-4 w-px shrink-0 bg-[var(--border)]" />
        {/* Wrap instead of a single clipped line: long section lists stay
            fully reachable on narrow screens. On phones the wrapped chips
            filled the whole first viewport, so there a compact select
            carries the same jump list. */}
        <ul className="hidden min-w-0 flex-wrap items-center gap-1 sm:flex">
          {sections.map((s) => (
            <li key={s.id}>
              <a
                href={`#${s.id}`}
                title={s.hint}
                aria-current={active === s.id ? "true" : undefined}
                onClick={(e) => {
                  e.preventDefault();
                  document.getElementById(s.id)?.scrollIntoView({ behavior: "smooth" });
                  // Collapsed (default-closed) cards listen for this so a
                  // nav jump never lands on a hidden section.
                  window.dispatchEvent(new CustomEvent("jb-open-section", { detail: s.id }));
                }}
                className={cn(
                  "inline-block whitespace-nowrap rounded px-2 py-1 text-sm underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white",
                  active === s.id ? "font-medium text-white underline" : "text-white/80",
                )}
              >
                {s.label}
              </a>
            </li>
          ))}
        </ul>
        <select
          aria-label={t("nav.sections")}
          className="min-w-0 flex-1 rounded-[var(--radius)] border border-white/25 bg-white/10 px-1.5 py-1 text-xs text-white sm:hidden [&>option]:bg-[var(--card)] [&>option]:text-[var(--foreground)]"
          value={active ?? sections[0]?.id}
          onChange={(e) => {
            document.getElementById(e.target.value)?.scrollIntoView({ behavior: "smooth" });
            window.dispatchEvent(new CustomEvent("jb-open-section", { detail: e.target.value }));
          }}
        >
          {sections.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
      </div>
    </nav>
  );
}
