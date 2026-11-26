"use client";

import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";

const DEFAULT_LIMIT_OPTIONS = [25, 50, 100] as const;

/** Shared offset pager with exact "Showing X–Y of Z" range and optional per-page selector. */
export function DirectoryPager({
  offset,
  shown,
  total,
  limit,
  onOffset,
  onLimit,
  limitOptions = DEFAULT_LIMIT_OPTIONS,
  perPageLabel = "Per page",
  prevLabel = "Previous",
  nextLabel = "Next",
  isFetching = false,
  position = "bottom",
}: {
  offset: number;
  shown: number;
  total: number;
  limit: number;
  onOffset: (nextOffset: number) => void;
  onLimit?: (nextLimit: number) => void;
  limitOptions?: readonly number[];
  perPageLabel?: string;
  prevLabel?: string;
  nextLabel?: string;
  isFetching?: boolean;
  position?: "top" | "bottom";
}) {
  const from = total > 0 && shown > 0 ? offset + 1 : 0;
  const to = total > 0 && shown > 0 ? Math.min(total, offset + shown) : 0;
  const hasPrev = offset > 0;
  const hasNext = offset + shown < total;

  return (
    <div
      className={`flex flex-wrap items-center justify-between gap-2 text-xs text-[var(--muted-foreground)] ${
        position === "top" ? "mb-3" : "mt-4"
      }`}
    >
      <div className="flex flex-wrap items-center gap-3">
        <span aria-live="polite" className="inline-flex items-center gap-1.5 tabular-nums">
          <span>
            {total > 0 && shown > 0
              ? `${from.toLocaleString("en")}–${to.toLocaleString("en")} of ${total.toLocaleString("en")}`
              : `0 of ${total.toLocaleString("en")}`}
          </span>
          {isFetching ? (
            <span className="inline-flex items-center gap-1">
              <Loader2 aria-hidden className="size-3 animate-spin" />
              (updating…)
            </span>
          ) : null}
        </span>
        {onLimit && (
          <label className="inline-flex items-center gap-1.5">
            <span>{perPageLabel}</span>
            <select
              aria-label={perPageLabel}
              value={limit}
              onChange={(event) => onLimit(Number(event.target.value))}
              className="h-7 rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-1.5 text-xs text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2"
            >
              {limitOptions.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {(hasPrev || hasNext) && (
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={!hasPrev}
            onClick={() => onOffset(Math.max(0, offset - limit))}
          >
            <ChevronLeft aria-hidden className="size-4" />
            {prevLabel}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!hasNext}
            onClick={() => onOffset(offset + limit)}
          >
            {nextLabel}
            <ChevronRight aria-hidden className="size-4" />
          </Button>
        </div>
      )}
    </div>
  );
}
