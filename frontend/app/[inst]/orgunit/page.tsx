"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { FacetGroupList, type FacetGroupDef, type FacetValue } from "@/components/filter-panel";
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
import { useOrgUnits } from "@/hooks/use-api";
import { useInstitution } from "@/hooks/use-institution";
import { useSiteMeta } from "@/hooks/use-site-meta";
import {
  encodeNamePath,
  errorMessage,
  type OrgUnitItem,
  type OrgUnitLevel,
  type OrgUnitSearchSort,
} from "@/lib/api";
import { formatEur } from "@/lib/format";
import { ORGUNIT_COLUMN_SORTS } from "@/lib/search-config";

const SEARCH_INPUT_ID = "orgunit-search";

const PAGE_SIZES = [25, 50, 100];

/** Works-bucket facet value → message key for its label. */
const WORKS_BUCKET_KEYS: Record<string, string> = {
  "1-4": "list.works1to4",
  "5-19": "list.works5to19",
  "20-49": "list.works20to49",
  "50+": "list.works50plus",
};

/** Matches the journal page's sort-select styling. */
const SELECT_CLASS =
  "h-9 rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2";

/** Comma-joined multi-select param → list of values (journal-search convention). */
function paramValues(sp: { get(key: string): string | null }, key: string): string[] {
  return (sp.get(key) ?? "").split("|").filter(Boolean);
}

/** Top 8 buckets of a facet record, with active values kept visible. */
function facetValues(counts: Record<string, number> | undefined, active: string[]): FacetValue[] {
  const list: FacetValue[] = Object.entries(counts ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([value, count]) => ({ value, count }));
  for (const value of active) if (!list.some((v) => v.value === value)) list.unshift({ value });
  return list;
}

/** Deal-covered works as "12 (18%)"; the share needs a nonzero denominator. */
function DealWorksCell({ unit }: { unit: OrgUnitItem }) {
  const t = useTranslations("orgunits");
  const share = unit.n_works > 0 ? Math.round((unit.deal_works / unit.n_works) * 100) : 0;
  return (
    <span className="tabular-nums" title={t("tooltips.dealWorks")}>
      {unit.deal_works.toLocaleString("en")}
      {unit.n_works > 0 && <span className="text-[var(--muted-foreground)]"> ({share}%)</span>}
    </span>
  );
}

export default function OrgUnitSearchPage() {
  // useSearchParams needs a Suspense boundary during prerender.
  return (
    <React.Suspense fallback={null}>
      <OrgUnitsView />
    </React.Suspense>
  );
}

function OrgUnitsView() {
  const t = useTranslations("orgunits");
  const tc = useTranslations("common");
  const inst = useInstitution();
  const site = useSiteMeta();
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const q = sp.get("q") ?? "";
  const [input, setInput] = React.useState(q);

  const levelParam = sp.get("level");
  const level: OrgUnitLevel =
    levelParam === "group" || levelParam === "institute" ? levelParam : "faculty";
  const faculty = paramValues(sp, "faculty");
  const works = paramValues(sp, "works");
  const usesDeals = sp.get("uses_deals") === "true";
  const anyFilter = faculty.length > 0 || works.length > 0 || usesDeals;

  // Sort and paging are URL state too; the backend default is
  // relevance-with-q, else works desc.
  const sortParam = sp.get("sort");
  const sort: OrgUnitSearchSort | undefined = [
    "relevance",
    "name",
    "authors",
    "works",
    "deal_works",
  ].includes(sortParam ?? "")
    ? (sortParam as OrgUnitSearchSort)
    : undefined;
  const dirParam = sp.get("dir");
  const dir: "asc" | "desc" | null = dirParam === "asc" || dirParam === "desc" ? dirParam : null;
  const limitParam = parseInt(sp.get("limit") ?? "", 10);
  const pageSize = PAGE_SIZES.includes(limitParam) ? limitParam : 50;
  const offsetParam = parseInt(sp.get("offset") ?? "", 10);
  const offset = Number.isFinite(offsetParam) && offsetParam > 0 ? offsetParam : 0;

  const setParams = React.useCallback(
    (patch: Record<string, string | undefined>) => {
      const next = new URLSearchParams(sp.toString());
      for (const [key, value] of Object.entries(patch)) {
        if (!value) next.delete(key);
        else next.set(key, value);
      }
      // Any query, filter, sort, or page-size change restarts at page 1;
      // only the pager itself touches offset directly.
      if (!("offset" in patch)) next.delete("offset");
      router.replace(`${pathname}?${next}`, { scroll: false });
    },
    [pathname, router, sp],
  );

  const update = React.useCallback(
    (value: string) => setParams({ q: value || undefined }),
    [setParams],
  );

  // Live search with debounce; keep the input in sync with back/forward nav.
  React.useEffect(() => {
    setInput(q);
  }, [q]);
  React.useEffect(() => {
    const t = setTimeout(() => {
      if (input !== q) update(input);
    }, 300);
    return () => clearTimeout(t);
  }, [input, q, update]);

  const { data, isPending, isFetching, isError, error, refetch } = useOrgUnits({
    level,
    q: q || undefined,
    faculty: faculty.length > 0 ? faculty : undefined,
    works: works.length > 0 ? works : undefined,
    uses_deals: usesDeals || undefined,
    sort,
    dir: dir ?? undefined,
    offset: offset > 0 ? offset : undefined,
    limit: pageSize === 50 ? undefined : pageSize,
    include_facets: true,
  });

  const rows = data?.items ?? [];
  // Hide the APC column when no unit has APC data (e.g. ut); otherwise it
  // reads as a column of broken dashes.
  const showApc = rows.some((u) => u.apc_n > 0);
  const facets = data?.facets;

  // Pager math; total is the unpaginated filtered count.
  const total = data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.min(Math.floor(offset / pageSize) + 1, pageCount);
  const showPager = total > pageSize;

  const toggleFacet = (key: string, value: string) => {
    if (key === "faculty") {
      const next = faculty.includes(value)
        ? faculty.filter((v) => v !== value)
        : [...faculty, value];
      setParams({ faculty: next.join("|") || undefined });
      return;
    }
    if (key === "works") {
      const next = works.includes(value) ? works.filter((v) => v !== value) : [...works, value];
      setParams({ works: next.join("|") || undefined });
      return;
    }
    if (key === "uses_deals") {
      setParams({ uses_deals: usesDeals ? undefined : "true" });
    }
  };

  const clearFilters = () =>
    setParams({ faculty: undefined, works: undefined, uses_deals: undefined });

  // Tri-state column sort: natural → reversed → off (journal-table
  // convention). Off removes both params so the backend default applies
  // (relevance with a query, works high→low without).
  const cycleSort = (columnId: string) => {
    const spec = ORGUNIT_COLUMN_SORTS[columnId];
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
  const sortHeadState = { sort, dir, cycleSort, specs: ORGUNIT_COLUMN_SORTS };
  const ariaSortFor = (columnId: string): "ascending" | "descending" | undefined => {
    const spec = ORGUNIT_COLUMN_SORTS[columnId];
    if (!spec || sort !== spec.key) return undefined;
    return (dir ?? spec.natural) === "asc" ? "ascending" : "descending";
  };

  const groups: FacetGroupDef[] = [
    ...(level === "group"
      ? [
          {
            key: "faculty",
            label: t("columns.faculty"),
            defaultOpen: true,
            values: facetValues(facets?.faculty, faculty),
            activeValues: faculty,
          },
        ]
      : []),
    {
      key: "works",
      label: t("list.filter.publications"),
      defaultOpen: true,
      values: facetValues(facets?.size, works).map((v) => ({
        ...v,
        label: WORKS_BUCKET_KEYS[v.value] ? t(WORKS_BUCKET_KEYS[v.value]) : v.value,
      })),
      activeValues: works,
    },
    // The backend only accepts uses_deals=true, so the "no" bucket is not
    // offered as a filter; the count is absent until facets load.
    {
      key: "uses_deals",
      label: t("list.filter.deal"),
      defaultOpen: true,
      values: [{ value: "yes", label: t("list.filter.usesDeals"), count: facets?.uses_deals?.yes }],
      activeValues: usesDeals ? ["yes"] : [],
    },
  ];

  const unitHref = (unit: { level: OrgUnitLevel; name: string }) =>
    `/${inst}/orgunit/${unit.level}/${encodeNamePath(unit.name)}`;

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <div className="flex flex-col min-[960px]:grid min-[960px]:grid-cols-[15rem_minmax(0,1fr)] min-[960px]:items-start min-[960px]:gap-6 min-[1280px]:grid-cols-[18rem_minmax(0,1fr)] min-[1280px]:gap-8">
        <section className="order-1 mb-8 min-[960px]:col-start-2 min-[960px]:row-start-1 min-[960px]:mb-6">
          <h1 className="mb-3 text-3xl font-bold text-balance">{t("list.title")}</h1>
          <p className="mb-6 max-w-2xl text-[var(--muted-foreground)]">
            {t("list.intro", { institution: site.name })}
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
                placeholder={t(`list.search.${level}`)}
                aria-label={t(`list.search.${level}`)}
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
            <Button type="submit">{t("list.search.action")}</Button>
          </form>
        </section>

        {/* Stacked filter card: the only filter UI below 960px. */}
        {data != null && (
          <section className="order-2 mb-6 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 min-[960px]:hidden">
            <FacetGroupList groups={groups} onToggle={toggleFacet} variant="chips" />
          </section>
        )}

        {/* Wide-screen sidebar: sticky, scrolls on its own when long. */}
        {data != null && (
          <aside className="sticky top-20 hidden max-h-[calc(100vh-6rem)] self-start overflow-y-auto rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 min-[960px]:col-start-1 min-[960px]:row-span-2 min-[960px]:row-start-1 min-[960px]:block">
            <FacetGroupList groups={groups} onToggle={toggleFacet} variant="rows" />
          </aside>
        )}

        <div className="order-3 min-w-0 min-[960px]:col-start-2 min-[960px]:row-start-2">
          <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
            {/* Level toggle: switching also drops the faculty facet, which
              only applies to research groups. */}
            <div
              role="group"
              aria-label={t("list.levelLabel")}
              className="flex overflow-hidden rounded-[var(--radius)] border border-[var(--input)]"
            >
              <Button
                variant={level === "faculty" ? "secondary" : "ghost"}
                size="sm"
                className="rounded-none"
                aria-pressed={level === "faculty"}
                onClick={() => setParams({ level: undefined, faculty: undefined })}
              >
                {t("list.levelToggle.faculty")}
              </Button>
              <Button
                variant={level === "group" ? "secondary" : "ghost"}
                size="sm"
                className="rounded-none"
                aria-pressed={level === "group"}
                onClick={() => setParams({ level: "group", faculty: undefined })}
              >
                {t("list.levelToggle.group")}
              </Button>
              <Button
                variant={level === "institute" ? "secondary" : "ghost"}
                size="sm"
                className="rounded-none"
                aria-pressed={level === "institute"}
                onClick={() => setParams({ level: "institute", faculty: undefined })}
              >
                {t("list.levelToggle.institute")}
              </Button>
            </div>
            <label htmlFor="orgunit-sort" className="whitespace-nowrap">
              {t("list.sortBy")}
            </label>
            <select
              id="orgunit-sort"
              title={t("list.sortOrderTitle")}
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
              <option value="default">{q ? t("list.sort.relevance") : t("list.sort.works")}</option>
              {(
                [
                  ["name", t("list.sort.name")],
                  ["authors", t("list.sort.authors")],
                  ["works", t("list.sort.works")],
                  ["deal_works", t("list.sort.dealWorks")],
                ] as [OrgUnitSearchSort, string][]
              ).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            <label htmlFor="orgunit-per-page" className="whitespace-nowrap">
              {t("list.perPage")}
            </label>
            <select
              id="orgunit-per-page"
              title={t("list.perPageTitle")}
              value={pageSize}
              onChange={(event) =>
                setParams({
                  limit: event.target.value === "50" ? undefined : event.target.value,
                })
              }
              className={SELECT_CLASS}
            >
              {PAGE_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
            {anyFilter && (
              <Button
                variant="ghost"
                size="sm"
                className="text-[var(--muted-foreground)]"
                title={t("list.resetFiltersTitle")}
                onClick={clearFilters}
              >
                {t("list.resetFilters")}
              </Button>
            )}
          </div>
          <Card>
            <CardContent className="pt-6">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm text-[var(--muted-foreground)]">
                  {/* Announce only settled counts: while a fetch runs the live
                    region keeps its previous text, so typing never chatters. */}
                  <span aria-live="polite">
                    {data
                      ? `${t(`counts.${level}`, { count: data.total })}${q ? ` ${t("list.matching", { query: q })}` : ""}`
                      : ""}
                  </span>
                  {isFetching && data ? ` ${t("list.updating")}` : ""}
                </p>
                {showPager && (
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      aria-label={t("list.pager.prevLabel")}
                      disabled={offset === 0}
                      onClick={() =>
                        setParams({
                          offset: String(Math.max(0, offset - pageSize)),
                        })
                      }
                    >
                      <ChevronLeft aria-hidden className="size-4" /> {t("list.pager.prev")}
                    </Button>
                    <span className="whitespace-nowrap text-sm tabular-nums text-[var(--muted-foreground)]">
                      {t("list.pager.page", { page, pages: pageCount })}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      aria-label={t("list.pager.nextLabel")}
                      disabled={offset + pageSize >= total}
                      onClick={() => setParams({ offset: String(offset + pageSize) })}
                    >
                      {t("list.pager.next")} <ChevronRight aria-hidden className="size-4" />
                    </Button>
                  </div>
                )}
              </div>

              {isError ? (
                <div className="py-10 text-center">
                  <p className="text-[var(--destructive)]">{errorMessage(tc, error)}</p>
                  <Button variant="outline" size="sm" className="mt-3" onClick={() => refetch()}>
                    {t("list.retry")}
                  </Button>
                </div>
              ) : isPending ? (
                <ListSkeletonRows rows={8} />
              ) : rows.length === 0 ? (
                <div className="py-10 text-center text-[var(--muted-foreground)]">
                  {q && !anyFilter ? (
                    <>{t(`list.emptyQuery.${level}`, { query: q })}</>
                  ) : !anyFilter ? (
                    // Unfiltered empty: for an institution whose orgunit
                    // corpus was never harvested (e.g. rug) this is a data
                    // gap, not a filter problem.
                    <>
                      {t("list.emptyNoData", {
                        institution: site.name || t("list.institutionFallback"),
                      })}
                    </>
                  ) : (
                    <>
                      {t(`list.emptyFiltered.${level}`)}
                      <div className="mt-3">
                        <Button variant="outline" size="sm" onClick={clearFilters}>
                          {t("list.clearFilters")}
                        </Button>
                      </div>
                    </>
                  )}
                </div>
              ) : (
                <>
                  {/* Stacked cards on narrow viewports: seven columns would
                    push the counts off-screen behind horizontal scrolling. */}
                  <ul
                    className={isFetching ? "opacity-60 md:hidden" : "md:hidden"}
                    aria-label={t("list.resultsListLabel")}
                  >
                    {rows.map((u) => (
                      <li
                        key={`${u.level}:${u.name}`}
                        className="border-b border-[var(--border)] py-3 first:pt-0 last:border-0 last:pb-0"
                      >
                        <Link
                          href={unitHref(u)}
                          className="font-medium text-[var(--foreground)] underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                        >
                          {u.name}
                        </Link>
                        <div className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                          {u.faculty || "—"}
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs tabular-nums text-[var(--muted-foreground)]">
                          <span>{t("counts.author", { count: u.n_authors })}</span>
                          <span>{t("counts.work", { count: u.n_works })}</span>
                          {u.deal_works > 0 && (
                            <span>{t("counts.dealWork", { count: u.deal_works })}</span>
                          )}
                          {u.apc_n > 0 && (
                            <span>
                              {t("list.mobileApc", { euro: formatEur(u.apc_euro_total) })}
                            </span>
                          )}
                        </div>
                        {u.topics.length > 0 && (
                          <div className="mt-1 text-xs text-[var(--muted-foreground)]">
                            {u.topics
                              .slice(0, 2)
                              .map((topic) => topic.name)
                              .join(" · ")}
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                  <div className={isFetching ? "hidden opacity-60 md:block" : "hidden md:block"}>
                    <Table>
                      <caption className="sr-only">{t("list.tableCaption")}</caption>
                      <TableHeader>
                        <TableRow>
                          <TableHead aria-sort={ariaSortFor("name")}>
                            <SortHead
                              columnId="name"
                              label={t("columns.name")}
                              state={sortHeadState}
                            />
                          </TableHead>
                          {level === "group" && <TableHead>{t("columns.faculty")}</TableHead>}
                          <TableHead className="text-right" aria-sort={ariaSortFor("authors")}>
                            <SortHead
                              columnId="authors"
                              label={t("columns.authors")}
                              state={sortHeadState}
                            />
                          </TableHead>
                          <TableHead className="text-right" aria-sort={ariaSortFor("works")}>
                            <SortHead
                              columnId="works"
                              label={t("columns.works")}
                              state={sortHeadState}
                            />
                          </TableHead>
                          <TableHead className="text-right" aria-sort={ariaSortFor("deal_works")}>
                            <SortHead
                              columnId="deal_works"
                              label={t("columns.dealWorks")}
                              state={sortHeadState}
                            />
                          </TableHead>
                          {showApc && (
                            <TableHead className="text-right">{t("columns.apc")}</TableHead>
                          )}
                          <TableHead>{t("columns.topics")}</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {rows.map((u) => (
                          <TableRow key={`${u.level}:${u.name}`}>
                            <TableCell className="font-medium">
                              <Link
                                href={unitHref(u)}
                                className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                              >
                                <span className="line-clamp-2" title={u.name}>
                                  {u.name}
                                </span>
                              </Link>
                            </TableCell>
                            {level === "group" && (
                              <TableCell>
                                <span
                                  className="block max-w-44 truncate"
                                  title={u.faculty ?? undefined}
                                >
                                  {u.faculty || (
                                    <span className="text-[var(--muted-foreground)]">—</span>
                                  )}
                                </span>
                              </TableCell>
                            )}
                            <TableCell className="text-right tabular-nums">
                              {u.n_authors.toLocaleString("en")}
                            </TableCell>
                            <TableCell className="text-right tabular-nums">
                              {u.n_works.toLocaleString("en")}
                            </TableCell>
                            <TableCell className="text-right">
                              <DealWorksCell unit={u} />
                            </TableCell>
                            {showApc && (
                              <TableCell className="whitespace-nowrap text-right tabular-nums">
                                {u.apc_n > 0 ? (
                                  <span title={t("tooltips.apc", { count: u.apc_n })}>
                                    {formatEur(u.apc_euro_total)} €{" "}
                                    <span className="text-[var(--muted-foreground)]">
                                      ({u.apc_n})
                                    </span>
                                  </span>
                                ) : (
                                  <span className="text-[var(--muted-foreground)]">—</span>
                                )}
                              </TableCell>
                            )}
                            <TableCell>
                              {u.topics.length > 0 ? (
                                <span
                                  className="block max-w-40 truncate"
                                  title={u.topics
                                    .slice(0, 2)
                                    .map((topic) => `${topic.name} (${Math.round(topic.n)})`)
                                    .join(" · ")}
                                >
                                  {u.topics
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
                  <p className="mt-4 text-xs text-[var(--muted-foreground)]">
                    {t("list.showing", { shown: rows.length, total: data?.total ?? 0 })}
                  </p>
                </>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
