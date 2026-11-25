"use client";

import { Bookmark } from "lucide-react";
import * as React from "react";
import { useTranslations } from "next-intl";

import { addJournal, removeJournal, useShortlist } from "@/lib/shortlist";
import { cn } from "@/lib/utils";

/**
 * Bookmark that puts one journal on the shortlist or takes it off. The label
 * stays the same whether or not the journal is saved and `aria-pressed`
 * carries the state, so screen readers announce a toggle. The empty
 * pseudo-element widens the tap area to 40 px around the 24 px icon.
 */
export function ShortlistToggle({
  inst,
  issnL,
  title,
  className,
}: {
  inst: string;
  issnL: string;
  title: string;
  /** Extra classes, for a different size or for stacking above a row-wide link. */
  className?: string;
}) {
  const t = useTranslations("shortlist");
  const saved = useShortlist(inst).some((entry) => entry.issnL === issnL);
  return (
    <button
      type="button"
      aria-pressed={saved}
      aria-label={t("toggle.add", { title })}
      title={saved ? t("toggle.removeTitle", { title }) : t("toggle.addTitle", { title })}
      onClick={(event) => {
        // Result rows navigate on click; the bookmark must only toggle.
        event.stopPropagation();
        if (saved) removeJournal(inst, issnL);
        else addJournal(inst, issnL, title);
      }}
      className={cn(
        "relative inline-flex size-6 shrink-0 items-center justify-center rounded-[var(--radius)] text-[var(--muted-foreground)] before:absolute before:-inset-2 hover:bg-[var(--muted)] hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
        saved && "text-[var(--primary-text)]",
        className,
      )}
    >
      <Bookmark aria-hidden className={cn("size-4", saved && "fill-current")} />
    </button>
  );
}
