"use client";

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DealBadge } from "@/components/badges";
import { CollapsibleCard } from "@/components/collapsible-card";
import { DealCapUsage } from "@/components/deal-cap-usage";
import { External } from "@/components/journal/shared";
import { SourceNote } from "@/components/source-note";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { capReached, latestYearUsage } from "@/lib/deal-caps";
import { dealLinkLabel, orderedDealLinks } from "@/lib/deal-links";
import { cleanProse } from "@/lib/utils";
import type { Attribution, DealLink, DealOut } from "@/lib/api";

export function DealPanel({
  id,
  deal,
  attribution,
}: {
  id: string;
  deal: DealOut;
  attribution: Partial<Attribution>;
}) {
  const t = useTranslations("journals");
  const tc = useTranslations("common");
  const site = useSiteMeta();
  const capNumbers = Object.entries(deal.cap_numbers ?? {}).sort(
    (a, b) => (parseInt(a[0], 10) || 0) - (parseInt(b[0], 10) || 0),
  );
  const capUsage = latestYearUsage(deal.cap_usage);
  const capUsageReached = capUsage.some(capReached);
  return (
    <CollapsibleCard
      id={id}
      compact
      title={
        <>
          {t("deal.title")}
          <DealBadge covered capped={capUsageReached} />
          {deal.corresponding_authors_only && (
            <Badge variant="muted" title={t("deal.correspondingOnlyHint", { name: site.name })}>
              {t("deal.correspondingOnly")}
            </Badge>
          )}
          {deal.needs_curation && (
            <Badge
              variant="outline"
              className="border-[var(--primary)] text-[var(--primary-text)] normal-case"
              title={deal.needs_curation_reason ?? undefined}
            >
              {t("deal.curationPending")}
            </Badge>
          )}
        </>
      }
      description={
        <p className="text-sm text-[var(--muted-foreground)]">
          {deal.publisher_name} · {deal.duration_text ?? deal.esac_id}
        </p>
      }
      contentClassName="space-y-4 text-sm"
    >
      {deal.summary && <p className="max-w-prose text-pretty">{cleanProse(deal.summary)}</p>}
      {deal.conditions_text && (
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("deal.costsHeading")}
          </h3>
          <p className="max-w-prose whitespace-pre-line text-pretty">
            {cleanProse(deal.conditions_text)}
          </p>
        </div>
      )}
      {(deal.cap_text || capNumbers.length > 0 || capUsage.length > 0) && (
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("deal.capsHeading")}
          </h3>
          {deal.cap_text && (
            <p className="whitespace-pre-line text-pretty">{cleanProse(deal.cap_text)}</p>
          )}
          {capNumbers.length > 0 && (
            <ul className="mt-1.5 flex flex-wrap gap-1.5">
              {capNumbers.map(([year, count]) => (
                <li
                  key={year}
                  className="rounded-full bg-[var(--muted)] px-2.5 py-0.5 text-xs tabular-nums"
                >
                  {year}: {String(count)}
                </li>
              ))}
            </ul>
          )}
          {capUsage.length > 0 && (
            <div className={capNumbers.length > 0 ? "mt-1.5" : undefined}>
              <DealCapUsage entries={capUsage} />
            </div>
          )}
        </div>
      )}
      {deal.article_types_text && (
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("deal.articleTypesHeading")}
          </h3>
          <p className="text-pretty">{cleanProse(deal.article_types_text)}</p>
        </div>
      )}
      {deal.workflow_text && (
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("deal.workflowHeading")}
          </h3>
          <p className="text-pretty">{cleanProse(deal.workflow_text)}</p>
        </div>
      )}
      <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-[var(--border)] pt-3">
        {deal.links?.length ? (
          orderedDealLinks(deal.links)
            .filter((link): link is DealLink & { url: string } => !!link.url)
            .map((link) => (
              <External key={`${link.category}-${link.url}`} href={link.url}>
                {dealLinkLabel(tc, link)}
              </External>
            ))
        ) : (
          // Old backend: no links[] yet; fall back to the flat URL fields.
          <>
            {deal.openaccess_nl_url && (
              <External href={deal.openaccess_nl_url}>{t("deal.openaccessNlLink")}</External>
            )}
            {deal.contract_url && (
              <External href={deal.contract_url}>{t("deal.contractLink")}</External>
            )}
            {deal.jct_data_url && <External href={deal.jct_data_url}>{t("deal.jctLink")}</External>}
          </>
        )}
        <SourceNote
          {...attribution}
          codes={attribution.caveat_codes}
          howBuilt={tc("sourceNote.explain.deals")}
        />
      </div>
    </CollapsibleCard>
  );
}
