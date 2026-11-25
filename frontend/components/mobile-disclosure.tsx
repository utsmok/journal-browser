"use client";

import { ChevronDown } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Section that is always visible from 960px and, below that, opens from a
 * full-width button so the results below it start near the top of the page.
 * CSS alone decides the wide-screen state, so the server markup is right on
 * both viewports and needs no correction after hydration.
 */
export function MobileDisclosure({
  label,
  className,
  children,
}: {
  /** Button text, also the accessible name of the section. */
  label: string;
  className?: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const panelId = React.useId();
  return (
    <div className={cn("min-w-0", className)}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex min-h-11 w-full items-center justify-between gap-2 rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-3 py-2 text-sm font-medium hover:bg-[var(--muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] min-[960px]:hidden"
      >
        {label}
        <ChevronDown
          aria-hidden
          className={cn("size-4 shrink-0 transition-transform", open && "rotate-180")}
        />
      </button>
      <div id={panelId} className={cn("min-[960px]:block", !open && "hidden")}>
        {children}
      </div>
    </div>
  );
}
