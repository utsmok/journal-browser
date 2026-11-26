"use client";

import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import type * as React from "react";

import { Button } from "@/components/ui/button";
import type { JournalSearchResponse } from "@/lib/api";

export function Pagination({
  data,
  isFetching,
  stack,
  moveTo,
  toolbarSlot,
}: {
  data?: JournalSearchResponse;
  isFetching: boolean;
  stack: string[];
  moveTo: (nextStack: string[], nextCursor: string | undefined) => void;
  toolbarSlot?: React.ReactNode;
}) {
  const t = useTranslations("common");
  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] pb-3">
      <p className="inline-flex items-center gap-1.5 text-sm text-[var(--muted-foreground)]">
        {/* Announce only settled counts: while a fetch runs the live
            region keeps its previous text, so typing never chatters. */}
        <span aria-live="polite">{data ? t("pagination.count", { count: data.total }) : ""}</span>
        {isFetching && data ? (
          <span className="inline-flex items-center gap-1">
            <Loader2 aria-hidden className="size-3 animate-spin" />
            {t("pagination.updating")}
          </span>
        ) : null}
      </p>
      <div className="flex flex-wrap items-center gap-3">
        {toolbarSlot}
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
            <ChevronLeft aria-hidden className="size-4" /> {t("pagination.prev")}
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
            {t("pagination.next")} <ChevronRight aria-hidden className="size-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
