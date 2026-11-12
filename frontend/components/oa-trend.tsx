"use client";

import { OA_STATUS_META, OA_STATUS_ORDER } from "@/components/badges";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { useTranslations } from "next-intl";
import type { StatsYear } from "@/lib/api";

const STATUS_LABEL_KEYS: Record<string, string> = {
  gold: "trend.statusGold",
  hybrid: "trend.statusHybrid",
  green: "trend.statusGreen",
  bronze: "trend.statusBronze",
  diamond: "trend.statusDiamond",
  closed: "trend.statusClosed",
};

/**
 * Hand-rolled stacked per-year OA-status chart (no chart library), in the
 * StatBars spirit. One column per year; segments stack gold (bottom) →
 * closed (top) and sum to that year's works_count.
 */
export function OaTrend({ stats }: { stats: StatsYear[] }) {
  const site = useSiteMeta();
  const t = useTranslations("common");
  const total = (s: StatsYear) => OA_STATUS_ORDER.reduce((acc, k) => acc + (s[`oa_${k}`] ?? 0), 0);
  const max = Math.max(1, ...stats.map(total));
  const currentYear = new Date().getFullYear();
  if (stats.length === 0 || stats.every((s) => total(s) === 0))
    return <p className="py-8 text-sm text-[var(--muted-foreground)]">{t("trend.noWorks")}</p>;
  return (
    <div>
      <div
        className="flex h-44 items-end gap-2"
        role="img"
        aria-label={t("trend.chartLabel", { short: site.short })}
      >
        {stats.map((s) => {
          const count = total(s);
          return (
            <div
              key={s.year}
              className="flex h-full flex-1 flex-col items-center justify-end gap-1"
            >
              <span className="text-[11px] tabular-nums text-[var(--muted-foreground)]">
                {count > 0 ? count : ""}
              </span>
              <div
                className="flex w-full max-w-12 flex-col-reverse overflow-hidden rounded-t"
                style={{ height: `${Math.max((count / max) * 100, count > 0 ? 2 : 0)}%` }}
                title={t("trend.yearTitle", { year: String(s.year), count: String(count) })}
              >
                {OA_STATUS_ORDER.map((status) => {
                  const n = s[`oa_${status}`] ?? 0;
                  if (n === 0) return null;
                  // flexGrow splits the column exactly proportionally; fixed
                  // percentage heights would round and leave gaps.
                  return (
                    <div
                      key={status}
                      className={OA_STATUS_META[status].bar}
                      style={{ flexGrow: n, flexBasis: 0 }}
                      title={t("trend.segmentTitle", {
                        year: String(s.year),
                        label: t(STATUS_LABEL_KEYS[status]),
                        count: String(n),
                      })}
                    />
                  );
                })}
              </div>
              <span className="text-[11px] tabular-nums text-[var(--muted-foreground)]">
                {s.year}
                {s.year === currentYear && <span title={t("trend.yearInProgress")}>*</span>}
              </span>
            </div>
          );
        })}
      </div>
      {/* The chart is role="img"; this transcript carries the per-year data. */}
      <ul className="sr-only">
        {stats.map((s) => {
          const breakdown = OA_STATUS_ORDER.filter((k) => (s[`oa_${k}`] ?? 0) > 0)
            .map((k) =>
              t("trend.srStatus", {
                label: t(STATUS_LABEL_KEYS[k]),
                count: String(s[`oa_${k}`] ?? 0),
              }),
            )
            .join(", ");
          return (
            <li key={s.year}>
              {t("trend.srWorks", { year: String(s.year), total: String(total(s)) })}
              {breakdown ? ` ${breakdown}` : ""}
            </li>
          );
        })}
      </ul>
      <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-[var(--muted-foreground)]">
        {OA_STATUS_ORDER.map((status) => (
          <li key={status} className="flex items-center gap-1.5">
            <span
              aria-hidden
              className={`inline-block size-2.5 rounded-full ${OA_STATUS_META[status].bar}`}
            />
            {t(STATUS_LABEL_KEYS[status])}
          </li>
        ))}
        {stats.some((s) => s.year === currentYear) && <li>{t("trend.yearInProgressLegend")}</li>}
      </ul>
      <p className="mt-1.5 text-xs text-[var(--muted-foreground)]">{t("trend.bronzeNote")}</p>
    </div>
  );
}
