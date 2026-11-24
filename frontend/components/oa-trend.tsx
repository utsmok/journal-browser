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
export function OaTrend({ stats, compact = false }: { stats: StatsYear[]; compact?: boolean }) {
  const site = useSiteMeta();
  const t = useTranslations("common");
  const total = (s: StatsYear) => OA_STATUS_ORDER.reduce((acc, k) => acc + (s[`oa_${k}`] ?? 0), 0);
  const max = Math.max(1, ...stats.map(total));
  const currentYear = new Date().getFullYear();
  if (stats.length === 0 || stats.every((s) => total(s) === 0))
    return (
      <p className={`${compact ? "py-4" : "py-8"} text-sm text-[var(--muted-foreground)]`}>
        {t("trend.noWorks")}
      </p>
    );
  const hideBarCounts = compact && stats.length > 8;
  return (
    <div>
      <div
        className={`flex items-end ${compact ? "h-24 gap-1" : "h-44 gap-2"}`}
        role="img"
        aria-label={t("trend.chartLabel", { short: site.short })}
      >
        {stats.map((s, i) => {
          const count = total(s);
          return (
            <div
              key={s.year}
              className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-0.5 overflow-hidden"
            >
              {!hideBarCounts && (
                <span className="max-w-full overflow-hidden text-[10px] tabular-nums text-[var(--muted-foreground)]">
                  {count > 0 ? count : ""}
                </span>
              )}
              <div
                className={`flex w-full ${compact ? "max-w-8" : "max-w-12"} flex-col-reverse overflow-hidden rounded-t`}
                style={{ height: `${Math.max((count / max) * 100, count > 0 ? 2 : 0)}%` }}
                title={t("trend.yearTitle", { year: String(s.year), count: String(count) })}
              >
                {OA_STATUS_ORDER.map((status) => {
                  const n = s[`oa_${status}`] ?? 0;
                  if (n === 0) return null;
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
              <span
                className={`max-w-full overflow-hidden ${compact ? "text-[10px]" : "text-[11px]"} tabular-nums text-[var(--muted-foreground)] ${i % 2 === 1 ? "max-sm:hidden" : ""}`}
              >
                {compact && stats.length > 9 ? `'${String(s.year).slice(-2)}` : s.year}
                {s.year === currentYear && <span title={t("trend.yearInProgress")}>*</span>}
              </span>
            </div>
          );
        })}
      </div>
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
      <ul
        className={`mt-2 flex flex-wrap ${compact ? "gap-x-2.5 gap-y-0.5 text-[11px]" : "gap-x-3 gap-y-1 text-xs"} text-[var(--muted-foreground)]`}
      >
        {OA_STATUS_ORDER.map((status) => (
          <li
            key={status}
            className="flex items-center gap-1"
            title={status === "bronze" && compact ? t("trend.bronzeNote") : undefined}
          >
            <span
              aria-hidden
              className={`inline-block size-2 rounded-full ${OA_STATUS_META[status].bar}`}
            />
            {t(STATUS_LABEL_KEYS[status])}
          </li>
        ))}
        {stats.some((s) => s.year === currentYear) && <li>{t("trend.yearInProgressLegend")}</li>}
      </ul>
      {!compact && (
        <p className="mt-1.5 text-xs text-[var(--muted-foreground)]">{t("trend.bronzeNote")}</p>
      )}
    </div>
  );
}
