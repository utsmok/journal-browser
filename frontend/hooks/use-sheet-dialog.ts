"use client";

import * as React from "react";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';

/** Marks an element that must stay interactive while a sheet is open (the
 * backdrop), so the rest of the page can be made inert around the sheet. */
export const SHEET_KEEP = "data-sheet-keep";

function focusableIn(panel: HTMLElement): HTMLElement[] {
  // Closed <details> keep their controls in the DOM but without a box.
  return [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
    (el) => el.getClientRects().length > 0,
  );
}

/**
 * Modal behaviour for a panel that is a sheet on one screen class and an
 * inline region on the other (a menu drawer, a filter sidebar). While
 * `open && modal`, focus moves into the panel, Tab cycles inside it, Escape
 * calls `onClose`, the page behind cannot scroll, and everything outside the
 * panel becomes inert. Closing returns focus to `returnFocusTo`, or else to
 * the element that had it when the sheet opened.
 *
 * The caller switches `modal` off above its breakpoint and closes the panel
 * there, so the same element stays one DOM instance in both forms.
 */
export function useSheetDialog({
  open,
  modal,
  onClose,
  returnFocusTo,
}: {
  open: boolean;
  modal: boolean;
  onClose: () => void;
  returnFocusTo?: React.RefObject<HTMLElement | null>;
}) {
  const panelRef = React.useRef<HTMLDivElement>(null);
  const labelId = React.useId();
  const onCloseRef = React.useRef(onClose);
  React.useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  React.useEffect(() => {
    if (!open || !modal) return;
    const panel = panelRef.current;
    if (!panel) return;
    const opener =
      returnFocusTo?.current ??
      (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    const root = document.documentElement;
    const previousOverflow = root.style.overflow;
    root.style.overflow = "hidden";

    // Everything beside the panel's ancestor chain is the "rest of the page".
    const inerted: HTMLElement[] = [];
    for (let el: HTMLElement | null = panel; el && el !== document.body; ) {
      const parent: HTMLElement | null = el.parentElement;
      if (!parent) break;
      for (const sibling of parent.children) {
        if (
          sibling === el ||
          sibling.hasAttribute(SHEET_KEEP) ||
          sibling.matches("script, style, template") ||
          sibling.hasAttribute("inert")
        )
          continue;
        sibling.setAttribute("inert", "");
        inerted.push(sibling as HTMLElement);
      }
      el = parent;
    }

    (focusableIn(panel)[0] ?? panel).focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusableIn(panel);
      const first = items[0];
      const last = items.at(-1);
      if (!first || !last) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const current = document.activeElement;
      const outside = !panel.contains(current);
      if ((event.shiftKey && (current === first || outside)) || (!event.shiftKey && outside)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (!event.shiftKey && current === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      for (const el of inerted) el.removeAttribute("inert");
      root.style.overflow = previousOverflow;
      if (opener?.isConnected && opener.getClientRects().length > 0) opener.focus();
    };
  }, [open, modal, returnFocusTo]);

  return { panelRef, labelId };
}
