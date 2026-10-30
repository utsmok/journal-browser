"use client";

import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";

import type { SortKey } from "@/lib/api";
import { COLUMN_SORTS } from "@/lib/search-config";

export function SortHead({
  columnId,
  label,
  state,
  title,
}: {
  columnId: string;
  label: string;
  state: {
    sort: SortKey;
    dir: "asc" | "desc" | null;
    cycleSort: (columnId: string) => void;
    disabled?: boolean;
  };
  title?: string;
}) {
  // Semantic ranking ignores sort params, so the buttons would lie.
  if (state.disabled)
    return <span className="inline-flex items-center gap-1 opacity-60">{label}</span>;
  const spec = COLUMN_SORTS[columnId];
  const active = !!spec && state.sort === spec.key;
  const current = active ? (state.dir ?? spec!.natural) : null;
  const atNatural = active && current === spec!.natural;
  const Icon = !active ? ChevronsUpDown : current === "asc" ? ArrowUp : ArrowDown;
  return (
    <button
      type="button"
      onClick={() => state.cycleSort(columnId)}
      title={
        title ??
        (active
          ? `Sorted ${current === "asc" ? "A–Z, low–high" : "Z–A, high–low"}; click to ${atNatural ? "reverse" : "reset"}`
          : `Sort by ${label}`)
      }
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
