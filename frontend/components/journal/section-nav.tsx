"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import * as React from "react";

import { useInstitution } from "@/hooks/use-institution";
import { cn } from "@/lib/utils";

/** href for "Back to search": the last search this tab ran, else this
 * university's search home (never the global landing). */
export function useLastSearchHref(): string {
  const inst = useInstitution();
  const fallback = `/${inst}/`;
  const [href, setHref] = React.useState(fallback);
  React.useEffect(() => {
    setHref(sessionStorage.getItem("jb-last-search") ?? fallback);
  }, [fallback]);
  return href;
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
}: {
  sections: { id: string; label: string; hint?: string }[];
}) {
  const active = useSectionSpy(sections.map((s) => s.id));
  const t = useTranslations("journals");
  // Muted-foreground/primary-text both fail 4.5:1 on the navy bar, so this
  // nav speaks in white and separates the active item with weight+underline.
  const backHref = useLastSearchHref();
  return (
    <nav
      aria-label={t("nav.sections")}
      className="sticky top-0 z-40 border-b border-[var(--border)] bg-[var(--secondary)] text-[var(--secondary-foreground)]"
    >
      <div className="mx-auto flex max-w-5xl items-center gap-3 overflow-x-auto px-4 py-2">
        <Link
          href={backHref}
          className="inline-flex shrink-0 items-center gap-1 text-sm text-white/80 hover:text-white"
        >
          <ArrowLeft aria-hidden className="size-4" /> {t("nav.backToSearch")}
        </Link>
        <span aria-hidden className="h-4 w-px shrink-0 bg-[var(--border)]" />
        {/* Wrap instead of a single clipped line: long section lists stay
            fully reachable on narrow screens. */}
        <ul className="flex min-w-0 flex-wrap items-center gap-1">
          {sections.map((s) => (
            <li key={s.id}>
              <a
                href={`#${s.id}`}
                title={s.hint}
                aria-current={active === s.id ? "true" : undefined}
                onClick={(e) => {
                  e.preventDefault();
                  document.getElementById(s.id)?.scrollIntoView({ behavior: "smooth" });
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
      </div>
    </nav>
  );
}
