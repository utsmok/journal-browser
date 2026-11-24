"use client";

import { ExternalLink, Quote, Sparkles, X } from "lucide-react";
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
  DealGlyph,
  DoajGlyph,
  QuartileGlyph,
  WorksGlyph,
} from "@/components/data-icons";
import { DetailSummaryPanel, type DetailStatItem } from "@/components/detail-summary";
import { DealPanel } from "@/components/journal/deal-panel";
import { FunderFitCard } from "@/components/journal/funder-fit-card";
import { GreenOaPanel } from "@/components/journal/green-oa-panel";
import {
  CopyButton,
  External,
  MoreToggle,
  NamedTopic,
  TOPICS_LIMIT,
} from "@/components/journal/shared";
import { OpenaireCard } from "@/components/journal/openaire-card";
import { PublicationsCard } from "@/components/journal/publications-card";
import { SectionNav, useLastSearchHref } from "@/components/journal/section-nav";
import { UtAuthorshipCard } from "@/components/journal/ut-authorship-card";
import { SourceNote } from "@/components/source-note";
import { ErrorPanel, JournalDetailSkeleton } from "@/components/states";
import { InsetPanel } from "@/components/sub-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { apcRowGap, apcSummary } from "@/lib/format";
import { useFunderPrefs } from "@/lib/funder-prefs";

const SIMILAR_PREVIEW = 5;
const ALT_NAMES_PREVIEW = 6;

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
  const [citeOpen, setCiteOpen] = React.useState(false);
  const [altNamesExpanded, setAltNamesExpanded] = React.useState(false);
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
  // The APC tile states which price it shows: the publisher's list price,
  // or else the mean amount paid to OpenAPC.
  const apc = apcSummary(journal);
  const apcYear = apc.year ?? "—";
  const apcSource = apc.source ?? "";
  const apcPaid = apc.paid;

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
      label:
        apc.kind === "list"
          ? t("header.kpiListPrice")
          : apc.kind === "paid"
            ? t("header.kpiPaidApc")
            : t("header.kpiApc"),
      value: apc.kind === "list" ? (apc.amount ?? "—") : (apcPaid?.amount ?? "—"),
      icon: (
        <DataIcon className={`size-3.5 ${ACCESS_TEXT.brand}`}>
          <ApcGlyph />
        </DataIcon>
      ),
      sub:
        apc.kind === "list" ? (
          <>
            {t("header.kpiListSub", { source: apcSource, year: apcYear })}
            {apcPaid ? (
              <span className="hidden xl:inline">
                {` · ${t("header.kpiPaidShort", { amount: apcPaid.amount })}`}
              </span>
            ) : (
              apc.original && ` · ${apc.original}`
            )}
          </>
        ) : apc.kind === "paid" && apcPaid ? (
          apcPaid.count != null ? (
            t("header.kpiPaidSub", { period: apcPaid.period, count: apcPaid.count })
          ) : (
            t("header.kpiPaidPeriod", { period: apcPaid.period })
          )
        ) : undefined,
      hint:
        apc.kind === "list"
          ? [
              t("header.kpiListHint", { source: apcSource, year: apcYear }),
              apc.original
                ? t("header.kpiListConvertedHint", { original: apc.original })
                : apc.currency !== "EUR"
                  ? t("header.kpiListNoRateHint", { currency: apc.currency ?? "" })
                  : null,
              apcPaid
                ? apcPaid.count != null
                  ? t("header.kpiPaidHint", {
                      amount: apcPaid.amount,
                      count: apcPaid.count,
                      period: apcPaid.period,
                    })
                  : t("header.kpiPaidHintNoCount", {
                      amount: apcPaid.amount,
                      period: apcPaid.period,
                    })
                : null,
            ]
              .filter(Boolean)
              .join(" ")
          : apc.kind === "paid"
            ? t("header.kpiPaidTileHint", { period: apcPaid?.period ?? apcYear })
            : undefined,
    },
    {
      label: t("header.kpiTotalWorks"),
      value: openalex?.works_count != null ? openalex.works_count.toLocaleString("en") : "—",
      hint: t("metrics.worksCountHint"),
      sub:
        openalex?.cited_by_count != null
          ? t("header.kpiCitations", { count: openalex.cited_by_count.toLocaleString("en") })
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
    ...(!similarEmpty ? [{ id: "similar", label: t("similar.title") }] : []),
    { id: "metrics", label: t("metrics.title") },
    { id: "ut-authorship", label: t("utAuthorship.title") },
    { id: "publications", label: t("publications.navLabel") },
    ...(openaire && openaire.matched_works > 0
      ? [{ id: "openaire", label: t("openaire.title") }]
      : []),
    ...(data.openalex_only.available ? [{ id: "cris-gaps", label: t("crisGaps.title") }] : []),
  ];

  const uniqueIssns = [`ISSN-L ${journal.issn_l}`, ...data.issns.map((i) => `ISSN ${i}`)].filter(
    (v, i, a) => a.indexOf(v) === i,
  );
  const today = new Date().toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
  const citation = t("citation.template", {
    title: journal.title ?? journal.issn_l,
    publisher: journal.publisher_name ?? t("header.unknownPublisher"),
    issnL: journal.issn_l,
    url: `${process.env.NEXT_PUBLIC_SITE_URL ?? "https://journalbrowser.samuelmok.cc"}/${inst}/journals/${journal.issn_l}`,
    date: today,
  });
  const visibleAltNames = altNamesExpanded
    ? data.alternate_titles
    : data.alternate_titles.slice(0, ALT_NAMES_PREVIEW);

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
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
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
            <Button
              variant={citeOpen ? "secondary" : "outline"}
              size="sm"
              aria-expanded={citeOpen}
              onClick={() => setCiteOpen((v) => !v)}
              className="shrink-0 gap-1.5"
            >
              <Quote aria-hidden className="size-3.5" />
              {t("header.cite")}
            </Button>
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
          {citeOpen && (
            <div className="mt-2.5 flex items-start gap-2 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--muted)]/40 px-3 py-2 text-xs">
              <p className="min-w-0 flex-1 text-pretty text-[var(--foreground)] [overflow-wrap:anywhere]">
                {citation}
              </p>
              <CopyButton text={citation} label={t("citation.copyLabel")} />
              <button
                type="button"
                onClick={() => setCiteOpen(false)}
                aria-label={tc("feedback.close")}
                className="inline-flex size-6 shrink-0 items-center justify-center rounded border border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              >
                <X aria-hidden className="size-3.5" />
              </button>
            </div>
          )}
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
            topics={
              topicChipItems.length > 0
                ? {
                    label: t("topics.title"),
                    items: topicChipItems,
                    showCounts: oaTopics.length > 0,
                    limit: TOPICS_LIMIT,
                    sourceNote:
                      oaTopics.length > 0 ? (
                        <SourceNote
                          {...(attribution.openalex ?? {})}
                          codes={attribution.openalex?.caveat_codes}
                        />
                      ) : undefined,
                  }
                : undefined
            }
            metaFooter={
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                  <span className="shrink-0 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                    {t("identifiers.label")}
                  </span>
                  <div className="flex flex-wrap items-center gap-2">
                    {uniqueIssns.map((label) => (
                      <span key={label} className="inline-flex items-center gap-1">
                        <Badge variant="muted" className="font-normal tabular-nums">
                          {label}
                        </Badge>
                        <CopyButton text={label.replace(/^ISSN(-L)? /, "")} label={label} />
                      </span>
                    ))}
                  </div>
                  {(data.doaj_homepage_url || openalex?.url || data.openaccess_nl_slug) && (
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                      {data.doaj_homepage_url && (
                        <span className="inline-flex items-center gap-1.5">
                          <External href={data.doaj_homepage_url}>
                            {t("identifiers.doajRecord")}
                          </External>
                          <SourceNote
                            source={t("identifiers.viaDoaj")}
                            url="https://doaj.org"
                            codes={["doaj-canon"]}
                          />
                        </span>
                      )}
                      {openalex?.url && (
                        <External href={openalex.url}>{t("identifiers.openalexSource")}</External>
                      )}
                      {data.openaccess_nl_slug && (
                        <External
                          href={`https://openaccess.nl/en/publisher/${data.openaccess_nl_slug}`}
                        >
                          {t("identifiers.oaNlPublisher")}
                        </External>
                      )}
                    </div>
                  )}
                </div>
                {data.alternate_titles.length > 0 && (
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="shrink-0 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                      {t("names.inlineLabel")}
                    </span>
                    {visibleAltNames.map((name) => (
                      <Badge key={name} variant="muted" className="font-normal normal-case">
                        {name}
                      </Badge>
                    ))}
                    {data.alternate_titles.length > ALT_NAMES_PREVIEW && (
                      <MoreToggle
                        open={altNamesExpanded}
                        onToggle={() => setAltNamesExpanded((v) => !v)}
                        moreLabel={t("names.showAll", {
                          count: String(data.alternate_titles.length),
                        })}
                      />
                    )}
                  </div>
                )}
              </div>
            }
          />

          {/* Block 3: Publishing routes & costs */}
          <div
            className={
              (deals.length > 0 ? deals.length : 1) + (greenOa ? 1 : 0) > 1
                ? "grid gap-4 lg:grid-cols-2"
                : ""
            }
          >
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

          {hasApc && (
            <CollapsibleCard
              id="apc"
              title={t("apc.title")}
              count={data.apc_aggregates.length > 0 ? data.apc_aggregates.length : undefined}
              compact
              contentClassName="text-xs sm:text-sm [&_td]:px-2 [&_td]:py-1.5 [&_th]:h-8 [&_th]:px-2"
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
                      <TableHead className="text-right" title={t("apc.zeroColHint")}>
                        {t("apc.zeroCol")}
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
                    {data.apc_aggregates.map((a) => {
                      // A line under the period says why it has no mean, or why
                      // its mean is approximate.
                      const gap = apcRowGap(a);
                      const zero = a.zero_count ?? 0;
                      const note =
                        gap === "legacyMean"
                          ? t("apc.legacyMeanNote")
                          : gap === "noneAboveZero"
                            ? t("apc.noneAboveZeroNote")
                            : gap === "noAmount"
                              ? t("apc.noAmountNote")
                              : gap === "allDealPaid"
                                ? t("apc.allDealPaidNote", { count: zero })
                                : gap === "partDealPaid"
                                  ? t("apc.partDealPaidNote", {
                                      zero,
                                      rest: a.article_count - zero,
                                    })
                                  : null;
                      const eur = (v: number) => `€${Math.round(v).toLocaleString("en")}`;
                      return (
                        <React.Fragment key={a.period}>
                          <TableRow className={note ? "border-b-0" : undefined}>
                            <TableCell className="tabular-nums">{a.period}</TableCell>
                            <TableCell className="text-right tabular-nums">
                              {a.article_count}
                            </TableCell>
                            <TableCell className="text-right tabular-nums">
                              {a.zero_count ?? "—"}
                            </TableCell>
                            <TableCell className="text-right tabular-nums">
                              {a.euro_mean != null ? eur(a.euro_mean) : "—"}
                              {a.euro_mean != null && a.paid_count != null && (
                                <div className="text-[11px] text-[var(--muted-foreground)]">
                                  {t("apc.paidCount", { count: a.paid_count })}
                                </div>
                              )}
                            </TableCell>
                            <TableCell className="text-right tabular-nums">
                              {a.euro_max == null
                                ? "—"
                                : a.euro_min == null
                                  ? t("apc.upTo", { amount: eur(a.euro_max) })
                                  : `${eur(a.euro_min)}–${eur(a.euro_max)}`}
                            </TableCell>
                          </TableRow>
                          {note && (
                            <TableRow>
                              <TableCell
                                colSpan={5}
                                className="py-0 pb-1.5 text-[11px] text-[var(--muted-foreground)]"
                              >
                                {note}
                              </TableCell>
                            </TableRow>
                          )}
                        </React.Fragment>
                      );
                    })}
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

          {/* Block 4: Similar & Detailed Metrics & UT Authorship */}
          {similar && !similarEmpty && (
            <CollapsibleCard id="similar" title={t("similar.title")} compact>
              <div className="space-y-3">
                {(
                  [
                    {
                      key: "institution",
                      heading: t("similar.institutionHeading", { short: site.short }),
                      note: t("similar.institutionNote", { name: site.name }),
                      icon: (
                        <DataIcon className={`size-3.5 ${ACCESS_TEXT.brand}`}>
                          <WorksGlyph />
                        </DataIcon>
                      ),
                    },
                    {
                      key: "deals",
                      heading: t("similar.dealsHeading"),
                      note: t("similar.dealsNote", { short: site.short }),
                      icon: (
                        <DataIcon className={`size-3.5 ${ACCESS_TEXT.deal}`}>
                          <DealGlyph />
                        </DataIcon>
                      ),
                    },
                    {
                      key: "all",
                      heading: t("similar.allHeading"),
                      note: t("similar.allNote", { short: site.short }),
                      icon: (
                        <Sparkles
                          aria-hidden
                          className="size-3.5 shrink-0 text-[var(--muted-foreground)]"
                        />
                      ),
                    },
                  ] as const
                ).map(
                  (group) =>
                    similar[group.key].length > 0 && (
                      <InsetPanel
                        key={group.key}
                        title={group.heading}
                        icon={group.icon}
                        count={similar[group.key].length}
                        subtitle={group.note}
                      >
                        <ul className="divide-y divide-[var(--border)]">
                          {(openSimilar[group.key]
                            ? similar[group.key]
                            : similar[group.key].slice(0, SIMILAR_PREVIEW)
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
                        {similar[group.key].length > SIMILAR_PREVIEW && (
                          <div className="mt-1.5 border-t border-[var(--border)] pt-1.5">
                            <MoreToggle
                              open={!!openSimilar[group.key]}
                              onToggle={() =>
                                setOpenSimilar((m) => ({ ...m, [group.key]: !m[group.key] }))
                              }
                              moreLabel={t("similar.showAll", {
                                count: String(similar[group.key].length),
                              })}
                            />
                          </div>
                        )}
                      </InsetPanel>
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
            contentClassName="space-y-3 text-sm"
          >
            <InsetPanel title={t("metrics.groupOpenAlex")}>
              <dl className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-5">
                {[
                  {
                    label: t("metrics.citednessLabel"),
                    hint: t("metrics.citednessHint"),
                    value:
                      journal.twoyr_mean_citedness != null
                        ? journal.twoyr_mean_citedness.toFixed(1)
                        : "—",
                  },
                  {
                    label: t("metrics.hIndexLabel"),
                    hint: t("metrics.hIndexHint"),
                    value: num("h_index")?.toLocaleString("en") ?? "—",
                  },
                  {
                    label: t("metrics.i10Label"),
                    hint: t("metrics.i10Hint"),
                    value: num("i10_index")?.toLocaleString("en") ?? "—",
                  },
                  ...(openalex?.cited_by_count != null
                    ? [
                        {
                          label: t("metrics.totalCitationsLabel"),
                          hint: t("metrics.totalCitationsHint"),
                          value: openalex.cited_by_count.toLocaleString("en"),
                        },
                      ]
                    : []),
                  ...(openalex?.works_count != null
                    ? [
                        {
                          label: t("metrics.worksCountLabel"),
                          hint: t("metrics.worksCountHint"),
                          value: openalex.works_count.toLocaleString("en"),
                        },
                      ]
                    : []),
                ].map((item) => (
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
                  </div>
                ))}
              </dl>
              <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1">
                <SourceNote
                  {...(attribution.metrics ?? {})}
                  codes={attribution.metrics?.caveat_codes}
                />
                {openalex && (
                  <SourceNote
                    {...(attribution.openalex ?? {})}
                    codes={attribution.openalex?.caveat_codes}
                  />
                )}
              </div>
            </InsetPanel>

            {(metrics || openaire) && (
              <InsetPanel title={t("metrics.groupInst", { short: site.short })}>
                <dl className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
                  {metrics && (
                    <div
                      title={t("metrics.fwciHint", { short: site.short })}
                      tabIndex={0}
                      className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--muted)]/35 px-3 py-2"
                    >
                      <dt className="truncate text-[11px] font-medium text-[var(--muted-foreground)]">
                        {t("metrics.fwciLabel", { short: site.short })}
                      </dt>
                      <dd className="mt-0.5 text-lg font-bold leading-tight tabular-nums text-[var(--foreground)]">
                        {metrics.fwci_avg != null && metrics.fwci_n > 0
                          ? metrics.fwci_avg.toFixed(2)
                          : "—"}
                      </dd>
                      <div className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
                        {t("metrics.fwciN", { count: metrics.fwci_n })}
                      </div>
                    </div>
                  )}
                  {metrics && metrics.retracted > 0 && (
                    <div
                      title={t("metrics.retractedHint", { short: site.short })}
                      tabIndex={0}
                      className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--muted)]/35 px-3 py-2"
                    >
                      <dt className="truncate text-[11px] font-medium text-[var(--muted-foreground)]">
                        {t("metrics.retractedLabel", { short: site.short })}
                      </dt>
                      <dd className="mt-0.5 text-lg font-bold leading-tight tabular-nums text-[var(--foreground)]">
                        {metrics.retracted.toLocaleString("en")}
                      </dd>
                    </div>
                  )}
                  {openaire && (
                    <div
                      title={t("metrics.openaireHint", { name: site.name })}
                      tabIndex={0}
                      className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--muted)]/35 px-3 py-2"
                    >
                      <dt className="truncate text-[11px] font-medium text-[var(--muted-foreground)]">
                        {t("metrics.openaireLabel")}
                      </dt>
                      <dd className="mt-0.5 text-lg font-bold leading-tight tabular-nums text-[var(--foreground)]">
                        {openaire.matched_works.toLocaleString("en")}
                      </dd>
                    </div>
                  )}
                </dl>
                <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1">
                  {metrics && (
                    <SourceNote
                      {...(attribution.openalex ?? {})}
                      codes={attribution.openalex?.caveat_codes}
                    />
                  )}
                  {openaire && (
                    <SourceNote
                      {...(attribution.openaire ?? {})}
                      codes={attribution.openaire?.caveat_codes}
                    />
                  )}
                </div>
              </InsetPanel>
            )}

            {latestSjr && (
              <InsetPanel title={t("metrics.groupScimago")}>
                <dl className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
                  <div
                    title={t("metrics.sjrHint")}
                    tabIndex={0}
                    className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--muted)]/35 px-3 py-2"
                  >
                    <dt className="truncate text-[11px] font-medium text-[var(--muted-foreground)]">
                      {t("metrics.sjrLabel")}
                    </dt>
                    <dd className="mt-0.5 text-lg font-bold leading-tight tabular-nums text-[var(--foreground)]">
                      {latestSjr.sjr !== null ? latestSjr.sjr.toFixed(3) : "—"}
                    </dd>
                    {latestSjr.year && (
                      <div className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
                        {latestSjr.year}
                      </div>
                    )}
                  </div>
                  <div
                    title={t("metrics.bestQuartileHint")}
                    tabIndex={0}
                    className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--muted)]/35 px-3 py-2"
                  >
                    <dt className="truncate text-[11px] font-medium text-[var(--muted-foreground)]">
                      {t("metrics.bestQuartileLabel")}
                    </dt>
                    <dd className="mt-0.5 text-lg font-bold leading-tight tabular-nums text-[var(--foreground)]">
                      {latestSjr.best_quartile ?? "—"}
                    </dd>
                  </div>
                  <div
                    title={t("metrics.sjrHIndexHint")}
                    tabIndex={0}
                    className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--muted)]/35 px-3 py-2"
                  >
                    <dt className="truncate text-[11px] font-medium text-[var(--muted-foreground)]">
                      {t("metrics.sjrHIndexLabel")}
                    </dt>
                    <dd className="mt-0.5 text-lg font-bold leading-tight tabular-nums text-[var(--foreground)]">
                      {latestSjr.h_index?.toLocaleString("en") ?? "—"}
                    </dd>
                  </div>
                </dl>
                <div className="mt-2.5">
                  <SourceNote
                    {...(attribution.scimagojr ?? {})}
                    codes={attribution.scimagojr?.caveat_codes}
                  />
                </div>
              </InsetPanel>
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
            initialTotal={data.openalex_only.total}
            initialPartsCounts={data.openalex_only.parts_counts}
          />
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
