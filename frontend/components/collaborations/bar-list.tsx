"use client";

/** Labelled bars for a small set of counts. The number next to each bar
 * carries the value, so the bar is decoration for screen readers. */
export function BarList({
  title,
  rows,
}: {
  title: string;
  rows: { label: string; count: number }[];
}) {
  const max = Math.max(1, ...rows.map((row) => row.count));
  return (
    <div>
      <h3 className="text-sm font-semibold">{title}</h3>
      <ul className="mt-2 space-y-1.5">
        {rows.map((row) => (
          <li
            key={row.label}
            className="grid grid-cols-[7rem_minmax(0,1fr)_4rem] items-center gap-3 text-sm"
          >
            <span className="truncate">{row.label}</span>
            <span className="block h-2 rounded-full bg-[var(--muted)]" aria-hidden>
              <span
                className="block h-2 rounded-full bg-[var(--primary)]"
                style={{ width: `${(row.count / max) * 100}%` }}
              />
            </span>
            <span className="text-right tabular-nums">{row.count.toLocaleString("en")}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
