"use client";

import { Menu, X } from "lucide-react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { YearFilterChip } from "@/components/year-filter";
import { useMediaQuery } from "@/hooks/use-media-query";
import { SHEET_KEEP, useSheetDialog } from "@/hooks/use-sheet-dialog";
import { cn } from "@/lib/utils";

/** Viewport from which the header shows nav and utilities inline. Below it
 * the same elements sit in a right-hand drawer behind a menu button. */
export const HEADER_INLINE_QUERY = "(min-width: 1024px)";

const MENU_ID = "site-menu";

const iconButton =
  "inline-flex size-11 shrink-0 items-center justify-center rounded-[var(--radius)] text-white hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70";

/**
 * Header region that is a drawer below the `lg` breakpoint and plain header
 * content above it. The children (nav links, utilities) exist once: on
 * wide screens `display: contents` makes them direct items of the header
 * bar, on narrow screens they stack inside the drawer.
 */
export function SiteMenu({ children }: { children: React.ReactNode }) {
  const t = useTranslations("common");
  const pathname = usePathname() ?? "/";
  const inline = useMediaQuery(HEADER_INLINE_QUERY);
  // The drawer belongs to one location: navigating, or growing the viewport
  // past the breakpoint, closes it without a separate effect.
  const [openPath, setOpenPath] = React.useState<string | null>(null);
  const open = openPath === pathname && !inline;
  const openerRef = React.useRef<HTMLElement | null>(null);
  const close = React.useCallback(() => setOpenPath(null), []);
  const { panelRef, labelId } = useSheetDialog({
    open,
    modal: !inline,
    onClose: close,
    returnFocusTo: openerRef,
  });

  const show = (event: React.MouseEvent<HTMLElement>) => {
    openerRef.current = event.currentTarget;
    setOpenPath(pathname);
  };

  return (
    <>
      <div className="flex items-center gap-1 lg:hidden">
        <YearFilterChip onClick={show} />
        <button
          type="button"
          aria-label={t("nav.openMenu")}
          aria-controls={MENU_ID}
          aria-expanded={open}
          onClick={(event) => (open ? close() : show(event))}
          className={iconButton}
        >
          <Menu aria-hidden className="size-5" />
        </button>
      </div>
      <div
        {...{ [SHEET_KEEP]: "" }}
        aria-hidden
        onClick={close}
        className={cn("fixed inset-0 z-[55] bg-black/50 lg:hidden", !open && "hidden")}
      />
      <div
        id={MENU_ID}
        ref={panelRef}
        role={open ? "dialog" : undefined}
        aria-modal={open ? true : undefined}
        aria-labelledby={labelId}
        className={cn(
          "hidden lg:contents",
          open &&
            "fixed inset-y-0 right-0 z-[60] flex w-full max-w-sm flex-col gap-6 overflow-y-auto bg-[var(--secondary)] p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] shadow-2xl",
        )}
      >
        <div className="flex items-center justify-between gap-2 border-b border-white/15 px-1 pb-2 lg:hidden">
          <h2 id={labelId} className="text-lg font-bold text-white">
            {t("nav.menuLabel")}
          </h2>
          <button
            type="button"
            aria-label={t("nav.closeMenu")}
            onClick={close}
            className={iconButton}
          >
            <X aria-hidden className="size-5" />
          </button>
        </div>
        {children}
      </div>
    </>
  );
}
