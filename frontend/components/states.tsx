"use client";

import { useTranslations } from "next-intl";

import { BackLink } from "@/components/back-link";

/** Detail-page loading state: the entity name (when the URL provides it)
 * plus one labelled block per expected section, so a slow detail request
 * reads as progress instead of an anonymous grey page. */
export function DetailSkeleton({
  title,
  sections,
  label,
}: {
  /** Entity name known from the URL; renders as real text. */
  title?: string;
  /** Section names, already translated. */
  sections?: string[];
  /** Accessible loading label; defaults to the generic one. */
  label?: string;
}) {
  const t = useTranslations("common");
  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10" aria-busy="true" aria-live="polite">
      <span className="sr-only">{label ?? t("states.loadingDetails")}</span>
      {title !== undefined ? (
        <h1 className="text-3xl font-bold text-balance">{title}</h1>
      ) : (
        <div className="h-8 w-2/3 animate-pulse rounded bg-[var(--muted)]" />
      )}
      <div className="mt-8 space-y-6">
        {(sections ?? []).map((section) => (
          <div
            key={section}
            className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm"
          >
            <p className="text-sm font-medium text-[var(--muted-foreground)]">{section}</p>
            <div className="mt-3 space-y-2.5">
              {[92, 75, 84, 60].map((w, i) => (
                <div
                  key={i}
                  className="h-4 animate-pulse rounded bg-[var(--muted)]"
                  style={{ width: `${w}%` }}
                />
              ))}
            </div>
          </div>
        ))}
        {(!sections || sections.length === 0) && (
          <div className="h-40 animate-pulse rounded bg-[var(--muted)]" />
        )}
      </div>
    </div>
  );
}

/**
 * Full-page skeleton for the journal detail. Mirrors the real layout
 * (header, key-stats grid, chart, publications list) so sections pop in
 * without the page reflowing underneath the reader.
 */
export function JournalDetailSkeleton() {
  const t = useTranslations("common");
  const tj = useTranslations("journals");
  return (
    <div className="mx-auto max-w-5xl px-4 py-10" aria-busy="true" aria-live="polite">
      <span className="sr-only">{t("states.loadingJournal")}</span>
      <div className="flex flex-wrap items-center gap-2">
        <div className="h-8 w-72 max-w-full animate-pulse rounded bg-[var(--muted)]" />
        <div className="h-6 w-24 animate-pulse rounded bg-[var(--muted)]" />
        <div className="h-6 w-16 animate-pulse rounded bg-[var(--muted)]" />
      </div>
      <div className="mt-2 h-4 w-44 animate-pulse rounded bg-[var(--muted)]" />
      <div className="mt-8 space-y-6">
        {[tj("oaPerYear.title"), tj("deal.title"), tj("publications.navLabel")].map((section) => (
          <div
            key={section}
            className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm"
          >
            <p className="text-sm font-medium text-[var(--muted-foreground)]">{section}</p>
            <div className="mt-3 h-24 animate-pulse rounded bg-[var(--muted)]" />
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * Detail-page error state: message plus a way back. Defaults match the
 * search-backed detail pages; callers with other labels or margins override.
 */
export function ErrorPanel({
  message,
  backHref,
  backLabel,
  backClassName = "mt-2",
}: {
  message: string;
  backHref: string;
  backLabel?: string;
  backClassName?: string;
}) {
  const t = useTranslations("common");
  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <p className="text-[var(--destructive)]">{message}</p>
      <BackLink
        href={backHref}
        label={backLabel ?? t("states.backToSearch")}
        className={backClassName}
      />
    </div>
  );
}

/** List-page loading state: `rows` placeholder bars. */
export function ListSkeletonRows({ rows }: { rows: number }) {
  return (
    <div className="space-y-2 py-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-9 animate-pulse rounded bg-[var(--muted)]" />
      ))}
    </div>
  );
}
