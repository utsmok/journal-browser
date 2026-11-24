"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Inset bordered sub-panel for multi-group detail cards (e.g. Similar journals,
 * UT authorship, OpenAIRE subjects/funders, Detailed metrics) so each group has
 * a clear visual boundary, background header bar, and optional count badge.
 */
export function InsetPanel({
  title,
  icon,
  count,
  subtitle,
  children,
  className,
  bodyClassName,
}: {
  title: React.ReactNode;
  icon?: React.ReactNode;
  count?: number | string;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <div
      className={cn(
        "overflow-hidden rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)]",
        className,
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-0.5 border-b border-[var(--border)] bg-[var(--muted)]/50 px-3 py-2">
        <div className="flex min-w-0 items-center gap-1.5">
          {icon}
          <h3 className="text-xs font-semibold text-[var(--foreground)] sm:text-sm">{title}</h3>
          {count !== undefined && (
            <span className="inline-flex items-center rounded-full border border-[var(--border)] bg-[var(--card)] px-1.5 py-0.5 text-[11px] font-normal tabular-nums text-[var(--muted-foreground)]">
              {typeof count === "number" ? count.toLocaleString("en") : count}
            </span>
          )}
        </div>
        {subtitle && <p className="w-full text-xs text-[var(--muted-foreground)]">{subtitle}</p>}
      </div>
      <div className={cn("px-3 py-2", bodyClassName)}>{children}</div>
    </div>
  );
}
