"use client";

import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import { ApcText } from "@/components/apc-text";
import { DealBadge, OaTypeBadge, QuartileBadge } from "@/components/badges";
import { CardPager } from "@/components/card-pager";
import { CollapsibleCard } from "@/components/collapsible-card";
import { CrisGapsSection } from "@/components/cris-gaps-section";
import { ACCESS_TEXT, ApcGlyph, DataIcon, DealGlyph, WorksGlyph } from "@/components/data-icons";
import { DetailSummaryPanel } from "@/components/detail-summary";
import { SectionNav } from "@/components/journal/section-nav";
import { MoreToggle } from "@/components/journal/shared";
import { OaCompositionBar, OaCompositionLegend } from "@/components/oa-composition";
import { DetailSkeleton, ErrorPanel } from "@/components/states";
import { InsetPanel } from "@/components/sub-panel";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { usePublisher } from "@/hooks/use-api";
import { useInstitution } from "@/hooks/use-institution";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { useYearRange } from "@/hooks/use-year-filter";
import {
  errorMessage,
  encodeNamePath,
  type DealOut,
  type PublisherDetailResponse,
  type PublisherListItem,
} from "@/lib/api";
import { capReached, latestYearUsage } from "@/lib/deal-caps";
import { formatEur } from "@/lib/format";
import { dealLinkLabel, displayPublisherName, orderedDealLinks } from "@/lib/deal-links";

const PAGE_SIZE = 10;
const SUBTABLE_CAP = 10;

function dealConditionsUrl(deal: DealOut): string | null {
  const links = deal.links ? orderedDealLinks(deal.links) : [];
  return links[0]?.url ?? deal.contract_url ?? null;
}

function DealRow({ deal }: { deal: DealOut }) {
  const t = useTranslations("publishers");
  const tc = useTranslations("common");
  const conditionsUrl = dealConditionsUrl(deal);
  const capUsage = latestYearUsage(deal.cap_usage);
  const capUsageReached = capUsage.some(capReached);
  return (
    <li className="py-2 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <DealBadge covered capped={capUsageReached} />
        <span className="font-medium">
          {displayPublisherName(deal.publisher_name) || t("detail.unnamedDeal")}
        </span>
        {deal.covers_in_group != null && (
          <span className="text-xs text-[var(--muted-foreground)]">
            {t("detail.dealCoversGroup", { count: deal.covers_in_group })}
          </span>
        )}
        {deal.duration_text && (
          <span className="text-xs text-[var(--muted-foreground)]">{deal.duration_text}</span>
        )}
        {deal.corresponding_authors_only && (
          <span className="text-xs text-[var(--muted-foreground)]">
            {t("detail.correspondingOnly")}
          </span>
        )}
        {conditionsUrl && (
          <a
            href={conditionsUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex min-h-11 min-w-11 items-center gap-1 text-xs text-[var(--primary-text)] underline-offset-2 hover:underline min-[1024px]:min-h-0 min-[1024px]:min-w-0"
          >
            {deal.links?.length
              ? dealLinkLabel(tc, orderedDealLinks(deal.links)[0])
              : t("detail.contract")}{" "}
            <ExternalLink aria-hidden className="size-3 shrink-0" />
          </a>
        )}
      </div>
      {deal.conditions_text && (
        <p className="mt-1 max-w-prose whitespace-pre-line text-pretty text-xs text-[var(--muted-foreground)]">
          {deal.conditions_text}
        </p>
      )}
    </li>
  );
}

/** Slim composition bar + compact quartile pill row embedded inside Overview. */
function PublisherBreakdowns({ publisher }: { publisher: PublisherListItem }) {
  const t = useTranslations("publishers");
  return (
    <div className="space-y-2.5 border-t border-[var(--border)] pt-3">
      <div className="space-y-1.5">
        <div className="flex items-center justify-between gap-2 text-xs font-medium text-[var(--muted-foreground)]">
          <span>{t("detail.composition")}</span>
          <span className="tabular-nums">{publisher.n_journals.toLocaleString("en")}</span>
        </div>
        <OaCompositionBar
          counts={publisher.oa_types}
          total={publisher.n_journals}
          className="h-2.5"
        />
        <OaCompositionLegend counts={publisher.oa_types} />
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs tabular-nums">
        <span className="font-medium text-[var(--muted-foreground)]">{t("detail.quartiles")}:</span>
        {(["q1", "q2", "q3", "q4", "none"] as const).map((q) => {
          const n = publisher.quartiles[q] ?? 0;
          return (
            <span
              key={q}
              className={`inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2 py-0.5 ${
                n ? "bg-[var(--card)]" : "opacity-50"
              }`}
            >
              {q === "none" ? (
                <span>{t("detail.notRanked")}</span>
              ) : (
                <QuartileBadge quartile={q.toUpperCase()} />
              )}
              <span className="text-[var(--muted-foreground)]">{n.toLocaleString("en")}</span>
            </span>
          );
        })}
      </div>
    </div>
  );
}

type UtAuthorship = PublisherDetailResponse["ut_authorship"];
type UtAuthorRow = UtAuthorship["top_authors"][number];

function UtAuthorshipCard({ authorship, inst }: { authorship: UtAuthorship; inst: string }) {
  const t = useTranslations("publishers");
  const [showAll, setShowAll] = React.useState<Record<string, boolean>>({});
  const empty =
    authorship.faculties.length === 0 &&
    authorship.research_groups.length === 0 &&
    authorship.top_authors.length === 0;
  return (
    <CollapsibleCard
      id="ut-authorship"
      title={t("detail.authorship")}
      count={authorship.n_ut_works > 0 ? authorship.n_ut_works : undefined}
      defaultOpen={false}
      compact
      description={
        <p className="text-xs text-[var(--muted-foreground)]">
          {t("detail.authorshipIntro", { count: authorship.n_ut_works })}
        </p>
      }
      contentClassName="space-y-3 text-sm [&_td]:py-1.5 [&_th]:h-8"
    >
      {empty ? (
        <p className="text-[var(--muted-foreground)]">{t("detail.authorshipEmpty")}</p>
      ) : (
        <>
          {(authorship.faculties.length > 0 || authorship.research_groups.length > 0) && (
            <div
              className={
                authorship.faculties.length > 0 && authorship.research_groups.length > 0
                  ? "grid gap-3 lg:grid-cols-2"
                  : ""
              }
            >
              {(
                [
                  {
                    key: "faculties",
                    level: "faculty" as const,
                    heading: t("detail.faculties"),
                    caption: t("detail.authorshipCaptionFaculty"),
                    rows: authorship.faculties,
                  },
                  {
                    key: "groups",
                    level: "group" as const,
                    heading: t("detail.researchGroups"),
                    caption: t("detail.authorshipCaptionGroup"),
                    rows: authorship.research_groups,
                  },
                ] as const
              ).map((section) => {
                if (section.rows.length === 0) return null;
                const expanded = !!showAll[section.key];
                const visible = expanded ? section.rows : section.rows.slice(0, SUBTABLE_CAP);
                return (
                  <InsetPanel
                    key={section.heading}
                    title={section.heading}
                    count={section.rows.length}
                    bodyClassName="px-2 py-1"
                  >
                    <Table>
                      <caption className="sr-only">{section.caption}</caption>
                      <TableHeader>
                        <TableRow>
                          <TableHead>{t("detail.name")}</TableHead>
                          <TableHead className="text-right">{t("detail.works")}</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {visible.map((row) => (
                          <TableRow key={row.name}>
                            <TableCell className="font-medium">
                              <Link
                                href={`/${inst}/orgunit/${section.level}/${encodeNamePath(row.name)}`}
                                className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                              >
                                {row.name}
                              </Link>
                            </TableCell>
                            <TableCell className="text-right tabular-nums">
                              {row.works.toLocaleString("en")}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                    {section.rows.length > SUBTABLE_CAP && (
                      <div className="px-1 py-1.5">
                        <MoreToggle
                          open={expanded}
                          onToggle={() =>
                            setShowAll((s) => ({ ...s, [section.key]: !s[section.key] }))
                          }
                          moreLabel={t("detail.showAllCount", { count: section.rows.length })}
                        />
                      </div>
                    )}
                  </InsetPanel>
                );
              })}
            </div>
          )}
          {authorship.top_authors.length > 0 && (
            <InsetPanel
              title={t("detail.topAuthors")}
              count={authorship.top_authors.length}
              bodyClassName="px-2 py-1"
            >
              <Table>
                <caption className="sr-only">{t("detail.topAuthorsCaption")}</caption>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("detail.author")}</TableHead>
                    <TableHead className="text-right">{t("detail.works")}</TableHead>
                    <TableHead>{t("detail.affiliation")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(showAll.authors
                    ? authorship.top_authors
                    : authorship.top_authors.slice(0, SUBTABLE_CAP)
                  ).map((a: UtAuthorRow) => (
                    <TableRow key={a.pure_uuid}>
                      <TableCell className="font-medium">
                        <Link
                          href={`/${inst}/author/${a.pure_uuid}`}
                          className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                        >
                          {a.name}
                        </Link>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {a.works.toLocaleString("en")}
                      </TableCell>
                      <TableCell>
                        <span className="text-[var(--muted-foreground)]">
                          {a.research_group ?? a.faculty ?? "—"}
                        </span>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {authorship.top_authors.length > SUBTABLE_CAP && (
                <div className="px-1 py-1.5">
                  <MoreToggle
                    open={!!showAll.authors}
                    onToggle={() => setShowAll((s) => ({ ...s, authors: !s.authors }))}
                    moreLabel={t("detail.showAllCount", { count: authorship.top_authors.length })}
                  />
                </div>
              )}
            </InsetPanel>
          )}
        </>
      )}
    </CollapsibleCard>
  );
}

export default function PublisherPage() {
  const t = useTranslations("publishers");
  const tc = useTranslations("common");
  const params = useParams<{ slug: string[] }>();
  const inst = useInstitution();
  const site = useSiteMeta();
  const backHref = `/${inst}/publisher`;
  const name = params?.slug?.map(decodeURIComponent).join("/") ?? "";
  const { year_from, year_to } = useYearRange();
  const { data, isPending, isError, error } = usePublisher(name || undefined, {
    year_from,
    year_to,
  });

  const [journalPage, setJournalPage] = React.useState(1);
  React.useEffect(() => {
    setJournalPage(1);
  }, [name]);

  if (isPending)
    return (
      <DetailSkeleton
        title={name}
        sections={[t("detail.oaOverTime"), t("detail.apcCosts"), t("detail.journals")]}
      />
    );
  if (isError || !data)
    return (
      <ErrorPanel
        message={errorMessage(tc, error)}
        backHref={backHref}
        backLabel={t("detail.backToList")}
      />
    );

  const { publisher, journals, deals, deal_discrepancies, n_discrepancies, works_by_year } = data;
  const trendYears = works_by_year.filter(
    (s) =>
      (year_from === undefined || s.year >= year_from) &&
      (year_to === undefined || s.year <= year_to),
  );
  const journalPages = Math.max(1, Math.ceil(journals.length / PAGE_SIZE));
  const journalRows = journals.slice((journalPage - 1) * PAGE_SIZE, journalPage * PAGE_SIZE);
  const { n_journals: apcJournals, eur_min: apcMin, eur_max: apcMax } = publisher.apc;
  const apcValue =
    apcJournals === 0 || (apcMin == null && apcMax == null)
      ? "—"
      : apcMin != null && apcMax != null && apcMin !== apcMax
        ? `€${formatEur(apcMin)}–${formatEur(apcMax)}`
        : `€${formatEur(apcMax ?? (apcMin as number))}`;

  const sections: { id: string; label: string }[] = [
    { id: "overview", label: t("detail.navOverview") },
    ...(deals.length > 0 || n_discrepancies > 0
      ? [{ id: "deals", label: t("detail.navDeals") }]
      : []),
    ...(journals.length > 0 ? [{ id: "journals", label: t("detail.navJournals") }] : []),
    { id: "ut-authorship", label: t("detail.navAuthorship", { inst: site.short }) },
    ...(data.openalex_only.available ? [{ id: "cris-gaps", label: t("detail.navCrisGaps") }] : []),
  ];

  const hasDealsCard = deals.length > 0 || n_discrepancies > 0;

  return (
    <>
      <SectionNav
        sections={sections}
        backFallback={backHref}
        backStorageKey="jb-last-publishers"
        backLabel={t("detail.backToList")}
      />
      <div className="mx-auto max-w-screen-2xl px-4 py-6">
        <header className="mb-4">
          <h1 className="text-2xl font-bold tracking-tight text-balance sm:text-3xl">
            {displayPublisherName(publisher.name)}
          </h1>
          {(publisher.external_ids?.openaccess_nl_slug || publisher.external_ids?.ror) && (
            <div className="mt-1.5 flex flex-wrap items-center gap-3 text-xs text-[var(--muted-foreground)] [&>a]:min-h-11 [&>a]:min-w-11 min-[1024px]:[&>a]:min-h-0 min-[1024px]:[&>a]:min-w-0">
              {publisher.external_ids?.openaccess_nl_slug && (
                <a
                  href={`https://openaccess.nl/en/publisher/${publisher.external_ids.openaccess_nl_slug}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-[var(--primary-text)] underline-offset-2 hover:underline"
                  title={t("detail.openAccessNlHint")}
                >
                  {t("detail.openAccessNl")}{" "}
                  <ExternalLink aria-hidden className="size-3.5 shrink-0" />
                </a>
              )}
              {publisher.external_ids?.ror && (
                <a
                  href={publisher.external_ids.ror}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-[var(--primary-text)] underline-offset-2 hover:underline"
                  title={t("detail.rorHint")}
                >
                  {t("detail.ror")} <ExternalLink aria-hidden className="size-3.5 shrink-0" />
                </a>
              )}
            </div>
          )}
        </header>

        <div className="space-y-4">
          <DetailSummaryPanel
            id="overview"
            stats={[
              {
                label: t("detail.kpiJournals"),
                value: publisher.n_journals.toLocaleString("en"),
              },
              {
                label: t("detail.kpiWorks", { inst: site.short }),
                value: publisher.n_works.toLocaleString("en"),
                icon: (
                  <DataIcon className={`size-3.5 ${ACCESS_TEXT.brand}`}>
                    <WorksGlyph />
                  </DataIcon>
                ),
              },
              {
                label: t("detail.kpiDeals"),
                value: publisher.deal_journals.toLocaleString("en"),
                icon: (
                  <DataIcon className={`size-3.5 ${ACCESS_TEXT.deal}`}>
                    <DealGlyph />
                  </DataIcon>
                ),
              },
              {
                label: t("detail.kpiApc"),
                value: apcValue,
                icon: (
                  <DataIcon className={`size-3.5 ${ACCESS_TEXT.brand}`}>
                    <ApcGlyph />
                  </DataIcon>
                ),
                hint: apcJournals > 0 ? t("apcCoverage", { count: apcJournals }) : undefined,
                sub:
                  apcJournals > 0
                    ? t("detail.apcJournalsCount", { count: apcJournals })
                    : undefined,
              },
            ]}
            belowStats={<PublisherBreakdowns publisher={publisher} />}
            trendStats={trendYears}
            trendTitle={t("detail.oaOverTime")}
            topics={
              publisher.topics.length > 0
                ? {
                    label: t("detail.topics"),
                    items: publisher.topics.map((topic) => ({
                      name: topic.name,
                      count: Math.round(topic.n),
                      href: `/${inst}/?publisher=${encodeURIComponent(publisher.name)}&topic=${encodeURIComponent(topic.name)}`,
                      title: t("detail.topicHint", { count: Math.round(topic.n) }),
                    })),
                    limit: 8,
                  }
                : undefined
            }
          />

          {hasDealsCard && (
            <CollapsibleCard
              id="deals"
              title={t("detail.deals")}
              count={deals.length > 0 ? deals.length : undefined}
              compact
              contentClassName="text-sm"
            >
              {deals.length > 0 && (
                <ul className="divide-y divide-[var(--border)]">
                  {deals.map((deal) => (
                    <DealRow key={deal.id} deal={deal} />
                  ))}
                </ul>
              )}
              {n_discrepancies > 0 && (
                <div className="mt-3 border-t border-[var(--border)] pt-2.5 text-xs text-[var(--muted-foreground)]">
                  <p>{t("detail.discrepancies", { count: n_discrepancies })}</p>
                  <ul className="mt-1 list-disc space-y-0.5 pl-4">
                    {deal_discrepancies.map((d) => (
                      <li key={d.title ?? d.publisher_name}>
                        {d.title}
                        {d.publisher_name && <span> ({d.publisher_name})</span>}{" "}
                        {t("detail.discrepancyCovered", {
                          publisher: d.deal_publisher ?? t("detail.anotherPublisher"),
                        })}
                      </li>
                    ))}
                    {n_discrepancies > deal_discrepancies.length && (
                      <li>
                        {t("detail.moreDiscrepancies", {
                          count: n_discrepancies - deal_discrepancies.length,
                        })}
                      </li>
                    )}
                  </ul>
                </div>
              )}
            </CollapsibleCard>
          )}

          {journals.length > 0 && (
            <CollapsibleCard
              id="journals"
              title={t("detail.journals")}
              count={publisher.n_journals}
              compact
              contentClassName="space-y-3 text-sm [&_td]:py-1.5 [&_th]:h-8"
            >
              <Table>
                <caption className="sr-only">{t("detail.journalsCaption")}</caption>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("detail.journal")}</TableHead>
                    <TableHead className="text-right">{t("detail.works")}</TableHead>
                    <TableHead>{t("detail.access")}</TableHead>
                    <TableHead>{t("detail.quartile")}</TableHead>
                    <TableHead>{t("detail.apc")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {journalRows.map((j) => (
                    <TableRow key={j.issn_l}>
                      <TableCell className="font-medium">
                        <Link
                          href={`/${inst}/journals/${j.issn_l}`}
                          className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                        >
                          {j.title || j.issn_l}
                        </Link>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {j.works.toLocaleString("en")}
                      </TableCell>
                      <TableCell>
                        <OaTypeBadge oaType={j.oa_type} isOa={j.is_oa} />
                      </TableCell>
                      <TableCell>
                        <QuartileBadge quartile={j.quartile ?? null} />
                      </TableCell>
                      <TableCell className="whitespace-nowrap">
                        <ApcText apc={j} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {publisher.n_journals > journals.length && (
                <p className="text-xs text-[var(--muted-foreground)]">
                  {t("detail.showingTopJournals", {
                    count: journals.length,
                    total: publisher.n_journals,
                  })}{" "}
                  <Link
                    href={`/${inst}/journals?publisher=${encodeURIComponent(publisher.name)}`}
                    className="text-[var(--primary-text)] hover:underline"
                  >
                    {t("detail.searchAllJournals")}
                  </Link>
                </p>
              )}
              {journalPages > 1 && (
                <CardPager
                  page={journalPage}
                  pages={journalPages}
                  total={journals.length}
                  onPage={setJournalPage}
                  label={t("detail.pagerLabel")}
                />
              )}
            </CollapsibleCard>
          )}

          <UtAuthorshipCard authorship={data.ut_authorship} inst={inst} />

          <CrisGapsSection
            target={{ kind: "publisher", name }}
            available={data.openalex_only.available}
            initialTotal={data.openalex_only.total}
            initialPartsCounts={data.openalex_only.parts_counts}
          />
        </div>
      </div>
    </>
  );
}
