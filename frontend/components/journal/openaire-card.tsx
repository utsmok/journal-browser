"use client";

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { CollapsibleCard } from "@/components/collapsible-card";
import { Metric } from "@/components/journal/shared";
import { SourceNote } from "@/components/source-note";
import { useSiteMeta } from "@/hooks/use-site-meta";
import type { Attribution, OpenaireInfo } from "@/lib/api";

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
  const site = useSiteMeta();
  return (
    <CollapsibleCard
      id="openaire"
      title={t("openaire.title")}
      description={
        <p className="text-sm text-[var(--muted-foreground)]">{t("openaire.description")}</p>
      }
      contentClassName="space-y-4 text-sm"
    >
      {/* The OpenAIRE usage counts exist for a small share of works; a 0
          means "no data", so those tiles stay hidden instead of showing 0. */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Metric
          label={t("metrics.openaireLabel")}
          hint={t("metrics.openaireHint", { name: site.name })}
          value={openaire.matched_works.toLocaleString("en")}
        />
        {openaire.with_fulltext > 0 && (
          <Metric
            label={t("openaire.fulltextLabel")}
            hint={t("openaire.fulltextHint")}
            value={openaire.with_fulltext.toLocaleString("en")}
          />
        )}
        {openaire.with_usage > 0 && (
          <Metric
            label={t("openaire.usageLabel")}
            hint={t("openaire.usageHint")}
            value={openaire.with_usage.toLocaleString("en")}
          />
        )}
        {openaire.diamond_works > 0 && (
          <Metric
            label={t("openaire.diamondLabel")}
            hint={t("openaire.diamondHint")}
            value={openaire.diamond_works.toLocaleString("en")}
          />
        )}
      </div>
      {openaire.oa_color_total > 0 && (
        <p className="text-xs text-[var(--muted-foreground)]">
          {t("openaire.colorCheck", {
            agree: openaire.oa_color_total - openaire.oa_color_disagree,
            total: openaire.oa_color_total,
            disagree: openaire.oa_color_disagree,
          })}
        </p>
      )}
      {openaire.top_fos.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {openaire.top_fos.map((f) => (
            <Badge key={f.subject} variant="outline" className="font-normal normal-case">
              {f.subject}
              <span className="ml-1.5 tabular-nums text-[var(--muted-foreground)]">
                {f.works.toLocaleString("en")}
              </span>
            </Badge>
          ))}
        </div>
      )}
      {openaire.top_funders.length > 0 && (
        <ul className="divide-y divide-[var(--border)]">
          {openaire.top_funders.map((f) => (
            <li
              key={f.funder}
              className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-1.5 first:pt-0 last:pb-0"
            >
              <span>{f.funder}</span>
              <span className="tabular-nums text-xs text-[var(--muted-foreground)]">
                {t("openaire.funderWorks", { count: f.works })}
              </span>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-[var(--border)] pt-3">
        <SourceNote {...note} codes={note.caveat_codes} />
      </div>
    </CollapsibleCard>
  );
}
