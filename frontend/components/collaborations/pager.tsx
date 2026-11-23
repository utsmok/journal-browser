"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";

/** Previous and next page of a list that pages with an offset. */
export function Pager({
  offset,
  shown,
  total,
  pageSize,
  onOffset,
}: {
  offset: number;
  /** Rows on the current page. */
  shown: number;
  total: number;
  pageSize: number;
  onOffset: (offset: number) => void;
}) {
  const t = useTranslations("collaborations");
  return (
    <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
      <p className="text-sm text-[var(--muted-foreground)]">
        {t("range", {
          from: (offset + 1).toLocaleString("en"),
          to: (offset + shown).toLocaleString("en"),
          total: total.toLocaleString("en"),
        })}
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
