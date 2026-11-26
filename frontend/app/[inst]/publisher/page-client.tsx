"use client";

import { Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import * as React from "react";

import { ActiveFiltersBar, type ActiveFilterChip } from "@/components/active-filters-bar";
import { DirectoryPager } from "@/components/directory-pager";
import { FilterLayout } from "@/components/filter-layout";
import {
  FacetGroupList,
  hasVisibleGroups,
  type FacetGroupDef,
  type FacetValue,
} from "@/components/filter-panel";
import { rememberDirectoryUrl } from "@/components/journal/section-nav";
import { LoadingBar } from "@/components/loading-bar";
import { OaCompositionBar } from "@/components/oa-composition";
import { SortHead } from "@/components/search/sort-head";
import { ListSkeletonRows } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useInstitution } from "@/hooks/use-institution";
import { usePublishers } from "@/hooks/use-api";
import { useSearchShortcut } from "@/hooks/use-search-shortcut";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { useYearRange } from "@/hooks/use-year-filter";
import {
  encodeNamePath,
  errorMessage,
  type PublisherListItem,
  type PublisherSearchSort,
} from "@/lib/api";
import { displayPublisherName } from "@/lib/deal-links";
import { formatEur } from "@/lib/format";
import { PUBLISHER_COLUMN_SORTS } from "@/lib/search-config";
import { patchSearchParams } from "@/lib/url-params";

import { normalizeDeal, publisherDirectoryParams } from "./params";

const SEARCH_INPUT_ID = "publisher-search";

/** Facet codes → message keys; unknown codes fall back to the raw value. */
const OA_TYPE_KEYS: Record<string, string> = {
  gold: "facets.oaTypes.gold",
  diamond: "facets.oaTypes.diamond",
  generic: "facets.oaTypes.modelUnknown",
  hybrid: "facets.oaTypes.hybrid",
  subscription: "facets.oaTypes.subscription",
};

const DEAL_KEYS: Record<string, string> = {
  covered: "facets.dealCovered",
  not_covered: "facets.dealNone",
  // Legacy bucket key still emitted by the publisher facets.
  none: "facets.dealNone",
};

/** Matches the journal page's sort-select styling. */
const SELECT_CLASS =
  "h-9 w-full rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-2 min-[768px]:w-auto focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2";

/** Top N buckets of a facet record, with active values kept visible. */
function facetValues(
  counts: Record<string, number> | undefined,
  active: string[],
  label?: (value: string) => string,
  limit = 8,
): FacetValue[] {
  const list: FacetValue[] = Object.entries(counts ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([value, count]) => ({ value, count, label: label?.(value) }));
  for (const value of active)
    if (!list.some((v) => v.value === value)) list.unshift({ value, label: label?.(value) });
  return list;
}

/** Compact Q1–Q4 chips with counts; a quartile with no journals dims out. */
function QuartileChips({ item }: { item: PublisherListItem }) {
  const t = useTranslations("publishers");
  return (
    <span className="flex flex-wrap gap-1 text-[11px] tabular-nums">
      {(["q1", "q2", "q3", "q4"] as const).map((q) => {
        const n = item.quartiles[q] ?? 0;
        return (
          <span
            key={q}
            title={
              n
                ? t("quartileChipHint", { quartile: q.toUpperCase(), count: n })
                : t("quartileChipNoneHint", { quartile: q.toUpperCase() })
            }
            className={
              n
                ? "rounded bg-[var(--secondary)] px-1 py-0.5 text-[var(--secondary-foreground)]"
                : "rounded bg-[var(--muted)] px-1 py-0.5 text-[var(--muted-foreground)]"
            }
          >
            {q.toUpperCase()}
            {n > 0 ? ` ${n}` : ""}
          </span>
        );
      })}
    </span>
  );
}

/** APC range over the publisher's journals with a known price. */
function ApcCell({ item }: { item: PublisherListItem }) {
  const t = useTranslations("publishers");
  const { n_journals, eur_min: min, eur_max: max } = item.apc;
  if (n_journals === 0 || (min == null && max == null))
    return <span className="text-[var(--muted-foreground)]">—</span>;
  const range =
    min != null && max != null && min !== max
      ? `€${formatEur(min)}–${formatEur(max)}`
      : `€${formatEur(max ?? (min as number))}`;
  return (
    <span className="tabular-nums" title={t("apcCoverage", { count: n_journals })}>
      {range}{" "}
      <span className="text-[var(--muted-foreground)]">({n_journals.toLocaleString("en")})</span>
    </span>
  );
}

export default function PublisherSearchPage() {
  // useSearchParams needs a Suspense boundary during prerender.
  return (
    <React.Suspense fallback={null}>
      <PublishersView />
    </React.Suspense>
  );
}

function PublishersView() {
  const t = useTranslations("publishers");
  const tc = useTranslations("common");
  const inst = useInstitution();
  const site = useSiteMeta();
  const sp = useSearchParams();
  const pathname = usePathname();
  const { year_from, year_to } = useYearRange();
  useSearchShortcut(SEARCH_INPUT_ID);

  const {
    params,
    q,
    oaTypes,
    deal,
    quartiles,
    sizes,
    topic,
    hasApc,
    hasWorks,
    sort,
    dir,
    pageSize,
    offset,
  } = publisherDirectoryParams(sp, { year_from, year_to });
  const [input, setInput] = React.useState(q);
  const lastCommittedQ = React.useRef(q);

  const anyFilter =
    oaTypes.length > 0 ||
    deal !== null ||
    quartiles.length > 0 ||
    sizes.length > 0 ||
    topic !== "" ||
    hasApc !== null ||
    hasWorks !== null;

  const setParams = React.useCallback(
    (patch: Record<string, string | undefined>) => {
      // Any query, filter, sort, or page-size change restarts at page 1;
      // only the pager itself touches offset directly.
      patchSearchParams(pathname, patch, { drop: "offset" in patch ? [] : ["offset"] });
    },
    [pathname],
  );

  const update = React.useCallback(
    (value: string) => {
      lastCommittedQ.current = value;
      setParams({ q: value || undefined });
    },
    [setParams],
  );

  // Live search with debounce; keep the input in sync with back/forward nav.
  React.useEffect(() => {
    if (q !== lastCommittedQ.current) {
      lastCommittedQ.current = q;
      setInput(q);
    }
  }, [q]);
  React.useEffect(() => {
    const t = setTimeout(() => {
      if (input !== q) update(input);
    }, 250);
    return () => clearTimeout(t);
  }, [input, q, update]);

  const yearsKey = `${year_from ?? ""}-${year_to ?? ""}`;
  const prevYearsKey = React.useRef(yearsKey);
  React.useEffect(() => {
    if (prevYearsKey.current === yearsKey) return;
    prevYearsKey.current = yearsKey;
    if (offset > 0) setParams({ offset: undefined });
  }, [yearsKey, offset, setParams]);

  React.useEffect(() => {
    const qs = sp.toString();
    rememberDirectoryUrl("jb-last-publishers", qs ? `${pathname}?${qs}` : pathname);
  }, [pathname, sp]);

  const { data, isPending, isFetching, isError, error, refetch } = usePublishers(params);

  const rows = data?.items ?? [];
  const facets = data?.facets;

  // Pager math; total is the unpaginated filtered count.
  const total = data?.total ?? 0;

  const toggleFacet = (key: string, value: string) => {
    if (key === "oa_type" || key === "quartile" || key === "size") {
      const current = key === "oa_type" ? oaTypes : key === "quartile" ? quartiles : sizes;
      const next = current.includes(value)
        ? current.filter((v) => v !== value)
        : [...current, value];
      setParams({ [key]: next.join("|") || undefined });
      return;
    }
    if (key === "deal") {
      const canonical = normalizeDeal(value) ?? undefined;
      setParams({ deal: deal === canonical ? undefined : canonical });
      return;
    }
    if (key === "topic") {
      setParams({ topic: topic === value ? undefined : value });
      return;
    }
    if (key === "has_works") {
      setParams({ has_works: hasWorks === value ? undefined : value });
      return;
    }
    if (key === "has_apc") {
      setParams({ has_apc: hasApc === value ? undefined : value });
    }
  };

  const clearFilters = () => {
    lastCommittedQ.current = "";
    setInput("");
    setParams({
      q: undefined,
      oa_type: undefined,
      deal: undefined,
      quartile: undefined,
      size: undefined,
      topic: undefined,
      has_apc: undefined,
      has_works: undefined,
    });
  };

  // Tri-state column sort: natural → reversed → off (journal-table
  // convention). Off removes both params so the backend default applies
  // (relevance with a query, works high→low without).
  const cycleSort = (columnId: string) => {
    const spec = PUBLISHER_COLUMN_SORTS[columnId];
    if (!spec) return;
    if (sort !== spec.key) {
      setParams({ sort: spec.key, dir: spec.natural });
      return;
    }
    const atNatural = (dir ?? spec.natural) === spec.natural;
    setParams(
      atNatural
        ? { sort: spec.key, dir: spec.natural === "asc" ? "desc" : "asc" }
        : { sort: undefined, dir: undefined },
    );
  };
  const sortHeadState = { sort, dir, cycleSort, specs: PUBLISHER_COLUMN_SORTS };
  const ariaSortFor = (columnId: string): "ascending" | "descending" | undefined => {
    const spec = PUBLISHER_COLUMN_SORTS[columnId];
    if (!spec || sort !== spec.key) return undefined;
    return (dir ?? spec.natural) === "asc" ? "ascending" : "descending";
  };

  const groups: FacetGroupDef[] = [
    {
      key: "oa_type",
      label: t("facets.openAccess"),
      defaultOpen: true,
      values: facetValues(facets?.oa_type, oaTypes, (v) =>
        v in OA_TYPE_KEYS ? t(OA_TYPE_KEYS[v]) : v,
      ),
      activeValues: oaTypes,
    },
    {
      key: "deal",
      label: t("facets.deal"),
      defaultOpen: true,
      values: facetValues(facets?.deal, deal ? [deal] : [], (v) =>
        v in DEAL_KEYS ? t(DEAL_KEYS[v]) : v,
      ),
      activeValues: deal ? [deal] : [],
    },
    {
      key: "quartile",
      label: t("facets.quartile"),
      defaultOpen: true,
      values: facetValues(facets?.quartile, quartiles),
      activeValues: quartiles,
    },
    {
      key: "has_apc",
      label: t("facets.apcPrice"),
      defaultOpen: true,
      values: facetValues(facets?.has_apc, hasApc ? [hasApc] : [], (v) =>
        v === "yes" ? t("facets.priceInfo") : t("facets.noPriceInfo"),
      ),
      activeValues: hasApc ? [hasApc] : [],
    },
    {
      key: "has_works",
      label: t("facets.works"),
      defaultOpen: false,
      values: facetValues(facets?.has_works, hasWorks ? [hasWorks] : [], (v) =>
        v === "true" ? t("facets.hasWorks") : t("facets.noWorks"),
      ),
      activeValues: hasWorks ? [hasWorks] : [],
    },
    {
      key: "size",
      label: t("facets.journalCount"),
      defaultOpen: false,
      values: facetValues(facets?.size, sizes, (v) =>
        v === "10+"
          ? t("facets.sizeTenPlus")
          : t("facets.sizeRange", { range: v.replace("-", " to ") }),
      ),
      activeValues: sizes,
    },
    {
      key: "topic",
      label: t("facets.topic"),
      defaultOpen: false,
      searchable: true,
      initialVisible: 8,
      values: facetValues(facets?.topic, topic ? [topic] : [], undefined, 30),
      activeValues: topic ? [topic] : [],
    },
  ].filter((group) => group.values.length > 0);

  const filterChips: ActiveFilterChip[] = [
    ...(q
      ? [
          {
            id: "q",
            label: `Search: “${q}”`,
            onRemove: () => {
              lastCommittedQ.current = "";
              setInput("");
              setParams({ q: undefined });
            },
          },
        ]
      : []),
    ...oaTypes.map((v) => ({
      id: `oa_type:${v}`,
      label: `${t("facets.openAccess")}: ${v in OA_TYPE_KEYS ? t(OA_TYPE_KEYS[v]) : v}`,
      onRemove: () => toggleFacet("oa_type", v),
    })),
    ...(deal
      ? [
          {
            id: `deal:${deal}`,
            label: `${t("facets.deal")}: ${deal in DEAL_KEYS ? t(DEAL_KEYS[deal]) : deal}`,
            onRemove: () => toggleFacet("deal", deal),
          },
        ]
      : []),
    ...quartiles.map((v) => ({
      id: `quartile:${v}`,
      label: `${t("facets.quartile")}: ${v}`,
      onRemove: () => toggleFacet("quartile", v),
    })),
    ...(hasApc
      ? [
          {
            id: `has_apc:${hasApc}`,
            label: `${t("facets.apcPrice")}: ${
              hasApc === "yes" ? t("facets.priceInfo") : t("facets.noPriceInfo")
            }`,
            onRemove: () => toggleFacet("has_apc", hasApc),
          },
        ]
      : []),
    ...(hasWorks
      ? [
          {
            id: `has_works:${hasWorks}`,
            label: `${t("facets.works")}: ${
              hasWorks === "true" ? t("facets.hasWorks") : t("facets.noWorks")
            }`,
            onRemove: () => toggleFacet("has_works", hasWorks),
          },
        ]
      : []),
    ...sizes.map((v) => ({
      id: `size:${v}`,
      label: `${t("facets.journalCount")}: ${
        v === "10+"
          ? t("facets.sizeTenPlus")
          : t("facets.sizeRange", { range: v.replace("-", " to ") })
      }`,
      onRemove: () => toggleFacet("size", v),
    })),
    ...(topic
      ? [
          {
            id: `topic:${topic}`,
            label: `${t("facets.topic")}: ${topic}`,
            onRemove: () => toggleFacet("topic", topic),
          },
        ]
      : []),
  ];

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <header className="mb-6">
        <h1 className="mb-2 text-3xl font-bold text-balance">{t("title")}</h1>
        <p className="mb-4 max-w-2xl text-sm text-[var(--muted-foreground)]">
          {t("search.intro", { inst: site.short })}
        </p>
        <form
          className="flex max-w-2xl gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            update(input);
          }}
        >
          <div className="relative flex-1">
            <Input
              id={SEARCH_INPUT_ID}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape") event.currentTarget.blur();
              }}
              placeholder={t("search.placeholder")}
              aria-label={t("search.searchAria")}
            />
            {input === "" && (
              <kbd
                aria-hidden
                className="pointer-events-none absolute right-2.5 top-1/2 hidden -translate-y-1/2 rounded border border-[var(--border)] bg-[var(--muted)] px-1.5 py-0.5 text-[11px] text-[var(--muted-foreground)] [@media(hover:hover)_and_(pointer:fine)]:block"
              >
                /
              </kbd>
            )}
          </div>
          <Button type="submit">{t("search.searchButton")}</Button>
        </form>
      </header>

      <FilterLayout
        filters={
          <FacetGroupList
            groups={groups}
            onToggle={toggleFacet}
            updating={isFetching && !isPending}
          />
        }
        activeCount={filterChips.length}
        onReset={clearFilters}
        resetTitle={t("search.resetHint")}
        updating={isFetching && !isPending}
        disabled={data == null || !hasVisibleGroups(groups)}
      >
        <ActiveFiltersBar
          chips={filterChips}
          onClearAll={clearFilters}
          ariaLabel={tc("activeFilters.label")}
          clearLabel={tc("activeFilters.clearAll")}
          removeAriaPrefix={tc("activeFilters.remove")}
        />

        <Card className="relative overflow-hidden">
          <LoadingBar active={isFetching} />
          <CardContent className="pt-5">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] pb-3">
              <p className="inline-flex items-center gap-1.5 text-sm text-[var(--muted-foreground)]">
                {/* Announce only settled counts: while a fetch runs the live
                    region keeps its previous text, so typing never chatters. */}
                <span aria-live="polite">
                  {data
                    ? q
                      ? t("results.countMatching", { count: data.total, q })
                      : t("results.count", { count: data.total })
                    : ""}
                </span>
                {isFetching && data ? (
                  <span className="inline-flex items-center gap-1">
                    <Loader2 aria-hidden className="size-3 animate-spin" />
                    {t("results.updating")}
                  </span>
                ) : null}
              </p>
              <div className="flex min-w-0 flex-col items-start gap-1 text-sm min-[768px]:flex-row min-[768px]:items-center min-[768px]:gap-2">
                <label
                  htmlFor="publisher-sort"
                  className="whitespace-nowrap text-xs text-[var(--muted-foreground)]"
                >
                  {t("search.sortBy")}
                </label>
                <select
                  id="publisher-sort"
                  title={t("search.sortHint")}
                  value={sort ?? "default"}
                  onChange={(event) =>
                    setParams({
                      sort: event.target.value === "default" ? undefined : event.target.value,
                      // A sort change invalidates the old direction: keeping
                      // `dir` would flip the freshly chosen label.
                      dir: undefined,
                    })
                  }
                  className={SELECT_CLASS}
                >
                  {/* The backend default is relevance with a query, works count
                      without; say so instead of guessing one label. */}
                  <option value="default">{q ? t("sort.relevance") : t("sort.works")}</option>
                  {(
                    [
                      ["name", t("sort.name")],
                      ["journals", t("sort.journals")],
                      ["works", t("sort.works")],
                      ["deals", t("sort.deals")],
                      ["apc", t("sort.apc")],
                    ] as [PublisherSearchSort, string][]
                  ).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {isError ? (
              <div className="py-10 text-center">
                <p className="text-[var(--destructive)]">{errorMessage(tc, error)}</p>
                <Button variant="outline" size="sm" className="mt-3" onClick={() => refetch()}>
                  {t("results.retry")}
                </Button>
              </div>
            ) : isPending ? (
              <ListSkeletonRows rows={8} />
            ) : rows.length === 0 ? (
              <div className="py-10 text-center text-[var(--muted-foreground)]">
                {q && !anyFilter ? (
                  <>{t("results.emptyQuery", { q })}</>
                ) : (
                  <>
                    {anyFilter ? t("results.emptyFilters") : t("results.empty")}
                    {anyFilter && (
                      <div className="mt-3">
                        <Button variant="outline" size="sm" onClick={clearFilters}>
                          {t("results.clearFilters")}
                        </Button>
                      </div>
                    )}
                  </>
                )}
              </div>
            ) : (
              <>
                {/* Stacked cards on narrow viewports: eight columns would
                    push the counts off-screen behind horizontal scrolling. */}
                <ul
                  className={
                    isFetching
                      ? "opacity-60 transition-opacity duration-150 md:hidden"
                      : "transition-opacity duration-150 md:hidden"
                  }
                  aria-label={t("results.listAria")}
                >
                  {rows.map((p) => (
                    <li
                      key={p.name}
                      className="border-b border-[var(--border)] py-3 first:pt-0 last:border-0 last:pb-0"
                    >
                      <Link
                        href={`/${inst}/publisher/${encodeNamePath(p.name)}`}
                        className="font-medium text-[var(--foreground)] underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                      >
                        {displayPublisherName(p.name)}
                      </Link>
                      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs tabular-nums text-[var(--muted-foreground)]">
                        <span>{t("units.journals", { count: p.n_journals })}</span>
                        <span>{t("units.works", { count: p.n_works })}</span>
                        {p.deal_journals > 0 && (
                          <span>{t("units.dealCoveredShort", { count: p.deal_journals })}</span>
                        )}
                      </div>
                      <div className="mt-1.5 max-w-48">
                        <OaCompositionBar counts={p.oa_types} total={p.n_journals} />
                      </div>
                      {p.topics.length > 0 && (
                        <div className="mt-1 text-xs text-[var(--muted-foreground)]">
                          {p.topics
                            .slice(0, 2)
                            .map((topic) => topic.name)
                            .join(" · ")}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
                <div
                  className={
                    isFetching
                      ? "hidden opacity-60 transition-opacity duration-150 md:block"
                      : "hidden transition-opacity duration-150 md:block"
                  }
                >
                  <Table>
                    <caption className="sr-only">{t("results.tableCaption")}</caption>
                    <TableHeader>
                      <TableRow>
                        <TableHead aria-sort={ariaSortFor("name")}>
                          <SortHead
                            columnId="name"
                            label={t("table.publisher")}
                            state={sortHeadState}
                          />
                        </TableHead>
                        <TableHead className="text-right" aria-sort={ariaSortFor("journals")}>
                          <SortHead
                            columnId="journals"
                            label={t("table.journals")}
                            state={sortHeadState}
                          />
                        </TableHead>
                        <TableHead className="text-right" aria-sort={ariaSortFor("works")}>
                          <SortHead
                            columnId="works"
                            label={t("table.works")}
                            state={sortHeadState}
                          />
                        </TableHead>
                        <TableHead>{t("table.oaComposition")}</TableHead>
                        <TableHead className="text-right" aria-sort={ariaSortFor("deals")}>
                          <SortHead
                            columnId="deals"
                            label={t("table.deals")}
                            state={sortHeadState}
                          />
                        </TableHead>
                        <TableHead>{t("table.quartiles")}</TableHead>
                        <TableHead aria-sort={ariaSortFor("apc")}>
                          <SortHead columnId="apc" label={t("table.apc")} state={sortHeadState} />
                        </TableHead>
                        <TableHead>{t("table.topics")}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {rows.map((p) => (
                        <TableRow key={p.name}>
                          <TableCell className="font-medium">
                            <Link
                              href={`/${inst}/publisher/${encodeNamePath(p.name)}`}
                              className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                            >
                              <span
                                className="block max-w-56 truncate"
                                title={displayPublisherName(p.name)}
                              >
                                {displayPublisherName(p.name)}
                              </span>
                            </Link>
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {p.n_journals.toLocaleString("en")}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {p.n_works.toLocaleString("en")}
                          </TableCell>
                          <TableCell>
                            <div className="w-28">
                              <OaCompositionBar counts={p.oa_types} total={p.n_journals} />
                            </div>
                          </TableCell>
                          <TableCell className="whitespace-nowrap text-right tabular-nums">
                            {p.deal_journals.toLocaleString("en")}
                            <span className="text-[var(--muted-foreground)]">
                              {" "}
                              of {p.n_journals.toLocaleString("en")}
                            </span>
                          </TableCell>
                          <TableCell>
                            <QuartileChips item={p} />
                          </TableCell>
                          <TableCell>
                            <ApcCell item={p} />
                          </TableCell>
                          <TableCell>
                            {p.topics.length > 0 ? (
                              <span
                                className="block max-w-40 truncate"
                                title={p.topics
                                  .slice(0, 2)
                                  .map((topic) => `${topic.name} (${Math.round(topic.n)})`)
                                  .join(" · ")}
                              >
                                {p.topics
                                  .slice(0, 2)
                                  .map((topic) => topic.name)
                                  .join(" · ")}
                              </span>
                            ) : (
                              <span className="text-[var(--muted-foreground)]">—</span>
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
                <DirectoryPager
                  offset={offset}
                  shown={rows.length}
                  total={total}
                  limit={pageSize}
                  onOffset={(nextOffset) =>
                    setParams({ offset: nextOffset > 0 ? String(nextOffset) : undefined })
                  }
                  onLimit={(nextLimit) =>
                    setParams({ limit: nextLimit === 50 ? undefined : String(nextLimit) })
                  }
                  perPageLabel={t("search.perPage")}
                  prevLabel={t("results.prev")}
                  nextLabel={t("results.next")}
                  isFetching={isFetching}
                />
              </>
            )}
          </CardContent>
        </Card>
      </FilterLayout>
    </div>
  );
}
