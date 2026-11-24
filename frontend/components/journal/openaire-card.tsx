"use client";

import { useTranslations } from "next-intl";
import * as React from "react";

import { CollapsibleCard } from "@/components/collapsible-card";
import { MoreToggle } from "@/components/journal/shared";
import { SourceNote } from "@/components/source-note";
import { InsetPanel } from "@/components/sub-panel";
import { Badge } from "@/components/ui/badge";
import { useSiteMeta } from "@/hooks/use-site-meta";
import type { Attribution, OpenaireInfo } from "@/lib/api";

const FUNDER_LIMIT = 10;

/** OpenAIRE Graph cross-check for this journal, over the confirmed-identity
 * facts store: what OpenAIRE matches and what it adds beyond OpenAlex
 * (fulltext links, usage events, diamond OA evidence, subjects, funders). */
export function OpenaireCard({
  openaire,
  note,
}: {
  openaire: OpenaireInfo;
  note: Partial<Attribution>;
}) {
  const t = useTranslations("journals");
  const tc = useTranslations("common");
  const site = useSiteMeta();
  const [showAllFunders, setShowAllFunders] = React.useState(false);

  const kpis: { label: string; value: string; hint?: string; sub?: string }[] = [
    {
      label: t("metrics.openaireLabel"),
      hint: t("metrics.openaireHint", { name: site.name }),
      value: openaire.matched_works.toLocaleString("en"),
    },
    ...(openaire.with_fulltext > 0
      ? [
          {
            label: t("openaire.fulltextLabel"),
            hint: t("openaire.fulltextHint"),
            value: openaire.with_fulltext.toLocaleString("en"),
            sub:
              openaire.matched_works > 0
                ? t("openaire.pctOfMatched", {
                    pct: String(
                      Math.round((openaire.with_fulltext / openaire.matched_works) * 100),
                    ),
                  })
                : undefined,
          },
        ]
      : []),
    ...(openaire.with_usage > 0
      ? [
          {
            label: t("openaire.usageLabel"),
            hint: t("openaire.usageHint"),
            value: openaire.with_usage.toLocaleString("en"),
            sub:
              openaire.matched_works > 0
                ? t("openaire.pctOfMatched", {
                    pct: String(Math.round((openaire.with_usage / openaire.matched_works) * 100)),
                  })
                : undefined,
          },
        ]
      : []),
    ...(openaire.diamond_works > 0
      ? [
          {
            label: t("openaire.diamondLabel"),
            hint: t("openaire.diamondHint"),
            value: openaire.diamond_works.toLocaleString("en"),
            sub:
              openaire.matched_works > 0
                ? t("openaire.pctOfMatched", {
                    pct: String(
                      Math.round((openaire.diamond_works / openaire.matched_works) * 100),
                    ),
                  })
                : undefined,
          },
        ]
      : []),
  ];

  const agree = Math.max(0, openaire.oa_color_total - openaire.oa_color_disagree);
  const agreePct =
    openaire.oa_color_total > 0 ? Math.round((agree / openaire.oa_color_total) * 100) : 0;
  const visibleFunders = showAllFunders
    ? openaire.top_funders
    : openaire.top_funders.slice(0, FUNDER_LIMIT);

  return (
    <CollapsibleCard
      id="openaire"
      title={t("openaire.title")}
      count={openaire.matched_works}
      defaultOpen={false}
      compact
      description={
        <p className="text-xs text-[var(--muted-foreground)]">{t("openaire.description")}</p>
      }
      contentClassName="space-y-3 text-sm"
    >
      <dl
        className={`grid gap-2.5 ${
          kpis.length <= 2 ? "grid-cols-2" : "grid-cols-2 sm:grid-cols-4"
        }`}
      >
        {kpis.map((item) => (
          <div
            key={item.label}
            title={item.hint}
            tabIndex={item.hint ? 0 : undefined}
            className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--muted)]/35 px-3 py-2"
          >
            <dt className="truncate text-[11px] font-medium text-[var(--muted-foreground)]">
              {item.label}
            </dt>
            <dd className="mt-0.5 text-lg font-bold leading-tight tabular-nums text-[var(--foreground)]">
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

      {openaire.oa_color_total > 0 && (
        <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--muted)]/25 px-3 py-2 text-xs text-[var(--muted-foreground)]">
          {openaire.oa_color_disagree === 0
            ? t("openaire.colorAgreeAll", { total: openaire.oa_color_total })
            : t("openaire.colorAgreement", {
                agree,
                total: openaire.oa_color_total,
                disagree: openaire.oa_color_disagree,
                pct: String(agreePct),
              })}
        </div>
      )}

      {(openaire.top_fos.length > 0 || openaire.top_funders.length > 0) && (
        <div
          className={
            openaire.top_fos.length > 0 && openaire.top_funders.length > 0
              ? "grid gap-3 lg:grid-cols-2"
              : ""
          }
        >
          {openaire.top_fos.length > 0 && (
            <InsetPanel
              title={t("openaire.subjectsHeading")}
              count={openaire.top_fos.length}
              bodyClassName="flex flex-wrap items-center gap-1.5 px-3 py-2.5"
            >
              {openaire.top_fos.map((f) => (
                <Badge key={f.subject} variant="muted" className="font-normal normal-case">
                  {f.subject}
                  <span className="ml-1.5 tabular-nums text-[var(--muted-foreground)]">
                    {f.works.toLocaleString("en")}
                  </span>
                </Badge>
              ))}
            </InsetPanel>
          )}

          {openaire.top_funders.length > 0 && (
            <InsetPanel title={t("openaire.fundersHeading")} count={openaire.top_funders.length}>
              <ul className="divide-y divide-[var(--border)] text-xs sm:text-sm">
                {visibleFunders.map((f) => (
                  <li
                    key={f.funder}
                    className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-1.5 first:pt-0 last:pb-0"
                  >
                    <span className="min-w-0 font-medium">{f.funder}</span>
                    <span className="shrink-0 tabular-nums text-xs text-[var(--muted-foreground)]">
                      {t("openaire.funderWorks", { count: f.works })}
                    </span>
                  </li>
                ))}
              </ul>
              {openaire.top_funders.length > FUNDER_LIMIT && (
                <div className="mt-1.5">
                  <MoreToggle
                    open={showAllFunders}
                    onToggle={() => setShowAllFunders((v) => !v)}
                    moreLabel={t("list.showAllCount", { count: openaire.top_funders.length })}
                  />
                </div>
              )}
            </InsetPanel>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-[var(--border)] pt-2.5">
        <SourceNote {...note} codes={note.caveat_codes} howBuilt={tc("sourceNote.explain.works")} />
      </div>
    </CollapsibleCard>
  );
}
