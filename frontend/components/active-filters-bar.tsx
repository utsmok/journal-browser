"use client";

import { X } from "lucide-react";

import { Button } from "@/components/ui/button";

export type ActiveFilterChip = {
  id: string;
  label: string;
  onRemove: () => void;
};

/** Dismissible row of active filter chips + a Clear all action. */
export function ActiveFiltersBar({
  chips,
  onClearAll,
  ariaLabel = "Active filters",
  clearLabel = "Clear all",
  removeAriaPrefix = "Remove filter",
}: {
  chips: ActiveFilterChip[];
  onClearAll: () => void;
  ariaLabel?: string;
  clearLabel?: string;
  removeAriaPrefix?: string;
}) {
  if (chips.length === 0) return null;
  return (
    <div aria-label={ariaLabel} className="mb-4 flex flex-wrap items-center gap-1.5 text-xs">
      {chips.map((chip) => (
        <button
          key={chip.id}
          type="button"
          onClick={chip.onRemove}
          aria-label={`${removeAriaPrefix}: ${chip.label}`}
          className="inline-flex items-center gap-1 rounded-md border border-[var(--brand-tint-border)] bg-[var(--brand-tint-bg)] px-2 py-1 text-[var(--primary-text)] hover:border-[var(--primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2"
        >
          <span className="max-w-[16rem] truncate">{chip.label}</span>
          <X aria-hidden className="size-3 shrink-0" />
        </button>
      ))}
      <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={onClearAll}>
        {clearLabel}
      </Button>
    </div>
  );
}
