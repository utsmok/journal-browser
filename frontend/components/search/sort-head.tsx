"use client";

import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import { useTranslations } from "next-intl";

import { COLUMN_SORTS } from "@/lib/search-config";

/** Column → backend sort key + natural direction; defaults to the journal
 * search table's specs so journals callers need no prop. */
type SortSpecs = Record<string, { key: string; natural: "asc" | "desc" }>;

export function SortHead({
  columnId,
  label,
  state,
  title,
}: {
  columnId: string;
  label: string;
  state: {
    sort?: string | null;
    dir: "asc" | "desc" | null;
    cycleSort: (columnId: string) => void;
    disabled?: boolean;
    specs?: SortSpecs;
  };
  title?: string;
}) {
  const t = useTranslations("common");
  // Semantic ranking ignores sort params, so the buttons would lie.
  if (state.disabled)
    return <span className="inline-flex items-center gap-1 opacity-60">{label}</span>;
  const spec = (state.specs ?? COLUMN_SORTS)[columnId];
  const active = !!spec && state.sort === spec.key;
  const current = active ? (state.dir ?? spec!.natural) : null;
  const atNatural = active && current === spec!.natural;
  const Icon = !active ? ChevronsUpDown : current === "asc" ? ArrowUp : ArrowDown;
  const sortedTitle = active
    ? current === "asc"
      ? t(atNatural ? "sortHead.sortedAscReverse" : "sortHead.sortedAscReset")
      : t(atNatural ? "sortHead.sortedDescReverse" : "sortHead.sortedDescReset")
    : "";
  return (
    <button
      type="button"
      onClick={() => state.cycleSort(columnId)}
      title={title ?? (active ? sortedTitle : t("sortHead.sortBy", { label }))}
      className="inline-flex items-center gap-1 hover:text-[var(--foreground)]"
    >
      {label}
      <Icon
        aria-hidden
        className={`size-3 ${active ? "text-[var(--primary-text)]" : "opacity-50"}`}
      />
    </button>
  );
}
