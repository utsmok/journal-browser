import type * as React from "react";

export type KpiItem = {
  label: string;
  value: React.ReactNode;
  hint?: string;
};

/** Compact 3- or 4-tile summary KPI strip for directory and detail headers. */
export function DetailKpiStrip({
  items,
  className = "mb-6",
}: {
  items: KpiItem[];
  className?: string;
}) {
  if (items.length === 0) return null;
  const colsClass =
    items.length <= 2
      ? "sm:grid-cols-2"
      : items.length === 3
        ? "sm:grid-cols-3"
        : "grid-cols-2 lg:grid-cols-4";
  return (
    <dl className={`grid gap-3 ${colsClass} ${className}`}>
      {items.map((item) => (
        <div
          key={item.label}
          title={item.hint}
          className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] px-4 py-3"
        >
          <dt className="text-xs font-medium text-[var(--muted-foreground)]">{item.label}</dt>
          <dd className="mt-1 text-xl font-bold tracking-tight tabular-nums text-[var(--foreground)]">
            {item.value}
          </dd>
          {item.hint && (
            <p className="mt-0.5 truncate text-[11px] text-[var(--muted-foreground)]">
              {item.hint}
            </p>
          )}
        </div>
      ))}
    </dl>
  );
}
