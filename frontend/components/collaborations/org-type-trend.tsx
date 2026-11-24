"use client";

import { useTranslations } from "next-intl";
import * as React from "react";

import { orgTypeCssVar, useCollabLabels } from "@/components/collaborations/labels";
import { Button } from "@/components/ui/button";
import type { CollaborationTrendYear } from "@/lib/api";

type Scale = "share" | "works";

/** One line per partner organisation type: collaborative works per year
 * with at least one partner of that type, as a count or as a share of that
 * year's collaborative works. A work with partners of two types counts on
 * both lines, so the lines do not add up to the yearly total. */
export function OrgTypeTrend({ trend }: { trend: CollaborationTrendYear[] }) {
  const t = useTranslations("collaborations");
  const labels = useCollabLabels();
  const [scale, setScale] = React.useState<Scale>("share");

  const types = React.useMemo(() => {
    const totals = new Map<string, number>();
    for (const year of trend) {
      for (const [kind, count] of Object.entries(year.by_org_type ?? {})) {
        totals.set(kind, (totals.get(kind) ?? 0) + count);
      }
    }
    return [...totals.entries()].sort((a, b) => b[1] - a[1]).map(([kind]) => kind);
  }, [trend]);

  const value = (year: CollaborationTrendYear, kind: string) => {
    const count = year.by_org_type?.[kind] ?? 0;
    if (scale === "works") return count;
    return year.with_partner ? (count / year.with_partner) * 100 : 0;
  };
  const max =
    scale === "share"
      ? 100
      : Math.max(1, ...trend.flatMap((year) => types.map((kind) => value(year, kind))));
  const format = (v: number) =>
    scale === "share" ? `${v.toFixed(1).replace(/\.0$/, "")}%` : v.toLocaleString("en");

  if (types.length === 0) {
    return <p className="py-8 text-sm text-[var(--muted-foreground)]">{t("overview.typeEmpty")}</p>;
  }

  return (
    <div>
      <div className="mb-3 flex overflow-hidden rounded-[var(--radius)] border border-[var(--input)] w-fit">
        {(["share", "works"] as const).map((option) => (
          <Button
            key={option}
            variant={scale === option ? "secondary" : "ghost"}
            size="sm"
            className="h-7 rounded-none px-2.5 text-xs"
            aria-pressed={scale === option}
            onClick={() => setScale(option)}
          >
            {option === "share" ? t("overview.typeScaleShare") : t("overview.typeScaleWorks")}
          </Button>
        ))}
      </div>
      <div className="flex gap-2">
        <div className="flex h-44 w-12 shrink-0 flex-col justify-between text-right text-[11px] tabular-nums text-[var(--muted-foreground)]">
          <span>{format(max)}</span>
          <span>{format(max / 2)}</span>
          <span>{format(0)}</span>
        </div>
        <div className="min-w-0 flex-1">
          <div className="relative h-44" role="img" aria-label={t("overview.typeChartLabel")}>
            <svg
              viewBox="0 0 100 100"
              preserveAspectRatio="none"
              className="absolute inset-0 size-full overflow-visible"
              aria-hidden
            >
              {[0, 50, 100].map((gy) => (
                <line
                  key={gy}
                  x1={0}
                  x2={100}
                  y1={gy}
                  y2={gy}
                  stroke="var(--border)"
                  strokeWidth={1}
                  vectorEffect="non-scaling-stroke"
                />
              ))}
              {types.map((kind) => (
                <polyline
                  key={kind}
                  fill="none"
                  stroke={orgTypeCssVar(kind)}
                  strokeWidth={2}
                  strokeLinejoin="round"
                  strokeDasharray={kind === "unknown" ? "4 3" : undefined}
                  vectorEffect="non-scaling-stroke"
                  // Each year sits at the centre of an equal-width column,
                  // matching the year labels and hover columns.
                  points={trend
                    .map(
                      (year, idx) =>
                        `${((idx + 0.5) / trend.length) * 100},${100 - (value(year, kind) / max) * 100}`,
                    )
                    .join(" ")}
                />
              ))}
            </svg>
            <div className="absolute inset-0 flex">
              {trend.map((year) => (
                <div
                  key={year.year}
                  className="h-full flex-1 hover:bg-[var(--muted)]/40"
                  title={[
                    t("overview.typeTooltipHead", {
                      year: String(year.year),
                      works: year.with_partner.toLocaleString("en"),
                    }),
                    ...types.map((kind) => `${labels.orgType(kind)}: ${format(value(year, kind))}`),
                  ].join("\n")}
                />
              ))}
            </div>
          </div>
          <div className="mt-1 flex">
            {trend.map((year, idx) => (
              <span
                key={year.year}
                className={`min-w-0 flex-1 overflow-hidden text-center text-[11px] tabular-nums text-[var(--muted-foreground)] ${idx % 2 === 1 ? "max-sm:invisible" : ""}`}
              >
                {year.year}
              </span>
            ))}
          </div>
        </div>
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--muted-foreground)]">
        {types.map((kind) => (
          <li key={kind} className="flex items-center gap-1.5">
            <span
              aria-hidden
              className="inline-block h-0.5 w-3.5 rounded-full"
              style={{ background: orgTypeCssVar(kind) }}
            />
            {labels.orgType(kind)}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-[var(--muted-foreground)]">{t("overview.typeNote")}</p>
    </div>
  );
}
