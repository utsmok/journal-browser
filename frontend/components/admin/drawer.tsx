"use client";

import { useEffect } from "react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";

/**
 * Right-side slide-over for focused record work (deal editor, create forms).
 * ESC or the overlay closes it; content scrolls independently.
 */
export function AdminDrawer({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label={title}>
      <button
        type="button"
        aria-label="Close panel"
        tabIndex={-1}
        className="absolute inset-0 h-full w-full cursor-default bg-black/40"
        onClick={onClose}
      />
      <div className="absolute inset-y-0 right-0 flex w-full max-w-2xl flex-col border-l bg-[var(--card)] shadow-xl">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <h2 className="text-base font-semibold">{title}</h2>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">{children}</div>
      </div>
    </div>
  );
}
