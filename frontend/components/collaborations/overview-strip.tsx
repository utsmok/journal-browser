"use client";

import { useTranslations } from "next-intl";
import * as React from "react";

import { OrgTypeTrend } from "@/components/collaborations/org-type-trend";
import { CollapsibleCard } from "@/components/collapsible-card";
import { GapCsvButton } from "@/components/gap-csv-button";
import { OaTrend } from "@/components/oa-trend";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useSiteMeta } from "@/hooks/use-site-meta";
import type { CollaborationSearchResponse, CollaborationTrendYear, StatsYear } from "@/lib/api";

function pct(part: number, whole: number): string {
  if (!whole) return "0";
  const value = (part / whole) * 100;
  return value < 0.1 && value > 0 ? "<0.1" : value.toFixed(1).replace(/\.0$/, "");
}

function GeoTrendChart({
  trend,
  instShort,
}: {
  trend: CollaborationTrendYear[];
  instShort: string;
}) {
  const t = useTranslations("collaborations");
  const max = Math.max(
    1,
    ...trend.map((y) => Math.max(y.domestic, y.international, y.with_partner)),
  );
  return (
    <div>
      <div className="flex h-44 items-end gap-2" role="img" aria-label={t("overview.trendTitle")}>
        {trend.map((row, idx) => {
          const domH = row.domestic > 0 ? Math.max((row.domestic / max) * 100, 2) : 0;
          const intlH = row.international > 0 ? Math.max((row.international / max) * 100, 2) : 0;
          return (
            <div
              key={row.year}
              className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1 overflow-hidden"
              title={`${row.year}: ${row.with_partner.toLocaleString("en")} collab (${row.international.toLocaleString("en")} international, ${row.domestic.toLocaleString("en")} domestic) of ${row.total_works.toLocaleString("en")} ${instShort} works`}
            >
              <span className="max-w-full overflow-hidden text-[11px] tabular-nums text-[var(--muted-foreground)]">
                {row.with_partner > 0 ? row.with_partner.toLocaleString("en") : ""}
              </span>
              <div className="flex h-full w-full max-w-12 items-end justify-center gap-0.5">
                <div
                  className="w-1/2 rounded-t bg-[var(--secondary)] dark:bg-sky-400/80"
                  style={{ height: `${intlH}%` }}
                />
                <div
                  className="w-1/2 rounded-t bg-[var(--primary)]"
                  style={{ height: `${domH}%` }}
                />
              </div>
              <span
                className={`max-w-full overflow-hidden text-[11px] tabular-nums text-[var(--muted-foreground)] ${idx % 2 === 1 ? "max-sm:hidden" : ""}`}
              >
                {row.year}
              </span>
            </div>
          );
        })}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--muted-foreground)]">
        <li className="flex items-center gap-1.5">
          <span
            aria-hidden
            className="inline-block size-2.5 rounded-full bg-[var(--secondary)] dark:bg-sky-400/80"
          />
          {t("overview.internationalLabel")}
        </li>
        <li className="flex items-center gap-1.5">
          <span aria-hidden className="inline-block size-2.5 rounded-full bg-[var(--primary)]" />
          {t("overview.domestic")}
        </li>
      </ul>
    </div>
  );
}

const TREND_MODES = ["geo", "type", "oa"] as const;
type TrendMode = (typeof TREND_MODES)[number];

/** Headline KPI strip + collapsible trend chart for policy & strategy overview. */
export function CollaborationOverview({
  data,
  trendCsvHref,
}: {
  data: CollaborationSearchResponse;
  trendCsvHref: string;
}) {
  const t = useTranslations("collaborations");
  const site = useSiteMeta();
  const [trendMode, setTrendMode] = React.useState<TrendMode>("geo");

  const collabPct = pct(data.works_with_partner, data.total_works);
  const intlPct = pct(data.international_works, data.works_with_partner);
  const oaPct = pct(data.oa_works, data.works_with_partner);

  const oaStats: StatsYear[] = React.useMemo(
    () =>
      data.trend.map((y) => ({
        year: y.year,
        works_count: y.with_partner,
        works_count_source: "pure_canon",
        oa_gold: y.oa_gold,
        oa_diamond: y.oa_diamond,
        oa_hybrid: y.oa_hybrid,
        oa_green: y.oa_green,
        oa_bronze: y.oa_bronze,
        oa_closed: y.oa_closed,
      })),
    [data.trend],
  );

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardContent className="p-4">
            <p className="text-xs font-medium text-[var(--muted-foreground)]">
              {t("overview.partners")}
            </p>
            <p className="mt-1 text-2xl font-bold tabular-nums">
              {data.total_partners.toLocaleString("en")}
            </p>
            <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
              {t("overview.partnersSub")}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs font-medium text-[var(--muted-foreground)]">
              {t("overview.collabWorks")}
            </p>
            <p className="mt-1 text-2xl font-bold tabular-nums">
              {data.works_with_partner.toLocaleString("en")}
            </p>
            <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
              {t("overview.collabShare", {
                share: collabPct,
                total: data.total_works.toLocaleString("en"),
                inst: site.short,
              })}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs font-medium text-[var(--muted-foreground)]">
              {t("overview.international")}
            </p>
            <p className="mt-1 text-2xl font-bold tabular-nums">
              {data.international_works.toLocaleString("en")}
            </p>
            <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
              {t("overview.internationalSub", {
                share: intlPct,
                domestic: data.domestic_works.toLocaleString("en"),
              })}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs font-medium text-[var(--muted-foreground)]">
              {t("overview.oaRate")}
            </p>
            <p className="mt-1 text-2xl font-bold tabular-nums">{oaPct}%</p>
            <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
              {t("overview.oaSub", {
                oa: data.oa_works.toLocaleString("en"),
                closed: data.closed_works.toLocaleString("en"),
              })}
            </p>
          </CardContent>
        </Card>
      </div>

      {data.trend.length > 1 && (
        <CollapsibleCard
          id="collab-trend"
          title={t("overview.trendTitle")}
          defaultOpen={false}
          description={
            <div className="mt-2 flex w-fit max-w-full flex-wrap overflow-hidden rounded-[var(--radius)] border border-[var(--input)]">
              {TREND_MODES.map((mode) => (
                <Button
                  key={mode}
                  variant={trendMode === mode ? "secondary" : "ghost"}
                  size="sm"
                  className="rounded-none px-2.5 min-[1024px]:h-7 min-[1024px]:text-xs"
                  aria-pressed={trendMode === mode}
                  onClick={() => setTrendMode(mode)}
                >
                  {t(`overview.trendMode.${mode}`)}
                </Button>
              ))}
            </div>
          }
        >
          {trendMode === "geo" && <GeoTrendChart trend={data.trend} instShort={site.short} />}
          {trendMode === "type" && <OrgTypeTrend trend={data.trend} />}
          {trendMode === "oa" && <OaTrend stats={oaStats} />}
          <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2">
            <GapCsvButton href={trendCsvHref} label={t("overview.trendCsv")} />
            <p className="text-xs text-[var(--muted-foreground)]">{t("overview.trendCsvNote")}</p>
          </div>
        </CollapsibleCard>
      )}
    </div>
  );
}
