"use client";

import { cn } from "@/lib/utils";

/**
 * Zero-layout-shift indeterminate progress bar overlaid at the top edge of a
 * card or page container while an async update is in flight.
 */
export function LoadingBar({ active, className }: { active: boolean; className?: string }) {
  if (!active) return null;
  return (
    <div
      aria-hidden="true"
      className={cn(
        "pointer-events-none absolute inset-x-0 top-0 z-10 h-0.5 overflow-hidden bg-[var(--primary)]/15",
        className,
      )}
    >
      <div className="jb-indeterminate-bar h-full w-1/3 rounded-full bg-[var(--primary)]" />
    </div>
  );
}
