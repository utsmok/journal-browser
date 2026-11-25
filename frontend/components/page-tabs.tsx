"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

export type PageTabItem<T extends string = string> = {
  value: T;
  label: string;
  badge?: string | number;
  icon?: React.ReactNode;
};

/**
 * Shared underline tab bar used across top-level directories
 * (Journals, Organisational units, Deals) instead of boxy segmented controls.
 */
export function PageTabs<T extends string>({
  items,
  value,
  onChange,
  ariaLabel,
  className,
}: {
  items: PageTabItem<T>[];
  value: T;
  onChange: (value: T) => void;
  ariaLabel: string;
  className?: string;
}) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cn(
        "flex flex-wrap items-center gap-x-6 gap-y-1 border-b border-[var(--border)]",
        className,
      )}
    >
      {items.map((item) => {
        const active = item.value === value;
        return (
          <button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(item.value)}
            className={cn(
              "-mb-px inline-flex min-h-11 items-center gap-2 border-b-2 pb-2.5 pt-1 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2 min-[1024px]:min-h-0",
              active
                ? "border-[var(--primary)] font-semibold text-[var(--foreground)]"
                : "border-transparent font-medium text-[var(--muted-foreground)] hover:border-[var(--border)] hover:text-[var(--foreground)]",
            )}
          >
            {item.icon}
            <span>{item.label}</span>
            {item.badge !== undefined && (
              <span
                className={cn(
                  "rounded-full px-2 py-0.5 text-xs tabular-nums",
                  active
                    ? "bg-[var(--brand-tint-bg)] text-[var(--primary-text)]"
                    : "bg-[var(--muted)] text-[var(--muted-foreground)]",
                )}
              >
                {item.badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
