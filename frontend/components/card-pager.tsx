"use client";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";

/** Compact numbered pagination window: first, last and current ± 1 with gaps. */
function pageWindow(current: number, pages: number): (number | "…")[] {
  const wanted = [...new Set([1, pages, current - 1, current, current + 1])]
    .filter((p) => p >= 1 && p <= pages)
    .sort((a, b) => a - b);
  const out: (number | "…")[] = [];
  for (const p of wanted) {
    if (out.length && p - (out.at(-1) as number) > 1) out.push("…");
    out.push(p);
  }
  return out;
}

/** Pager row for paginated card content (same look as the journal
 * publications card). */
export function CardPager({
  page,
  pages,
  total,
  onPage,
  isFetching = false,
  label,
}: {
  page: number;
  pages: number;
  total: number;
  onPage: (page: number) => void;
  isFetching?: boolean;
  /** Name of the paged items, e.g. "publications"; defaults to "items". */
  label?: string;
}) {
  const t = useTranslations("common");
  const itemsLabel = label ?? t("cardPager.itemsLabel");
  return (
    <nav
      className="flex flex-wrap items-center gap-1 text-xs"
      aria-label={t("cardPager.navAriaLabel", { label: itemsLabel })}
    >
      <Button
        variant="outline"
        size="sm"
        disabled={page <= 1 || isFetching}
        onClick={() => onPage(Math.max(1, page - 1))}
      >
        {t("cardPager.prev")}
      </Button>
      {pageWindow(page, pages).map((p, i) =>
        p === "…" ? (
          <span key={`gap-${i}`} className="px-1 text-[var(--muted-foreground)]">
            …
          </span>
        ) : (
          <Button
            key={p}
            variant={p === page ? "secondary" : "outline"}
            size="sm"
            disabled={isFetching}
            onClick={() => onPage(p)}
            aria-current={p === page ? "page" : undefined}
          >
            {p}
          </Button>
        ),
      )}
      <Button
        variant="outline"
        size="sm"
        disabled={page >= pages || isFetching}
        onClick={() => onPage(Math.min(pages, page + 1))}
      >
        {t("cardPager.next")}
      </Button>
      <span className="ml-2 text-[var(--muted-foreground)]">
        {t("cardPager.total", { total: total.toLocaleString("en"), label: itemsLabel })}
      </span>
    </nav>
  );
}
