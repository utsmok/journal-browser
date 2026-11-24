"use client";

import { Maximize2, Minimize2 } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { OaTrend } from "@/components/oa-trend";
import { TopicChipList, type TopicChipItem } from "@/components/topic-chips";
import { Card } from "@/components/ui/card";
import type { StatsYear } from "@/lib/api";

export type DetailStatItem = {
  label: string;
  value: React.ReactNode;
  icon?: React.ReactNode;
  hint?: string;
  sub?: React.ReactNode;
};

export type DetailSummaryTopics = {
  label?: string;
  items: TopicChipItem[];
  showCounts?: boolean;
  limit?: number;
  sourceNote?: React.ReactNode;
};

/**
 * Unified "At a Glance" summary block shared across all 6 detail views:
 * compact icon-annotated KPI tiles paired side-by-side with an embedded
 * compact OA trend (plus 1-click Expand toggle for full-width inspection),
 * optional inline topics, and optional compact entity metadata strip.
 */
export function DetailSummaryPanel({
  id = "overview",
  stats,
  belowStats,
  trendStats,
  trendTitle,
  trendSubtitle,
  trendEmpty,
  trendFooter,
  rightSlot,
  topics,
  metaFooter,
}: {
  id?: string;
  stats: DetailStatItem[];
  /** Optional slim bar / breakdown rendered directly below the KPI tiles (e.g. OA mix + quartiles). */
  belowStats?: React.ReactNode;
  trendStats?: StatsYear[];
  trendTitle?: React.ReactNode;
  trendSubtitle?: React.ReactNode;
  trendEmpty?: React.ReactNode;
  trendFooter?: React.ReactNode;
  /** Optional secondary slot next to or below expanded trend (e.g. partner work types). */
  rightSlot?: React.ReactNode;
  /** Optional compact topic strip folded into Overview instead of its own giant card. */
  topics?: DetailSummaryTopics;
  /** Optional compact reference strip (ISSNs, registry links, alternate names, ROR facts). */
  metaFooter?: React.ReactNode;
}) {
  const t = useTranslations("common");
  const [expanded, setExpanded] = React.useState(false);
  const hasTrendPanel = (trendStats !== undefined && trendStats.length > 0) || Boolean(trendEmpty);

  const statsGrid = (
    <div className="space-y-3">
      <dl
        className={`grid gap-2.5 ${
          hasTrendPanel && !expanded
            ? stats.length <= 2 || stats.length === 4
              ? "grid-cols-2"
              : "grid-cols-2 sm:grid-cols-3"
            : stats.length <= 2
              ? "grid-cols-2"
              : stats.length === 3
                ? "grid-cols-2 sm:grid-cols-3"
                : "grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6"
        }`}
      >
        {stats.map((item) => (
          <div
            key={item.label}
            title={item.hint}
            tabIndex={item.hint ? 0 : undefined}
            className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--muted)]/35 px-3 py-2.5"
          >
            <dt className="flex items-center gap-1.5 text-[11px] font-medium text-[var(--muted-foreground)]">
              {item.icon}
              <span className="truncate">{item.label}</span>
            </dt>
            <dd className="mt-1 text-lg font-bold leading-tight tracking-tight tabular-nums text-[var(--foreground)]">
              {item.value}
            </dd>
            {item.sub && (
              <div className="mt-0.5 truncate text-[11px] text-[var(--muted-foreground)]">
                {item.sub}
              </div>
            )}
          </div>
        ))}
      </dl>
      {belowStats}
    </div>
  );

  const trendBox = hasTrendPanel ? (
    <div className="rounded-[var(--radius)] border border-[var(--border)]/80 bg-[var(--muted)]/20 p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="text-xs font-semibold text-[var(--foreground)]">
            {trendTitle ?? t("trend.heading")}
          </div>
          {trendSubtitle && (
            <div className="text-[11px] text-[var(--muted-foreground)]">{trendSubtitle}</div>
          )}
        </div>
        {trendStats && trendStats.length > 0 && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="inline-flex shrink-0 items-center gap-1 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] px-2 py-0.5 text-[11px] font-medium text-[var(--muted-foreground)] hover:border-[var(--primary)] hover:text-[var(--primary-text)]"
            aria-expanded={expanded}
          >
            {expanded ? (
              <>
                <Minimize2 aria-hidden className="size-3" />
                {t("trend.compact")}
              </>
            ) : (
              <>
                <Maximize2 aria-hidden className="size-3" />
                {t("trend.expand")}
              </>
            )}
          </button>
        )}
      </div>
      {trendStats && trendStats.length > 0 ? (
        <OaTrend stats={trendStats} compact={!expanded} />
      ) : (
        trendEmpty
      )}
      {rightSlot && <div className="mt-3 border-t border-[var(--border)] pt-2.5">{rightSlot}</div>}
      {trendFooter && <div className="mt-2">{trendFooter}</div>}
    </div>
  ) : null;

  return (
    <section id={id} className="scroll-mt-16">
      <Card className="p-4">
        {hasTrendPanel && !expanded ? (
          <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
            {statsGrid}
            {trendBox}
          </div>
        ) : (
          <div className="space-y-4">
            {statsGrid}
            {trendBox}
          </div>
        )}
        {topics && topics.items.length > 0 && (
          <div className="mt-3 border-t border-[var(--border)] pt-2.5">
            <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
              <span className="shrink-0 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                {topics.label ?? t("topics.label")}
                {topics.items.length > (topics.limit ?? 8) && (
                  <span className="ml-1 font-normal tabular-nums">
                    ({topics.items.length.toLocaleString("en")})
                  </span>
                )}
              </span>
              <div className="min-w-0 flex-1">
                <TopicChipList
                  items={topics.items}
                  limit={topics.limit ?? 8}
                  showCounts={topics.showCounts ?? true}
                />
              </div>
              {topics.sourceNote && <div className="shrink-0">{topics.sourceNote}</div>}
            </div>
          </div>
        )}
        {metaFooter && (
          <div className="mt-3 border-t border-[var(--border)] pt-2.5 text-xs">{metaFooter}</div>
        )}
      </Card>
    </section>
  );
}
