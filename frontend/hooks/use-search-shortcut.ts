"use client";

import * as React from "react";

/** Focus `#<inputId>` when pressing `/` outside form fields; blur on `Escape`. */
export function useSearchShortcut(inputId: string) {
  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (event.key === "Escape" && target?.id === inputId) {
        target.blur();
        return;
      }
      if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) return;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable)
      ) {
        return;
      }
      event.preventDefault();
      document.getElementById(inputId)?.focus();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [inputId]);
}
