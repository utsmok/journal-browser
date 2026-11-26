"use client";

import { Loader2, SlidersHorizontal, X } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { useMediaQuery } from "@/hooks/use-media-query";
import { SHEET_KEEP, useSheetDialog } from "@/hooks/use-sheet-dialog";
import { cn } from "@/lib/utils";

/** Viewport from which the filters sit in a sidebar column next to the
 * results. Below it they open in a bottom sheet behind a "Filters" button,
 * so the results start at the top of the page. */
export const FILTER_SIDEBAR_QUERY = "(min-width: 960px)";

const GRID =
  "min-[960px]:grid min-[960px]:grid-cols-[15rem_minmax(0,1fr)] min-[960px]:items-start min-[960px]:gap-6 min-[1280px]:grid-cols-[18rem_minmax(0,1fr)] min-[1280px]:gap-8";
const CARD =
  "min-[960px]:block min-[960px]:rounded-[var(--radius)] min-[960px]:border min-[960px]:border-[var(--border)] min-[960px]:bg-[var(--card)] min-[960px]:shadow-sm";
const countBadge =
  "rounded-full bg-[var(--brand-tint-bg)] px-1.5 py-0.5 text-[11px] font-semibold tabular-nums text-[var(--primary-text)]";

/**
 * Two-column directory layout (filters, then results) that keeps the page
 * header's max width and side padding. The filters exist once: a sticky
 * sidebar from 960px, a modal bottom sheet below that.
 */
export function FilterLayout({
  filters,
  aboveFilters,
  className,
  activeCount = 0,
  onReset,
  resetTitle,
  headerSlot,
  disabled = false,
  updating = false,
  children,
}: {
  /** Facet groups shown in the sidebar and the sheet. */
  filters: React.ReactNode;
  /** A control that stays on the page on phones (e.g. a search box) and
   * moves into the sidebar column from 960px. */
  aboveFilters?: React.ReactNode;
  className?: string;
  /** Number of active filters, shown on the button and beside the heading. */
  activeCount?: number;
  onReset?: () => void;
  resetTitle?: string;
  /** Optional extra control placed between the heading and the facets
   * (e.g. a funder picker). */
  headerSlot?: React.ReactNode;
  /** Nothing to filter on this page (no data yet, or a mode without
   * filters): no button and no sheet, and the results take the full width. */
  disabled?: boolean;
  /** Facet counts are refreshing in the background. */
  updating?: boolean;
  /** The results column. */
  children: React.ReactNode;
}) {
  const t = useTranslations("common");
  const sidebar = useMediaQuery(FILTER_SIDEBAR_QUERY);
  const [open, setOpen] = React.useState(false);
  const sheetOpen = open && !sidebar;
  const buttonRef = React.useRef<HTMLButtonElement>(null);
  const close = React.useCallback(() => setOpen(false), []);
  const { panelRef, labelId } = useSheetDialog({
    open: sheetOpen,
    modal: !sidebar,
    onClose: close,
    returnFocusTo: buttonRef,
  });
  React.useEffect(() => {
    if (sidebar) setOpen(false);
  }, [sidebar]);
  const panelId = React.useId();
  // With a control above the filters, the sidebar column is the card and
  // the facets sit inside it; otherwise the facets are the card.
  const columnIsCard = aboveFilters != null;
  return (
    <div className={cn("flex flex-col gap-4", !disabled && GRID, className)}>
      {!disabled && (
        <div
          className={cn(
            "flex min-w-0 flex-col gap-3",
            "min-[960px]:sticky min-[960px]:top-20 min-[960px]:max-h-[calc(100vh-6rem)] min-[960px]:self-start min-[960px]:gap-4 min-[960px]:overflow-y-auto",
            columnIsCard && cn(CARD, "min-[960px]:p-4"),
          )}
        >
          {aboveFilters}
          <div className="min-[960px]:hidden">
            <button
              ref={buttonRef}
              type="button"
              aria-haspopup="dialog"
              aria-expanded={sheetOpen}
              aria-controls={panelId}
              onClick={() => setOpen(true)}
              className={cn(
                "inline-flex min-h-11 items-center gap-2 rounded-[var(--radius)] border bg-[var(--card)] px-3 text-sm font-medium transition-colors hover:bg-[var(--muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2",
                activeCount > 0 ? "border-[var(--primary)]" : "border-[var(--input)]",
              )}
            >
              <SlidersHorizontal aria-hidden className="size-4" />
              {t("facets.sidebarHeading")}
              {activeCount > 0 && (
                <span className="rounded-full bg-[var(--primary)] px-1.5 py-0.5 text-xs font-semibold tabular-nums text-[var(--primary-foreground)]">
                  {activeCount}
                </span>
              )}
            </button>
          </div>
          <div
            {...{ [SHEET_KEEP]: "" }}
            aria-hidden
            onClick={close}
            className={cn(
              "fixed inset-0 z-[55] bg-black/50 min-[960px]:hidden",
              !sheetOpen && "hidden",
            )}
          />
          <aside
            id={panelId}
            ref={panelRef}
            tabIndex={sheetOpen ? -1 : undefined}
            role={sheetOpen ? "dialog" : undefined}
            aria-modal={sheetOpen ? true : undefined}
            aria-labelledby={sheetOpen ? labelId : undefined}
            className={cn(
              !columnIsCard && CARD,
              sheetOpen &&
                "fixed inset-x-0 bottom-0 z-[60] flex max-h-[85dvh] flex-col overscroll-contain rounded-t-[var(--radius)] border-t border-[var(--border)] bg-[var(--card)] shadow-[0_-12px_32px_rgba(0,0,0,0.35)]",
              !sheetOpen && "hidden min-[960px]:block",
            )}
          >
            <div className="flex shrink-0 items-center justify-between gap-2 border-b border-[var(--border)] px-4 py-1 min-[960px]:border-b-0 min-[960px]:px-4 min-[960px]:pb-0 min-[960px]:pt-4">
              <span className="flex min-h-11 items-center gap-2 text-base font-semibold min-[960px]:min-h-0 min-[960px]:text-xs min-[960px]:uppercase min-[960px]:tracking-wide min-[960px]:text-[var(--muted-foreground)]">
                <span id={labelId}>{t("facets.sidebarHeading")}</span>
                {activeCount > 0 && <span className={countBadge}>{activeCount}</span>}
                {updating && (
                  <Loader2
                    aria-hidden
                    className="size-3 animate-spin text-[var(--muted-foreground)]"
                  />
                )}
              </span>
              {onReset && activeCount > 0 && (
                <button
                  type="button"
                  onClick={onReset}
                  title={resetTitle}
                  className="inline-flex min-h-11 items-center rounded-[var(--radius)] px-2 text-sm font-medium text-[var(--primary-text)] underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] min-[960px]:min-h-0 min-[960px]:px-0 min-[960px]:text-xs"
                >
                  {t("facets.sidebarReset")}
                </button>
              )}
              <button
                type="button"
                aria-label={t("facets.closeFilters")}
                onClick={close}
                className="-mr-2 inline-flex size-11 shrink-0 items-center justify-center rounded-[var(--radius)] text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] min-[960px]:hidden"
              >
                <X aria-hidden className="size-5" />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4 min-[960px]:overflow-visible min-[960px]:pt-3">
              {headerSlot && (
                <div className="mb-3 border-b border-[var(--border)] pb-3">{headerSlot}</div>
              )}
              {filters}
            </div>
            <div className="shrink-0 border-t border-[var(--border)] p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] min-[960px]:hidden">
              <Button type="button" className="w-full" onClick={close}>
                {t("facets.showResults")}
              </Button>
            </div>
          </aside>
        </div>
      )}

      <div className="min-w-0">{children}</div>
    </div>
  );
}
