import { OA_STATUS_META, OA_STATUS_ORDER } from "@/components/badges";
import type { StatsYear } from "@/lib/api";

/**
 * Hand-rolled stacked per-year OA-status chart (no chart library), in the
 * StatBars spirit. One column per year; segments stack gold (bottom) →
 * closed (top) and sum to that year's works_count.
 */
export function OaTrend({ stats }: { stats: StatsYear[] }) {
  const total = (s: StatsYear) =>
    OA_STATUS_ORDER.reduce((acc, k) => acc + (s[`oa_${k}`] ?? 0), 0);
  const max = Math.max(1, ...stats.map(total));
  const currentYear = new Date().getFullYear();
  return (
    <div>
      <div
        className="flex h-44 items-end gap-2"
        role="img"
        aria-label="Open access status of Twente publications per year"
      >
        {stats.map((s) => {
          const t = total(s);
          return (
            <div
              key={s.year}
              className="flex h-full flex-1 flex-col items-center justify-end gap-1"
            >
              <span className="text-[11px] tabular-nums text-[var(--muted-foreground)]">
                {t > 0 ? t : ""}
              </span>
              <div
                className="flex w-full max-w-12 flex-col-reverse overflow-hidden rounded-t"
                style={{ height: `${Math.max((t / max) * 100, t > 0 ? 2 : 0)}%` }}
                title={`${s.year}: ${t} works`}
              >
                {OA_STATUS_ORDER.map((status) => {
                  const count = s[`oa_${status}`] ?? 0;
                  if (count === 0) return null;
                  // flexGrow splits the column exactly proportionally; fixed
                  // percentage heights would round and leave gaps.
                  return (
                    <div
                      key={status}
                      className={OA_STATUS_META[status].bar}
                      style={{ flexGrow: count, flexBasis: 0 }}
                      title={`${s.year} · ${OA_STATUS_META[status].label}: ${count}`}
                    />
                  );
                })}
              </div>
              <span className="text-[11px] tabular-nums text-[var(--muted-foreground)]">
                {s.year}
                {s.year === currentYear && <span title="Year in progress">*</span>}
              </span>
            </div>
          );
        })}
      </div>
      {/* The chart is role="img"; this transcript carries the per-year data. */}
      <ul className="sr-only">
        {stats.map((s) => (
          <li key={s.year}>
            {s.year}: {total(s)} works
            {OA_STATUS_ORDER.filter((k) => (s[`oa_${k}`] ?? 0) > 0)
              .map((k) => `${OA_STATUS_META[k].label} ${s[`oa_${k}`]}`)
              .join(", ")}
          </li>
        ))}
      </ul>
      <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-[var(--muted-foreground)]">
        {OA_STATUS_ORDER.map((status) => (
          <li key={status} className="flex items-center gap-1.5">
            <span
              aria-hidden
              className={`inline-block size-2.5 rounded-full ${OA_STATUS_META[status].bar}`}
            />
            {OA_STATUS_META[status].label}
          </li>
        ))}
        {stats.some((s) => s.year === currentYear) && (
          <li>* year in progress</li>
        )}
      </ul>
    </div>
  );
}
