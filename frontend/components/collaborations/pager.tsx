"use client";

import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";

/** Previous and next page of a list that pages with an offset. */
export function Pager({
  offset,
  shown,
  total,
  pageSize,
  onOffset,
  isFetching = false,
}: {
  offset: number;
  /** Rows on the current page. */
  shown: number;
  total: number;
  pageSize: number;
  onOffset: (offset: number) => void;
  isFetching?: boolean;
}) {
  const t = useTranslations("collaborations");
  return (
    <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
      <p className="inline-flex items-center gap-1.5 text-sm text-[var(--muted-foreground)]">
        <span>
          {t("range", {
            from: (offset + 1).toLocaleString("en"),
            to: (offset + shown).toLocaleString("en"),
            total: total.toLocaleString("en"),
          })}
        </span>
        {isFetching && <Loader2 aria-hidden className="size-3.5 animate-spin" />}
      </p>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={offset === 0}
          onClick={() => onOffset(Math.max(0, offset - pageSize))}
        >
          <ChevronLeft aria-hidden className="size-4" /> {t("prev")}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={offset + shown >= total}
          onClick={() => onOffset(offset + pageSize)}
        >
          {t("next")} <ChevronRight aria-hidden className="size-4" />
        </Button>
      </div>
    </div>
  );
}
