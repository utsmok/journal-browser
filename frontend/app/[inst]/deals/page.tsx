"use client";

import { ChevronDown, CircleCheck, CircleX, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import type { UseQueryResult } from "@tanstack/react-query";

import { SourceNote } from "@/components/source-note";
import { Badge } from "@/components/ui/badge";
import { CollapsibleCard } from "@/components/collapsible-card";
import { Button } from "@/components/ui/button";
import { DealBadge } from "@/components/badges";
import { DealCapUsage } from "@/components/deal-cap-usage";
import { useDeals } from "@/hooks/use-api";
import { useInstitution } from "@/hooks/use-institution";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { errorMessage, type DealLink, type DealOut } from "@/lib/api";
import { capReached, latestYearUsage } from "@/lib/deal-caps";
import { dealLinkLabel, displayPublisherName, orderedDealLinks } from "@/lib/deal-links";
import { formatApc, formatEur } from "@/lib/format";
import { cleanProse } from "@/lib/utils";

/** One card line for a condition the deal either has or not. */
function ConditionLine({ ok, label }: { ok: boolean; label: string }) {
  const t = useTranslations("deals");
  const Icon = ok ? CircleCheck : CircleX;
  return (
    <span
      className={`inline-flex items-center gap-1 ${ok ? "" : "text-[var(--muted-foreground)]"}`}
      title={ok ? t("condition.applies") : t("condition.doesNotApply")}
    >
      <Icon aria-hidden className="size-3.5" />
      {label}
    </span>
  );
}

/** First sentence or two of the scraped summary, for the card description. */
function summaryPreview(text: string): string {
  const sentences = text.match(/[^.!?]+[.!?]+(\s|$)/g) ?? [text];
  const preview = sentences.slice(0, 2).join(" ").trim();
  return preview.length > 0 ? preview : text.trim();
}

function DealCard({ deal, archived }: { deal: DealOut; archived?: boolean }) {
  const t = useTranslations("deals");
  const tc = useTranslations("common");
  const site = useSiteMeta();
  const inst = useInstitution();
  const capNumbers = Object.entries(deal.cap_numbers ?? {}).sort(
    (a, b) => (parseInt(a[0], 10) || 0) - (parseInt(b[0], 10) || 0),
  );
  const oaPerYear = Object.entries(deal.per_year_oa_counts ?? {}).sort(
    (a, b) => (parseInt(a[0], 10) || 0) - (parseInt(b[0], 10) || 0),
  );
  const summary = deal.summary ? cleanProse(deal.summary) : null;
  const preview = summary ? summaryPreview(summary) : null;
  const duration = deal.duration_text ?? `${deal.start_year ?? "?"}–${deal.end_year ?? "?"}`;
  const latestOa = oaPerYear.at(-1);
  const latestCap = capNumbers.at(-1);
  const capUsage = latestYearUsage(deal.cap_usage);
  const capUsageReached = capUsage.some(capReached);
  const prose = (
    <>
      {deal.conditions_text && (
        <div>
          <p className="font-medium">{t("card.conditions")}</p>
          <p className="mt-0.5 max-w-prose text-pretty">{cleanProse(deal.conditions_text)}</p>
        </div>
      )}
      {deal.workflow_text && (
        <div>
          <p className="font-medium">{t("card.workflow")}</p>
          <p className="mt-0.5 max-w-prose text-pretty">{cleanProse(deal.workflow_text)}</p>
        </div>
      )}
      {deal.article_types_text && (
        <div>
          <p className="font-medium">{t("card.articleTypes")}</p>
          <p className="mt-0.5 max-w-prose text-pretty">{cleanProse(deal.article_types_text)}</p>
        </div>
      )}
    </>
  );
  const hasProse = deal.conditions_text || deal.workflow_text || deal.article_types_text;
  // Collapsible like the detail page's deal panels: the scraped prose runs
  // long, and a 16-card page should not force all of it on the reader.
  return (
    <CollapsibleCard
      id={`deal-${deal.id}`}
      title={
        <>
          {displayPublisherName(deal.publisher_name) || t("card.fallbackTitle", { id: deal.id })}
          {archived ? (
            <Badge variant="muted" title={t("card.archiveBadgeTitle")}>
              {t("card.archiveBadge")}
            </Badge>
          ) : (
            <Badge
              variant="secondary"
              title={t("card.currentBadgeTitle", { institution: site.name })}
            >
              {t("card.currentBadge")}
            </Badge>
          )}
          {capUsageReached && <DealBadge covered capped />}
          {deal.needs_curation && (
            <Badge
              variant="outline"
              className="border-[var(--primary)] text-[var(--primary-text)] normal-case"
              title={deal.needs_curation_reason ?? undefined}
            >
              {t("card.curationPending")}
            </Badge>
          )}
        </>
      }
      description={
        <p className="line-clamp-2 text-sm text-[var(--muted-foreground)]">
          {preview ?? t("card.descriptionFallback", { duration, count: deal.journal_count })}
        </p>
      }
      contentClassName="space-y-3 text-sm"
    >
      {/* Key figures at a glance; full per-year breakdowns follow below. */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums text-[var(--muted-foreground)]">
        <span>{duration}</span>
        <span>{t("card.journals", { count: deal.journal_count })}</span>
        {latestOa && (
          <span>{t("card.oaInYear", { count: Number(latestOa[1]), year: latestOa[0] })}</span>
        )}
        {latestCap && (
          <span>{t("card.capUsage", { year: latestCap[0], count: Number(latestCap[1]) })}</span>
        )}
        {deal.apc_n > 0 && (
          <span>{t("card.apcTotal", { total: formatEur(deal.apc_euro_total) })}</span>
        )}
        {deal.apc_n > 1 && (
          <span>{t("card.apcMean", { mean: formatApc(deal.apc_euro_total / deal.apc_n) })}</span>
        )}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
        <ConditionLine
          ok={deal.corresponding_authors_only === true}
          label={t("condition.correspondingOnly")}
        />
        <ConditionLine
          ok={Boolean(deal.cap_text || capNumbers.length > 0)}
          label={t("condition.capped")}
        />
      </div>
      {summary && summary !== preview && <p className="max-w-prose text-pretty">{summary}</p>}
      {deal.cap_text && (
        <p className="max-w-prose text-pretty">
          <span className="font-medium">{t("card.capsLabel")} </span>
          {cleanProse(deal.cap_text)}
        </p>
      )}
      {capNumbers.length > 0 && (
        <div>
          <p className="mb-1 text-xs text-[var(--muted-foreground)]">{t("card.capUsagePerYear")}</p>
          <ul className="flex flex-wrap gap-1.5">
            {capNumbers.map(([year, count]) => (
              <li
                key={year}
                className="rounded-full bg-[var(--muted)] px-2.5 py-0.5 text-xs tabular-nums"
              >
                {t("card.yearCount", { year, count: Number(count) })}
              </li>
            ))}
          </ul>
        </div>
      )}
      {capUsage.length > 0 && <DealCapUsage entries={capUsage} />}
      {oaPerYear.length > 0 && (
        <div>
          <p className="mb-1 text-xs text-[var(--muted-foreground)]">{t("card.oaPerYear")}</p>
          <ul className="flex flex-wrap gap-1.5">
            {oaPerYear.map(([year, count]) => (
              <li
                key={year}
                className="rounded-full bg-[var(--muted)] px-2.5 py-0.5 text-xs tabular-nums"
              >
                {t("card.yearCount", { year, count: Number(count) })}
              </li>
            ))}
          </ul>
        </div>
      )}
      {hasProse && (
        <details className="text-sm">
          <summary className="cursor-pointer text-[var(--primary-text)] hover:underline">
            {t("card.detailsSummary")}
          </summary>
          <div className="mt-2 space-y-2">{prose}</div>
        </details>
      )}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {!archived && (
          <Link
            href={`/${inst}/journals?deal=covered`}
            className="inline-flex items-center gap-1 text-[var(--primary-text)] hover:underline"
          >
            {t("card.coveredJournals")}
          </Link>
        )}
        {deal.links?.length ? (
          orderedDealLinks(deal.links)
            .filter((link): link is DealLink & { url: string } => !!link.url)
            .map((link) => (
              <a
                key={`${link.category}-${link.url}`}
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-[var(--primary-text)] hover:underline"
              >
                {dealLinkLabel(tc, link)} <ExternalLink aria-hidden className="size-3" />
              </a>
            ))
        ) : (
          // Old backend: no links[] yet; fall back to the flat URL fields.
          <>
            {deal.openaccess_nl_url && (
              <a
                href={deal.openaccess_nl_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-[var(--primary-text)] hover:underline"
              >
                {t("card.openaccessNl")} <ExternalLink aria-hidden className="size-3" />
              </a>
            )}
            {deal.contract_url && (
              <a
                href={deal.contract_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-[var(--primary-text)] hover:underline"
              >
                {t("card.contract")} <ExternalLink aria-hidden className="size-3" />
              </a>
            )}
            {deal.jct_data_url && (
              <a
                href={deal.jct_data_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-[var(--primary-text)] hover:underline"
              >
                {t("card.jctData")} <ExternalLink aria-hidden className="size-3" />
              </a>
            )}
          </>
        )}
      </div>
    </CollapsibleCard>
  );
}

export default function DealsPage() {
  const t = useTranslations("deals");
  const tc = useTranslations("common");
  const site = useSiteMeta();
  const current = useDeals("current");
  const archive = useDeals("archive");
  const [archiveOpen, setArchiveOpen] = useState(false);
  const section = (label: string, query: UseQueryResult<DealOut[], Error>, archived?: boolean) => (
    <section className="mb-10">
      <h2 className="mb-1 text-xl font-bold">{label}</h2>
      <p className="mb-4 text-sm text-[var(--muted-foreground)]">
        {query.data
          ? t("section.count", { count: query.data.length, institution: site.short })
          : query.isError
            ? t("section.loadFailed")
            : t("section.loading")}
      </p>
      {query.isError ? (
        <div>
          <p className="text-[var(--destructive)]">{errorMessage(tc, query.error)}</p>
          <Button variant="outline" size="sm" className="mt-2" onClick={() => query.refetch()}>
            {t("section.retry")}
          </Button>
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {(query.data ?? []).map((deal) => (
            <DealCard key={deal.id} deal={deal} archived={archived} />
          ))}
        </div>
      )}
    </section>
  );

  // Archived deals are rarely consulted, so they load behind a toggle; the
  // count rides in the heading so readers know what is folded away.
  const archiveCount = archive.data?.length ?? 0;
  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <h1 className="mb-2 text-3xl font-bold">{t("page.heading")}</h1>
      <p className="mb-8 max-w-2xl text-[var(--muted-foreground)]">
        {t("page.intro", { institution: site.short })}
      </p>
      {section(t("section.current"), current)}
      {archive.data ? (
        archiveCount > 0 ? (
          <section className="mb-10">
            <h2 className="text-xl font-bold">
              <button
                type="button"
                aria-expanded={archiveOpen}
                aria-controls="archive-deals"
                onClick={() => setArchiveOpen((open) => !open)}
                className="inline-flex items-center gap-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--primary)]"
              >
                {t("section.archiveToggle", { count: archiveCount })}
                <ChevronDown
                  aria-hidden
                  className={`size-4 text-[var(--muted-foreground)] transition-transform ${archiveOpen ? "" : "-rotate-90"}`}
                />
              </button>
            </h2>
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">
              {t("section.archiveIntro", { institution: site.short })}
            </p>
            {archiveOpen && (
              <div id="archive-deals" className="mt-4 grid gap-4 lg:grid-cols-2">
                {archive.data.map((deal) => (
                  <DealCard key={deal.id} deal={deal} archived />
                ))}
              </div>
            )}
          </section>
        ) : (
          <section className="mb-10">
            <h2 className="mb-1 text-xl font-bold">{t("section.archive")}</h2>
            <p className="text-sm text-[var(--muted-foreground)]">{t("section.archiveEmpty")}</p>
          </section>
        )
      ) : archive.isError ? (
        <section className="mb-10">
          <h2 className="mb-1 text-xl font-bold">{t("section.archive")}</h2>
          <p className="text-[var(--destructive)]">{errorMessage(tc, archive.error)}</p>
          <Button variant="outline" size="sm" className="mt-2" onClick={() => archive.refetch()}>
            {t("section.retry")}
          </Button>
        </section>
      ) : null}
      <SourceNote
        source="JCT · openaccess.nl"
        url="https://journalcheckertool.org/transformative-agreements/"
        codes={["jct-coverage", "openaccess-nl-prose", "issn-mapping"]}
      />
    </div>
  );
}
