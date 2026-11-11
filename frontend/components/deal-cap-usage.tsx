import type { CapUsageEntry } from "@/lib/deal-caps";

/** One line per latest-year cap usage entry, plus remaining APCs when the
 * cap is nearly exhausted. `?` marks a year whose used count the library
 * has not reported yet. */
export function DealCapUsage({ entries }: { entries: CapUsageEntry[] }) {
  return (
    <ul className="space-y-0.5 text-xs tabular-nums text-[var(--muted-foreground)]">
      {entries.map((entry, i) => {
        const left = entry.used != null ? entry.total - entry.used : null;
        return (
          <li key={i}>
            <span>
              {entry.year}
              {entry.pool ? ` ${entry.pool}` : ""}: {entry.used ?? "?"}/{entry.total} used
              {entry.as_of ? ` (through ${entry.as_of})` : ""}
              {left != null && left >= 1 && left <= 5
                ? ` — ${left} APC${left === 1 ? "" : "s"} left`
                : ""}
            </span>
            {entry.note && <span className="block">{entry.note}</span>}
          </li>
        );
      })}
    </ul>
  );
}
