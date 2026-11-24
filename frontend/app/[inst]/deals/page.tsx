"use client";

import { CircleCheck, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { ActiveFiltersBar, type ActiveFilterChip } from "@/components/active-filters-bar";
import { DealBadge } from "@/components/badges";
import { CollapsibleCard } from "@/components/collapsible-card";
import { DealCapUsage } from "@/components/deal-cap-usage";
import {
  FacetGroupList,
  FilterSidebarCard,
  hasVisibleGroups,
  type FacetGroupDef,
} from "@/components/filter-panel";
import { PageTabs } from "@/components/page-tabs";
import { SourceNote } from "@/components/source-note";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useDeals } from "@/hooks/use-api";
import { useInstitution } from "@/hooks/use-institution";
import { useSearchShortcut } from "@/hooks/use-search-shortcut";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { errorMessage, type DealLink, type DealOut } from "@/lib/api";
import { capReached, latestYearUsage } from "@/lib/deal-caps";
import { dealLinkLabel, displayPublisherName, orderedDealLinks } from "@/lib/deal-links";
import { formatApc, formatEur, formatInt } from "@/lib/format";
import { cleanProse } from "@/lib/utils";

/** One card line for a condition the deal has. False conditions never
 * render as ✗: a skimming reader parses "Corresponding authors only — ✗"
 * as a broken deal. Callers either omit them or reword positively. */
function ConditionLine({ label }: { label: string }) {
  const t = useTranslations("deals");
  return (
    <span className="inline-flex items-center gap-1" title={t("condition.applies")}>
      <CircleCheck aria-hidden className="size-3.5 text-emerald-700 dark:text-emerald-400" />
      {label}
    </span>
  );
}

/** Whitespace-collapsed form, for comparing scraped text that differs
 * only in line breaks and doubled spaces. */
function normalizeProse(text: string): string {
  return text.replace(/\s+/g, " ").trim();
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
        {/* OpenAPC records without a euro amount must not read as €0. */}
        {deal.apc_n > 0 && deal.apc_euro_total > 0 && (
          <span>{t("card.apcTotal", { total: formatEur(deal.apc_euro_total) })}</span>
        )}
        {deal.apc_n > 0 && deal.apc_euro_total > 0 && deal.apc_n > 1 && (
          <span>{t("card.apcMean", { mean: formatApc(deal.apc_euro_total / deal.apc_n) })}</span>
        )}
        {deal.apc_n > 0 && deal.apc_euro_total === 0 && (
          <span title={t("card.noCostDataTitle", { count: deal.apc_n })}>
            {t("card.noCostData")}
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
        {deal.corresponding_authors_only === true && (
          <ConditionLine label={t("condition.correspondingOnly")} />
        )}
        {deal.corresponding_authors_only === false && (
          <ConditionLine label={t("condition.openToAll")} />
        )}
        {Boolean(deal.cap_text || capNumbers.length > 0) && (
          <ConditionLine label={t("condition.capped")} />
        )}
      </div>
      {/* The scraped summary often restates the preview with different
      whitespace; only render the full text when it adds real content. */}
      {summary && preview && !normalizeProse(summary).startsWith(normalizeProse(preview)) && (
        <p className="max-w-prose text-pretty">{summary}</p>
      )}
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
            href={`/${inst}/?deal_id=${deal.id}`}
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

type DealTab = "current" | "archive";
type DealSort = "journals_desc" | "title_asc" | "oa_desc";

const SELECT_CLASS =
  "h-9 rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2";

function dealHasCaps(deal: DealOut): boolean {
  return Boolean(deal.cap_text || Object.keys(deal.cap_numbers ?? {}).length > 0);
}

function dealHasCost(deal: DealOut): boolean {
  return deal.apc_n > 0 && deal.apc_euro_total > 0;
}

function latestOaArticles(deal: DealOut): number {
  const entries = Object.entries(deal.per_year_oa_counts ?? {}).sort(
    (a, b) => (parseInt(a[0], 10) || 0) - (parseInt(b[0], 10) || 0),
  );
  return Number(entries.at(-1)?.[1] ?? 0);
}

type DealFacetState = {
  query: string;
  eligibility: string[];
  caps: string[];
  cost: string[];
  curation: string[];
};

function matchesDealFacets(
  deal: DealOut,
  state: DealFacetState,
  skip?: keyof DealFacetState,
): boolean {
  const needle = state.query.trim().toLowerCase();
  if (needle) {
    const hay = [
      deal.publisher_name ?? "",
      displayPublisherName(deal.publisher_name),
      deal.summary ?? "",
      deal.conditions_text ?? "",
      deal.cap_text ?? "",
    ]
      .join(" ")
      .toLowerCase();
    if (!hay.includes(needle)) return false;
  }
  if (skip !== "eligibility" && state.eligibility.length > 0) {
    const val = deal.corresponding_authors_only ? "corresponding" : "open_to_all";
    if (!state.eligibility.includes(val)) return false;
  }
  if (skip !== "caps" && state.caps.length > 0) {
    const isCapped = dealHasCaps(deal);
    const atCap = latestYearUsage(deal.cap_usage).some(capReached);
    const matched =
      (state.caps.includes("capped") && isCapped) ||
      (state.caps.includes("uncapped") && !isCapped) ||
      (state.caps.includes("cap_reached") && atCap);
    if (!matched) return false;
  }
  if (skip !== "cost" && state.cost.length > 0) {
    const val = dealHasCost(deal) ? "has_cost" : "no_cost";
    if (!state.cost.includes(val)) return false;
  }
  if (skip !== "curation" && state.curation.length > 0) {
    const val = deal.needs_curation ? "pending" : "curated";
    if (!state.curation.includes(val)) return false;
  }
  return true;
}

function toggleOption(prev: string[], value: string): string[] {
  return prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value];
}

export default function DealsPage() {
  const t = useTranslations("deals");
  const tc = useTranslations("common");
  const site = useSiteMeta();
  const current = useDeals("current");
  const archive = useDeals("archive");
  const [tab, setTab] = useState<DealTab>("current");
  const [sort, setSort] = useState<DealSort>("journals_desc");
  const [query, setQuery] = useState("");
  const [eligibility, setEligibility] = useState<string[]>([]);
  const [caps, setCaps] = useState<string[]>([]);
  const [cost, setCost] = useState<string[]>([]);
  const [curation, setCuration] = useState<string[]>([]);
  useSearchShortcut("deals-search");

  const currentList = current.data ?? [];
  const archiveList = archive.data ?? [];
  const activeQuery = tab === "current" ? current : archive;
  const activeList = tab === "current" ? currentList : archiveList;
  const isArchivedTab = tab === "archive";

  const facetState: DealFacetState = { query, eligibility, caps, cost, curation };
  const filtered = activeList
    .filter((d) => matchesDealFacets(d, facetState))
    .slice()
    .sort((a, b) => {
      if (sort === "title_asc") {
        return displayPublisherName(a.publisher_name).localeCompare(
          displayPublisherName(b.publisher_name),
        );
      }
      if (sort === "oa_desc") {
        const diff = latestOaArticles(b) - latestOaArticles(a);
        if (diff !== 0) return diff;
      }
      const diff = (b.journal_count ?? 0) - (a.journal_count ?? 0);
      if (diff !== 0) return diff;
      return displayPublisherName(a.publisher_name).localeCompare(
        displayPublisherName(b.publisher_name),
      );
    });

  const countIn = (skip: keyof DealFacetState, pred: (d: DealOut) => boolean) =>
    activeList.filter((d) => matchesDealFacets(d, facetState, skip) && pred(d)).length;

  const groups: FacetGroupDef[] = [
    {
      key: "eligibility",
      label: t("filter.groupEligibility"),
      defaultOpen: true,
      values: [
        {
          value: "corresponding",
          count: countIn("eligibility", (d) => d.corresponding_authors_only === true),
          label: t("filter.correspondingOnly"),
        },
        {
          value: "open_to_all",
          count: countIn("eligibility", (d) => d.corresponding_authors_only !== true),
          label: t("filter.openToAll"),
        },
      ],
      activeValues: eligibility,
    },
    {
      key: "caps",
      label: t("filter.groupCaps"),
      defaultOpen: true,
      values: [
        {
          value: "capped",
          count: countIn("caps", dealHasCaps),
          label: t("filter.capped"),
        },
        {
          value: "uncapped",
          count: countIn("caps", (d) => !dealHasCaps(d)),
          label: t("filter.uncapped"),
        },
        {
          value: "cap_reached",
          count: countIn("caps", (d) => latestYearUsage(d.cap_usage).some(capReached)),
          label: t("filter.capReached"),
        },
      ],
      activeValues: caps,
    },
    {
      key: "cost",
      label: t("filter.groupCost"),
      defaultOpen: true,
      values: [
        {
          value: "has_cost",
          count: countIn("cost", dealHasCost),
          label: t("filter.hasCost"),
        },
        {
          value: "no_cost",
          count: countIn("cost", (d) => !dealHasCost(d)),
          label: t("filter.noCost"),
        },
      ],
      activeValues: cost,
    },
    {
      key: "curation",
      label: t("filter.groupStatus"),
      defaultOpen: true,
      values: [
        {
          value: "curated",
          count: countIn("curation", (d) => !d.needs_curation),
          label: t("filter.curated"),
        },
        {
          value: "pending",
          count: countIn("curation", (d) => Boolean(d.needs_curation)),
          label: t("filter.curationPending"),
        },
      ],
      activeValues: curation,
    },
  ];

  const toggleFacet = (key: string, value: string) => {
    if (key === "eligibility") setEligibility((prev) => toggleOption(prev, value));
    else if (key === "caps") setCaps((prev) => toggleOption(prev, value));
    else if (key === "cost") setCost((prev) => toggleOption(prev, value));
    else if (key === "curation") setCuration((prev) => toggleOption(prev, value));
  };

  const clearAll = () => {
    setQuery("");
    setEligibility([]);
    setCaps([]);
    setCost([]);
    setCuration([]);
  };

  const optionLabel = (key: string, value: string): string => {
    if (key === "eligibility") {
      return value === "corresponding" ? t("filter.correspondingOnly") : t("filter.openToAll");
    }
    if (key === "caps") {
      if (value === "capped") return t("filter.capped");
      if (value === "cap_reached") return t("filter.capReached");
      return t("filter.uncapped");
    }
    if (key === "cost") return value === "has_cost" ? t("filter.hasCost") : t("filter.noCost");
    return value === "curated" ? t("filter.curated") : t("filter.curationPending");
  };

  const chips: ActiveFilterChip[] = [
    ...(query.trim()
      ? [
          {
            id: "q",
            label: `Search: “${query.trim()}”`,
            onRemove: () => setQuery(""),
          },
        ]
      : []),
    ...eligibility.map((v) => ({
      id: `eligibility:${v}`,
      label: `${t("filter.groupEligibility")}: ${optionLabel("eligibility", v)}`,
      onRemove: () => toggleFacet("eligibility", v),
    })),
    ...caps.map((v) => ({
      id: `caps:${v}`,
      label: `${t("filter.groupCaps")}: ${optionLabel("caps", v)}`,
      onRemove: () => toggleFacet("caps", v),
    })),
    ...cost.map((v) => ({
      id: `cost:${v}`,
      label: `${t("filter.groupCost")}: ${optionLabel("cost", v)}`,
      onRemove: () => toggleFacet("cost", v),
    })),
    ...curation.map((v) => ({
      id: `curation:${v}`,
      label: `${t("filter.groupStatus")}: ${optionLabel("curation", v)}`,
      onRemove: () => toggleFacet("curation", v),
    })),
  ];

  const hasFilter = chips.length > 0;
  const coveredCount = currentList.reduce((sum, d) => sum + (d.journal_count ?? 0), 0);
  const cappedCount = currentList.filter(dealHasCaps).length;

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <header className="mb-6">
        <h1 className="mb-2 text-3xl font-bold text-balance">{t("page.heading")}</h1>
        <p className="mb-4 max-w-2xl text-sm text-[var(--muted-foreground)]">
          {t("page.intro", { institution: site.short })}{" "}
          {current.data && (
            <span className="font-medium text-[var(--foreground)]">
              {t("page.summaryInline", {
                current: currentList.length,
                covered: coveredCount,
                capped: cappedCount,
              })}
            </span>
          )}
        </p>

        <PageTabs
          ariaLabel={t("tabs.ariaLabel")}
          value={tab}
          onChange={setTab}
          items={[
            {
              value: "current",
              label: t("tabs.current"),
              badge: current.data ? formatInt(currentList.length) : undefined,
            },
            {
              value: "archive",
              label: t("tabs.archive"),
              badge: archive.data ? formatInt(archiveList.length) : undefined,
            },
          ]}
          className="mb-5"
        />

        <form
          className="flex max-w-2xl gap-2"
          onSubmit={(event) => {
            event.preventDefault();
          }}
        >
          <div className="relative flex-1">
            <Input
              id="deals-search"
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") e.currentTarget.blur();
              }}
              placeholder={t("filter.searchPlaceholder")}
              aria-label={t("filter.searchAria")}
              className="pr-8"
            />
            {query === "" && (
              <kbd
                aria-hidden
                className="pointer-events-none absolute right-2.5 top-1/2 hidden -translate-y-1/2 rounded border border-[var(--border)] bg-[var(--muted)] px-1.5 py-0.5 text-[11px] text-[var(--muted-foreground)] [@media(hover:hover)_and_(pointer:fine)]:block"
              >
                /
              </kbd>
            )}
          </div>
        </form>
      </header>

      {/* Stacked filters (<960px) */}
      {activeQuery.data != null && hasVisibleGroups(groups) && (
        <section className="mb-6 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 min-[960px]:hidden">
          <FacetGroupList groups={groups} onToggle={toggleFacet} variant="chips" />
        </section>
      )}

      <div className="flex flex-col gap-6 min-[960px]:grid min-[960px]:grid-cols-[15rem_minmax(0,1fr)] min-[960px]:items-start min-[1280px]:grid-cols-[18rem_minmax(0,1fr)] min-[1280px]:gap-8">
        {/* Sticky sidebar (>=960px) */}
        {activeQuery.data != null && hasVisibleGroups(groups) ? (
          <aside className="sticky top-20 hidden max-h-[calc(100vh-6rem)] self-start overflow-y-auto min-[960px]:block">
            <FilterSidebarCard activeCount={chips.length} onReset={clearAll}>
              <FacetGroupList groups={groups} onToggle={toggleFacet} variant="rows" />
            </FilterSidebarCard>
          </aside>
        ) : (
          <div className="hidden min-[960px]:block" />
        )}

        <div className="min-w-0">
          <ActiveFiltersBar
            chips={chips}
            onClearAll={clearAll}
            ariaLabel={tc("activeFilters.label")}
            clearLabel={tc("activeFilters.clearAll")}
            removeAriaPrefix={tc("activeFilters.remove")}
          />

          <Card>
            <CardContent className="pt-5">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] pb-3">
                <p className="text-sm text-[var(--muted-foreground)]">
                  {activeQuery.data
                    ? t("section.count", { count: filtered.length, institution: site.short })
                    : activeQuery.isError
                      ? t("section.loadFailed")
                      : t("section.loading")}
                </p>
                <div className="flex items-center gap-2 text-sm">
                  <label
                    htmlFor="deals-sort"
                    className="whitespace-nowrap text-xs text-[var(--muted-foreground)]"
                  >
                    {t("sort.label")}
                  </label>
                  <select
                    id="deals-sort"
                    title={t("sort.title")}
                    value={sort}
                    onChange={(event) => setSort(event.target.value as DealSort)}
                    className={SELECT_CLASS}
                  >
                    <option value="journals_desc">{t("sort.journalsDesc")}</option>
                    <option value="title_asc">{t("sort.titleAsc")}</option>
                    <option value="oa_desc">{t("sort.oaDesc")}</option>
                  </select>
                </div>
              </div>

              {isArchivedTab && (
                <p className="mb-4 text-xs text-[var(--muted-foreground)]">
                  {t("section.archiveIntro", { institution: site.short })}
                </p>
              )}

              {activeQuery.isError ? (
                <div className="py-10 text-center">
                  <p className="text-[var(--destructive)]">{errorMessage(tc, activeQuery.error)}</p>
                  <Button
                    variant="outline"
                    size="sm"
                    className="mt-3"
                    onClick={() => activeQuery.refetch()}
                  >
                    {t("section.retry")}
                  </Button>
                </div>
              ) : !activeQuery.data ? (
                <p className="py-10 text-center text-sm text-[var(--muted-foreground)]">
                  {t("section.loading")}
                </p>
              ) : filtered.length === 0 ? (
                <div className="py-10 text-center text-sm text-[var(--muted-foreground)]">
                  <p>{hasFilter ? t("filter.empty") : t("section.archiveEmpty")}</p>
                  {hasFilter && (
                    <Button variant="outline" size="sm" className="mt-3" onClick={clearAll}>
                      {t("filter.clear")}
                    </Button>
                  )}
                </div>
              ) : (
                <div className="grid gap-4 lg:grid-cols-2">
                  {filtered.map((deal) => (
                    <DealCard key={deal.id} deal={deal} archived={isArchivedTab} />
                  ))}
                </div>
              )}

              <div className="mt-4">
                <SourceNote
                  source="JCT · openaccess.nl"
                  url="https://journalcheckertool.org/transformative-agreements/"
                  codes={["jct-coverage", "openaccess-nl-prose", "issn-mapping"]}
                  howBuilt={tc("sourceNote.explain.deals")}
                />
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
