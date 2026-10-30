"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { JournalSearchResponse } from "@/lib/api";

export function Pagination({
  data,
  isFetching,
  stack,
  moveTo,
}: {
  data?: JournalSearchResponse;
  isFetching: boolean;
  stack: string[];
  moveTo: (nextStack: string[], nextCursor: string | undefined) => void;
}) {
  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
      <p className="text-sm text-[var(--muted-foreground)]">
        {/* Announce only settled counts: while a fetch runs the live
            region keeps its previous text, so typing never chatters. */}
        <span aria-live="polite">
          {data ? `${data.total.toLocaleString("en")} journal${data.total === 1 ? "" : "s"}` : ""}
        </span>
        {isFetching && data ? " · updating…" : ""}
      </p>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={stack.length === 0}
          onClick={() => {
            const next = stack.slice(0, -1);
            moveTo(next, next[next.length - 1]);
          }}
        >
          <ChevronLeft aria-hidden className="size-4" /> Prev
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={!data?.next_cursor}
          onClick={() => {
            if (!data?.next_cursor) return;
            moveTo([...stack, data.next_cursor], data.next_cursor);
          }}
        >
          Next <ChevronRight aria-hidden className="size-4" />
        </Button>
      </div>
    </div>
  );
}
