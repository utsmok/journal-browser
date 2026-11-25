"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import * as React from "react";

export type TopicChipItem = {
  key?: string;
  name: string;
  count?: number;
  href?: string;
  title?: string;
};

/** Uniform compact topic pill list shared across Journal, Publisher, Author, and Partner detail pages. */
export function TopicChipList({
  items,
  limit = 8,
  showCounts = true,
}: {
  items: TopicChipItem[];
  limit?: number;
  showCounts?: boolean;
}) {
  const t = useTranslations("common");
  const [expanded, setExpanded] = React.useState(false);
  if (items.length === 0) return null;
  const shown = expanded ? items : items.slice(0, limit);
  const chipClass =
    "inline-flex min-h-11 items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--muted)] px-2 py-0.5 text-xs text-[var(--foreground)] min-[1024px]:min-h-0";

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {shown.map((item) => {
        const content = (
          <>
            <span>{item.name}</span>
            {showCounts && item.count != null && (
              <span className="tabular-nums text-[var(--muted-foreground)]">
                {item.count.toLocaleString("en")}
              </span>
            )}
          </>
        );
        return item.href ? (
          <Link
            key={item.key ?? item.name}
            href={item.href}
            title={item.title}
            className={`${chipClass} underline-offset-2 hover:border-[var(--primary)] hover:text-[var(--primary-text)] hover:underline`}
          >
            {content}
          </Link>
        ) : (
          <span key={item.key ?? item.name} title={item.title} className={chipClass}>
            {content}
          </span>
        );
      })}
      {items.length > limit && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="inline-flex min-h-11 items-center px-1.5 py-1 text-xs text-[var(--muted-foreground)] underline-offset-2 hover:text-[var(--primary-text)] hover:underline min-[1024px]:min-h-0"
        >
          {expanded ? t("list.showLess") : t("list.showMore", { count: items.length - limit })}
        </button>
      )}
    </div>
  );
}
