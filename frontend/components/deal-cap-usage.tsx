import { useTranslations } from "next-intl";

import type { CapUsageEntry } from "@/lib/deal-caps";

/** One line per latest-year cap usage entry, plus remaining APCs when the
 * cap is nearly exhausted. `?` marks a year whose used count the library
 * has not reported yet. */
export function DealCapUsage({ entries }: { entries: CapUsageEntry[] }) {
  const t = useTranslations("journals");
  return (
    <ul className="space-y-0.5 text-xs tabular-nums text-[var(--muted-foreground)]">
      {entries.map((entry, i) => {
        const left = entry.used != null ? entry.total - entry.used : null;
        return (
          <li key={i}>
            <span>
              {t("dealCapUsage.line", {
                year: String(entry.year),
                pool: entry.pool ? ` ${entry.pool}` : "",
                used: entry.used == null ? "?" : String(entry.used),
                total: String(entry.total),
              })}
              {entry.as_of ? ` ${t("dealCapUsage.through", { date: entry.as_of })}` : ""}
              {left != null && left >= 1 && left <= 5
                ? t("dealCapUsage.left", { count: left })
                : ""}
            </span>
            {entry.note && <span className="block">{entry.note}</span>}
          </li>
        );
      })}
    </ul>
  );
}
