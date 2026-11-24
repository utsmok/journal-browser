"use client";

import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import * as React from "react";

import { DealBadge, OaTypeBadge, QuartileBadge } from "@/components/badges";
import { CollapsibleCard } from "@/components/collapsible-card";
import { CrisGapsSection } from "@/components/cris-gaps-section";
import {
  ACCESS_TEXT,
  ApcGlyph,
  DataIcon,
  DoajGlyph,
  QuartileGlyph,
  WorksGlyph,
} from "@/components/data-icons";
import { DetailSummaryPanel, type DetailStatItem } from "@/components/detail-summary";
import { CitationCard } from "@/components/journal/citation-card";
import { DealPanel } from "@/components/journal/deal-panel";
import { FunderFitCard } from "@/components/journal/funder-fit-card";
import { GreenOaPanel } from "@/components/journal/green-oa-panel";
import { IdentifiersCard } from "@/components/journal/identifiers-card";
import {
  CopyButton,
  External,
  Metric,
  MoreToggle,
  NamedTopic,
  SIMILAR_LIMIT,
  TOPICS_LIMIT,
} from "@/components/journal/shared";
import { OpenaireCard } from "@/components/journal/openaire-card";
import { OtherNamesCard } from "@/components/journal/other-names-card";
import { PublicationsCard } from "@/components/journal/publications-card";
import { SectionNav, useLastSearchHref } from "@/components/journal/section-nav";
import { UtAuthorshipCard } from "@/components/journal/ut-authorship-card";
import { SourceNote } from "@/components/source-note";
import { ErrorPanel, JournalDetailSkeleton } from "@/components/states";
import { TopicChipList } from "@/components/topic-chips";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useJournal, useJournalWorks, useSimilar } from "@/hooks/use-api";
import { useInstitution } from "@/hooks/use-institution";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { useYearRange } from "@/hooks/use-year-filter";
import { encodeNamePath, errorMessage, type OpenalexTopic } from "@/lib/api";
import { useFunderPrefs } from "@/lib/funder-prefs";

function JournalPageInner() {
  const t = useTranslations("journals");
  const tc = useTranslations("common");
  const site = useSiteMeta();
  const params = useParams<{ issn_l: string }>();
  const inst = useInstitution();
  const issnL = params?.issn_l ? decodeURIComponent(params.issn_l) : undefined;
  const backHref = useLastSearchHref();
  const [funder] = useFunderPrefs();
  const { year_from, year_to } = useYearRange();
  const [openSimilar, setOpenSimilar] = React.useState<Record<string, boolean>>({});
  const { data, isPending, isError, error } = useJournal(issnL, funder?.id, {
    year_from,
    year_to,
  });
  const similarQuery = useSimilar(issnL);
  const similar = similarQuery.data;
  const searchParams = useSearchParams();
  const pParam = parseInt(searchParams.get("page") ?? "", 10);
  const requestedWorksPage = Number.isFinite(pParam) && pParam > 0 ? pParam : 1;
  const worksQuery = useJournalWorks(issnL, requestedWorksPage, { year_from, year_to });
  const similarEmpty =
    !similar ||
    (similar.all.length === 0 && similar.institution.length === 0 && similar.deals.length === 0);

  if (isPending) return <JournalDetailSkeleton />;
  if (isError || !data) return <ErrorPanel message={errorMessage(tc, error)} backHref={backHref} />;

  const { journal, stats, deals, attribution, summary_stats, stats_totals: totals } = data;
  const greenOa = data.green_oa ?? null;
  const recent = stats.filter(
    (s) =>
      s.year >= (site.windowStart ?? 0) &&
      (year_from === undefined || s.year >= year_from) &&
      (year_to === undefined || s.year <= year_to),
  );
  const pureTotal =
    year_from === undefined ? totals.pure_canon : recent.reduce((acc, s) => acc + s.works_count, 0);
  const openalex = data.openalex ?? null;
  const openaire = data.openaire ?? null;
  const metrics = data.institution_metrics ?? null;

  const ss = (summary_stats ?? {}) as Record<string, unknown>;
  const num = (key: string) => (typeof ss[key] === "number" ? (ss[key] as number) : null);
  const latestSjr = data.scimagojr.at(-1);
  const topics = Array.from(
    new Set(
      (data.topics as NamedTopic[])
        .map((tp) => tp?.display_name)
        .filter((n): n is string => Boolean(n)),
    ),
  );
  const oaTopics = (openalex?.topics ?? []).filter(
    (tp): tp is OpenalexTopic & { display_name: string } => Boolean(tp?.display_name),
  );
  const hasApc = data.apc_aggregates.length > 0 || data.apc_evidence.length > 0;

  const latestApcAgg = data.apc_aggregates[0];
  const latestApcPrice = data.apc_prices[0] as { price?: number; currency?: string } | undefined;
  const apcHeadline =
    latestApcAgg?.euro_mean != null
      ? `€${Math.round(latestApcAgg.euro_mean).toLocaleString("en")}`
      : latestApcPrice?.price != null
        ? `${latestApcPrice.currency ?? "€"} ${Math.round(latestApcPrice.price).toLocaleString("en")}`
        : "—";

  const summaryStats: DetailStatItem[] = [
    {
      label: t("header.kpiWorks", { inst: site.short }),
      value: pureTotal.toLocaleString("en"),
      icon: (
        <DataIcon className={`size-3.5 ${ACCESS_TEXT.brand}`}>
          <WorksGlyph />
        </DataIcon>
      ),
      sub:
        year_from === undefined
          ? `OpenAlex: ${totals.openalex_institution_filter.toLocaleString("en")}`
          : undefined,
    },
    {
      label: t("header.kpiCitedness"),
      value: journal.twoyr_mean_citedness != null ? journal.twoyr_mean_citedness.toFixed(1) : "—",
      hint: t("metrics.citednessHint"),
      sub: num("h_index") != null ? `h-index ${num("h_index")?.toLocaleString("en")}` : undefined,
    },
    {
      label: t("header.kpiQuartile"),
      value: latestSjr?.best_quartile ?? journal.quartile ?? "—",
      icon: (
        <DataIcon className={`size-3.5 ${ACCESS_TEXT.brand}`}>
          <QuartileGlyph />
        </DataIcon>
      ),
      hint: t("metrics.sjrHint"),
      sub:
        latestSjr?.sjr != null ? `SJR ${latestSjr.sjr.toFixed(3)} (${latestSjr.year})` : undefined,
    },
    {
      label: t("header.kpiFwci", { short: site.short }),
      value: metrics?.fwci_avg != null && metrics.fwci_n > 0 ? metrics.fwci_avg.toFixed(2) : "—",
      hint: t("metrics.fwciHint", { short: site.short }),
      sub:
        metrics && metrics.fwci_n > 0 ? t("metrics.fwciN", { count: metrics.fwci_n }) : undefined,
    },
    {
      label: t("header.kpiApc"),
      value: apcHeadline,
      icon: (
        <DataIcon className={`size-3.5 ${ACCESS_TEXT.brand}`}>
          <ApcGlyph />
        </DataIcon>
      ),
      sub: latestApcAgg ? `OpenAPC ${latestApcAgg.period}` : undefined,
    },
    {
      label: t("header.kpiTotalWorks"),
      value: openalex?.works_count != null ? openalex.works_count.toLocaleString("en") : "—",
      hint: t("metrics.worksCountHint"),
      sub:
        openalex?.cited_by_count != null
          ? `${openalex.cited_by_count.toLocaleString("en")} citations`
          : undefined,
    },
  ];

  const trendSubtitle =
    year_from !== undefined
      ? t("oaPerYear.titleSuffixYears", {
          short: site.short,
          from: String(year_from),
          to: String(year_to),
        })
      : site.windowStart === undefined
        ? t("oaPerYear.titleSuffixShort", { short: site.short })
        : t("oaPerYear.titleSuffixWindow", {
            short: site.short,
            window: String(site.windowStart),
          });

  const sections: { id: string; label: string; hint?: string }[] = [
    { id: "overview", label: t("nav.overview") },
    ...(deals.length > 0
      ? deals.map((deal) => ({ id: `deal-${deal.id}`, label: t("deal.title") }))
      : [{ id: "deal", label: t("deal.title") }]),
    ...(greenOa ? [{ id: "green-oa", label: t("greenOa.title") }] : []),
    ...(hasApc ? [{ id: "apc", label: t("apc.title"), hint: t("apc.hint") }] : []),
    ...(topics.length > 0 || oaTopics.length > 0
      ? [{ id: "topics", label: t("topics.title") }]
      : []),
    ...(!similarEmpty ? [{ id: "similar", label: t("similar.title") }] : []),
    { id: "metrics", label: t("metrics.title") },
    { id: "ut-authorship", label: t("utAuthorship.title") },
    { id: "publications", label: t("publications.navLabel") },
    ...(openaire && openaire.matched_works > 0
      ? [{ id: "openaire", label: t("openaire.title") }]
      : []),
    ...(data.openalex_only.available ? [{ id: "cris-gaps", label: t("crisGaps.title") }] : []),
    { id: "identifiers", label: t("identifiers.title") },
  ];

  const topicChipItems =
    oaTopics.length > 0
      ? oaTopics.map((topic) => ({
          key: topic.id ?? topic.display_name,
          name: topic.display_name,
          count: topic.count ?? 0,
          href: `/${inst}/?topic=${encodeURIComponent(topic.display_name)}&search_in=topic`,
          title: [
            [topic.subfield?.display_name, topic.field?.display_name, topic.domain?.display_name]
              .filter(Boolean)
              .join(" → "),
            t("topics.worksCount", { count: topic.count ?? 0 }),
          ]
            .filter(Boolean)
            .join(" · "),
        }))
      : topics.map((topic) => ({
          key: topic,
          name: topic.replace(/^\d+\s+/, ""),
          title: topic,
        }));

  return (
    <>
      <SectionNav sections={sections} />
      <div className="mx-auto max-w-screen-2xl px-4 py-6">
        <header className="mb-4">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">
              {data.homepage_url ? (
                <a
                  href={data.homepage_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={t("header.websiteLabel", {
                    title: journal.title ?? journal.issn_l,
                  })}
                  className="inline-flex items-center gap-1.5 underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                >
                  {journal.title ?? journal.issn_l}
                  <ExternalLink aria-hidden className="size-4 text-[var(--muted-foreground)]" />
                </a>
              ) : (
                (journal.title ?? journal.issn_l)
              )}
            </h1>
            <OaTypeBadge oaType={journal.oa_type} isOa={journal.is_oa} />
            <QuartileBadge quartile={journal.quartile ?? null} />
            <DealBadge covered={journal.deal_covered} capped={journal.deal_cap_reached} />
            {journal.is_in_doaj && (
              <Badge
                variant="outline"
                className="inline-flex items-center gap-1"
                title={t("header.doajHint")}
              >
                <DataIcon className={`size-3.5 ${ACCESS_TEXT.doaj}`}>
                  <DoajGlyph />
                </DataIcon>
                {t("header.doajBadge")}
              </Badge>
            )}
            <span className="inline-flex items-center gap-1">
              <Badge
                variant="muted"
                className="font-normal tabular-nums"
                title={t("header.issnLHint")}
              >
                ISSN-L {journal.issn_l}
              </Badge>
              <CopyButton text={journal.issn_l} label={`ISSN-L ${journal.issn_l}`} />
            </span>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--muted-foreground)]">
            <span>
              {journal.publisher_canonical || journal.publisher_name ? (
                <Link
                  href={`/${inst}/publisher/${encodeNamePath(
                    journal.publisher_canonical ?? journal.publisher_name ?? "",
                  )}`}
                  className="font-medium text-[var(--foreground)] underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                >
                  {journal.publisher_canonical ?? journal.publisher_name}
                </Link>
              ) : (
                t("header.unknownPublisher")
              )}
              {journal.publisher_canonical &&
                journal.publisher_name &&
                journal.publisher_canonical !== journal.publisher_name && (
                  <span>
                    {" · "}
                    {t("header.imprint", { name: journal.publisher_name })}
                  </span>
                )}
              {data.type ? ` · ${data.type.charAt(0).toUpperCase()}${data.type.slice(1)}` : ""}
            </span>
            {data.homepage_url && (
              <External href={data.homepage_url}>{t("header.homepage")}</External>
            )}
            <SourceNote
              source={t("header.metadataSource")}
              url={attribution.title?.url ?? undefined}
              howBuilt={tc("sourceNote.explain.journals")}
            />
          </div>
        </header>

        <div className="space-y-4">
          <DetailSummaryPanel
            id="overview"
            stats={summaryStats}
            trendStats={recent}
            trendTitle={t("oaPerYear.title")}
            trendSubtitle={trendSubtitle}
            trendEmpty={
              <p className="py-4 text-xs text-[var(--muted-foreground)]">{t("oaPerYear.empty")}</p>
            }
            trendFooter={
              <div className="space-y-1.5 text-xs">
                <p>
                  {year_from === undefined
                    ? t.rich("oaPerYear.totals", {
                        pure: totals.pure_canon.toLocaleString("en"),
                        short: site.short,
                        since: site.windowStart === undefined ? "" : ` since ${site.windowStart}`,
                        openalex: totals.openalex_institution_filter.toLocaleString("en"),
                        pureLabel: (chunks) => (
                          <span className="text-[var(--muted-foreground)]">{chunks}</span>
                        ),
                        openalexLabel: (chunks) => (
                          <span className="whitespace-nowrap">{chunks}</span>
                        ),
                        crossLabel: (chunks) => (
                          <span className="text-[var(--muted-foreground)]">{chunks}</span>
                        ),
                      })
                    : t.rich("oaPerYear.totalsYears", {
                        pure: pureTotal.toLocaleString("en"),
                        short: site.short,
                        from: String(year_from),
                        to: String(year_to),
                        pureLabel: (chunks) => (
                          <span className="text-[var(--muted-foreground)]">{chunks}</span>
                        ),
                      })}
                </p>
                <div className="flex flex-wrap gap-x-4">
                  <SourceNote
                    {...(attribution.stats ?? {})}
                    codes={attribution.stats?.caveat_codes}
                    howBuilt={tc("sourceNote.explain.works")}
                  />
                  <SourceNote
                    {...(attribution.oa_status ?? {})}
                    codes={attribution.oa_status?.caveat_codes}
                    howBuilt={tc("sourceNote.explain.journals")}
                  />
                </div>
              </div>
            }
          />

          {/* Block 3: Publishing routes & costs */}
          <div className="grid gap-4 lg:grid-cols-2">
            {deals.length > 0 ? (
              deals.map((deal) => (
                <DealPanel
                  key={deal.id}
                  id={`deal-${deal.id}`}
                  deal={deal}
                  attribution={attribution.deals ?? {}}
                />
              ))
            ) : (
              <CollapsibleCard
                id="deal"
                title={t("deal.title")}
                compact
                contentClassName="text-sm text-[var(--muted-foreground)]"
              >
                {t.rich("deal.noDeal", {
                  name: site.name,
                  oaNl: (chunks) => <External href="https://www.openaccess.nl">{chunks}</External>,
                  jct: (chunks) => (
                    <External href="https://journalcheckertool.org">{chunks}</External>
                  ),
                })}
                <div className="mt-2">
                  <SourceNote
                    {...(attribution.deals ?? {})}
                    codes={attribution.deals?.caveat_codes}
                    howBuilt={tc("sourceNote.explain.deals")}
                  />
                </div>
              </CollapsibleCard>
            )}

            {greenOa && <GreenOaPanel greenOa={greenOa} attribution={attribution.green_oa ?? {}} />}
          </div>

          {funder && <FunderFitCard fit={data.funder_fit ?? null} funder={funder} inst={inst} />}

          {(hasApc || topicChipItems.length > 0) && (
            <div className={hasApc && topicChipItems.length > 0 ? "grid gap-4 lg:grid-cols-2" : ""}>
              {hasApc && (
                <CollapsibleCard
                  id="apc"
                  title={t("apc.title")}
                  count={data.apc_aggregates.length}
                  compact
                  contentClassName="text-sm [&_td]:py-1.5 [&_th]:h-8"
                >
                  {data.apc_aggregates.length > 0 && (
                    <Table>
                      <caption className="sr-only">{t("apc.caption")}</caption>
                      <TableHeader>
                        <TableRow>
                          <TableHead title={t("apc.yearColHint")}>{t("apc.yearCol")}</TableHead>
                          <TableHead className="text-right" title={t("apc.countColHint")}>
                            {t("apc.countCol")}
                          </TableHead>
                          <TableHead className="text-right" title={t("apc.meanColHint")}>
                            {t("apc.meanCol")}
                          </TableHead>
                          <TableHead className="text-right" title={t("apc.rangeColHint")}>
                            {t("apc.rangeCol")}
                          </TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {data.apc_aggregates.map((a) => (
                          <TableRow key={a.period}>
                            <TableCell className="tabular-nums">{a.period}</TableCell>
                            <TableCell className="text-right tabular-nums">
                              {a.article_count}
                            </TableCell>
                            <TableCell className="text-right tabular-nums">
                              {a.euro_mean !== null
                                ? `€${Math.round(a.euro_mean).toLocaleString("en")}`
                                : "—"}
                            </TableCell>
                            <TableCell className="text-right tabular-nums">
                              {a.euro_min !== null && a.euro_max !== null
                                ? `€${Math.round(a.euro_min).toLocaleString("en")}–€${Math.round(a.euro_max).toLocaleString("en")}`
                                : "—"}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                  {data.apc_evidence.length > 0 && (
                    <p className="mt-2.5 text-xs text-[var(--muted-foreground)]">
                      {t("apc.evidence", {
                        count: data.apc_evidence.length,
                        short: site.short,
                        period: data.apc_evidence[0].period ?? "—",
                        amount:
                          data.apc_evidence[0].euro !== null
                            ? `€${Math.round(data.apc_evidence[0].euro!)}`
                            : t("apc.amountUnknown"),
                      })}
                    </p>
                  )}
                  <div className="mt-2.5">
                    <SourceNote
                      {...(attribution.apc_evidence ?? {})}
                      codes={attribution.apc_evidence?.caveat_codes}
                      howBuilt={tc("sourceNote.explain.apc")}
                    />
                  </div>
                </CollapsibleCard>
              )}

              {topicChipItems.length > 0 && (
                <CollapsibleCard
                  id="topics"
                  title={t("topics.title")}
                  count={topicChipItems.length}
                  compact
                  description={
                    <p className="text-xs text-[var(--muted-foreground)]">
                      {oaTopics.length > 0
                        ? t("topics.descriptionWithCounts")
                        : t("topics.description")}
                    </p>
                  }
                  contentClassName="space-y-2.5"
                >
                  <TopicChipList
                    items={topicChipItems}
                    limit={TOPICS_LIMIT}
                    showCounts={oaTopics.length > 0}
                  />
                  {oaTopics.length > 0 && (
                    <SourceNote
                      {...(attribution.openalex ?? {})}
                      codes={attribution.openalex?.caveat_codes}
                    />
                  )}
                </CollapsibleCard>
              )}
            </div>
          )}

          {/* Block 4: Similar & Detailed Metrics & UT Authorship */}
          {similar && !similarEmpty && (
            <CollapsibleCard id="similar" title={t("similar.title")} compact>
              <div className="space-y-4">
                {(
                  [
                    {
                      key: "institution",
                      heading: t("similar.institutionHeading", { short: site.short }),
                      note: t("similar.institutionNote", { name: site.name }),
                    },
                    {
                      key: "deals",
                      heading: t("similar.dealsHeading"),
                      note: t("similar.dealsNote", { short: site.short }),
                    },
                    {
                      key: "all",
                      heading: t("similar.allHeading"),
                      note: t("similar.allNote", { short: site.short }),
                    },
                  ] as const
                ).map(
                  (group) =>
                    similar[group.key].length > 0 && (
                      <div key={group.key}>
                        <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                          {group.heading}
                        </h3>
                        {group.note && (
                          <p className="mb-1 text-xs text-[var(--muted-foreground)]">
                            {group.note}
                          </p>
                        )}
                        <ul className="divide-y divide-[var(--border)]">
                          {(openSimilar[group.key]
                            ? similar[group.key]
                            : similar[group.key].slice(0, SIMILAR_LIMIT)
                          ).map((s) => (
                            <li
                              key={s.issn_l}
                              className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-1.5 text-sm first:pt-0 last:pb-0"
                            >
                              <Link
                                href={`/${inst}/journals/${s.issn_l}`}
                                className="font-medium underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                              >
                                {s.title ?? s.issn_l}
                              </Link>
                              <span className="text-xs text-[var(--muted-foreground)]">
                                {s.publisher_canonical ??
                                  s.publisher_name ??
                                  t("header.unknownPublisher")}
                              </span>
                              <span className="ml-auto flex flex-wrap items-center gap-2">
                                <DealBadge covered={s.deal_covered} capped={s.deal_cap_reached} />
                                {s.works > 0 && (
                                  <span
                                    className="text-xs text-[var(--muted-foreground)]"
                                    title={t("similar.publicationsHint", { name: site.name })}
                                  >
                                    {t("similar.publications", {
                                      count: s.works,
                                      short: site.short,
                                    })}
                                  </span>
                                )}
                                <QuartileBadge quartile={s.quartile ?? null} />
                                <span
                                  className="text-xs text-[var(--muted-foreground)]"
                                  title={t("similar.similarityTitle")}
                                >
                                  {s.similarity != null
                                    ? t("similar.percentMatch", {
                                        percent: String(Math.round(s.similarity * 100)),
                                      })
                                    : t("similar.sharedTopics", { count: s.shared_topics })}
                                  {s.similarity != null && (
                                    <span className="sr-only">{` ${t("similar.embeddingNote")}`}</span>
                                  )}
                                </span>
                              </span>
                            </li>
                          ))}
                        </ul>
                        {similar[group.key].length > SIMILAR_LIMIT && (
                          <MoreToggle
                            open={!!openSimilar[group.key]}
                            onToggle={() =>
                              setOpenSimilar((m) => ({ ...m, [group.key]: !m[group.key] }))
                            }
                            moreLabel={t("similar.showAll", {
                              count: String(similar[group.key].length),
                            })}
                          />
                        )}
                      </div>
                    ),
                )}
              </div>
              <div className="mt-3 border-t border-[var(--border)] pt-2.5">
                <SourceNote
                  source={tc("sourceNote.howListLabel")}
                  howBuilt={tc("sourceNote.explain.similar")}
                />
              </div>
            </CollapsibleCard>
          )}

          <CollapsibleCard
            id="metrics"
            title={t("metrics.title")}
            defaultOpen={false}
            compact
            contentClassName="space-y-4 text-sm"
          >
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <Metric
                label={t("metrics.citednessLabel")}
                hint={t("metrics.citednessHint")}
                value={
                  journal.twoyr_mean_citedness != null
                    ? journal.twoyr_mean_citedness.toFixed(1)
                    : "—"
                }
              />
              <Metric
                label={t("metrics.hIndexLabel")}
                hint={t("metrics.hIndexHint")}
                value={num("h_index")?.toLocaleString("en") ?? "—"}
                note="OpenAlex"
              />
              <Metric
                label={t("metrics.i10Label")}
                hint={t("metrics.i10Hint")}
                value={num("i10_index")?.toLocaleString("en") ?? "—"}
                note="OpenAlex"
              />
            </div>
            <SourceNote
              {...(attribution.metrics ?? {})}
              codes={attribution.metrics?.caveat_codes}
            />
            {(openalex || metrics || openaire) && (
              <div className="border-t border-[var(--border)] pt-3">
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                  {openalex?.cited_by_count != null && (
                    <Metric
                      label={t("metrics.totalCitationsLabel")}
                      hint={t("metrics.totalCitationsHint")}
                      value={openalex.cited_by_count.toLocaleString("en")}
                      note={
                        <SourceNote
                          {...(attribution.openalex ?? {})}
                          codes={attribution.openalex?.caveat_codes}
                        />
                      }
                    />
                  )}
                  {openalex?.works_count != null && (
                    <Metric
                      label={t("metrics.worksCountLabel")}
                      hint={t("metrics.worksCountHint")}
                      value={openalex.works_count.toLocaleString("en")}
                      note={
                        <SourceNote
                          {...(attribution.openalex ?? {})}
                          codes={attribution.openalex?.caveat_codes}
                        />
                      }
                    />
                  )}
                  {metrics && (
                    <Metric
                      label={t("metrics.fwciLabel", { short: site.short })}
                      hint={t("metrics.fwciHint", { short: site.short })}
                      value={
                        metrics.fwci_avg != null && metrics.fwci_n > 0
                          ? metrics.fwci_avg.toFixed(2)
                          : "—"
                      }
                      note={
                        <>
                          {t("metrics.fwciN", { count: metrics.fwci_n })}{" "}
                          <SourceNote
                            {...(attribution.openalex ?? {})}
                            codes={attribution.openalex?.caveat_codes}
                          />
                        </>
                      }
                    />
                  )}
                  {metrics && metrics.retracted > 0 && (
                    <Metric
                      label={t("metrics.retractedLabel", { short: site.short })}
                      hint={t("metrics.retractedHint", { short: site.short })}
                      value={metrics.retracted.toLocaleString("en")}
                      note={
                        <SourceNote
                          {...(attribution.openalex ?? {})}
                          codes={attribution.openalex?.caveat_codes}
                        />
                      }
                    />
                  )}
                  {openaire && (
                    <Metric
                      label={t("metrics.openaireLabel")}
                      hint={t("metrics.openaireHint", { name: site.name })}
                      value={openaire.matched_works.toLocaleString("en")}
                      note={
                        <SourceNote
                          {...(attribution.openaire ?? {})}
                          codes={attribution.openaire?.caveat_codes}
                        />
                      }
                    />
                  )}
                </div>
              </div>
            )}
            {latestSjr && (
              <div className="border-t border-[var(--border)] pt-3">
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                  <Metric
                    label={t("metrics.sjrLabel")}
                    hint={t("metrics.sjrHint")}
                    value={latestSjr.sjr !== null ? latestSjr.sjr.toFixed(3) : "—"}
                    note={latestSjr.year ? String(latestSjr.year) : undefined}
                  />
                  <Metric
                    label={t("metrics.bestQuartileLabel")}
                    hint={t("metrics.bestQuartileHint")}
                    value={latestSjr.best_quartile ?? "—"}
                  />
                  <Metric
                    label={t("metrics.sjrHIndexLabel")}
                    hint={t("metrics.sjrHIndexHint")}
                    value={latestSjr.h_index?.toLocaleString("en") ?? "—"}
                  />
                </div>
                <div className="mt-2.5">
                  <SourceNote
                    {...(attribution.scimagojr ?? {})}
                    codes={attribution.scimagojr?.caveat_codes}
                  />
                </div>
              </div>
            )}
          </CollapsibleCard>

          <UtAuthorshipCard authorship={data.ut_authorship} inst={inst} />

          {/* Block 5: Evidence & Reference */}
          <PublicationsCard
            key={journal.issn_l}
            title={journal.title ?? journal.issn_l}
            openalex={openalex}
            worksNote={attribution.works ?? {}}
            requested={requestedWorksPage}
            worksQuery={worksQuery}
          />

          {openaire && openaire.matched_works > 0 && (
            <OpenaireCard openaire={openaire} note={attribution.openaire ?? {}} />
          )}

          <CrisGapsSection
            target={{ kind: "journal", issnL: journal.issn_l }}
            available={data.openalex_only.available}
          />

          {data.alternate_titles.length > 0 && <OtherNamesCard names={data.alternate_titles} />}

          <div className="grid gap-4 lg:grid-cols-2">
            <IdentifiersCard
              issnL={journal.issn_l}
              issns={data.issns}
              doajUrl={data.doaj_homepage_url}
              openalexUrl={openalex?.url}
              oaNlSlug={data.openaccess_nl_slug}
            />

            <CitationCard data={data} />
          </div>
        </div>
      </div>
    </>
  );
}

export default function JournalPage() {
  return (
    <React.Suspense fallback={null}>
      <JournalPageInner />
    </React.Suspense>
  );
}
