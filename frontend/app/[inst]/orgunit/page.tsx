"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import {
  FacetGroupList,
  type FacetGroupDef,
  type FacetValue,
} from "@/components/filter-panel";
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

const SEARCH_INPUT_ID = "orgunit-search";

const PAGE_SIZES = [25, 50, 100];

const WORKS_LABELS: Record<string, string> = {
  "1-4": "1–4 works",
  "5-19": "5–19 works",
  "20-49": "20–49 works",
  "50+": "50+ works",
};

/** Matches the journal page's sort-select styling. */
const SELECT_CLASS =
  "h-9 rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2";

/** Comma-joined multi-select param → list of values (journal-search convention). */
function paramValues(
  sp: { get(key: string): string | null },
  key: string,
): string[] {
  return (sp.get(key) ?? "").split("|").filter(Boolean);
}

/** Top 8 buckets of a facet record, with active values kept visible. */
function facetValues(
  counts: Record<string, number> | undefined,
  active: string[],
): FacetValue[] {
  const list: FacetValue[] = Object.entries(counts ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([value, count]) => ({ value, count }));
  for (const value of active)
    if (!list.some((v) => v.value === value)) list.unshift({ value });
  return list;
}

/** Deal-covered works as "12 (18%)"; the share needs a nonzero denominator. */
function DealWorksCell({ unit }: { unit: OrgUnitItem }) {
  const share =
    unit.n_works > 0
      ? Math.round((unit.deal_works / unit.n_works) * 100)
      : 0;
  return (
    <span
      className="tabular-nums"
      title="Works in journals covered by an open access deal"
    >
      {unit.deal_works.toLocaleString("en")}
      {unit.n_works > 0 && (
        <span className="text-[var(--muted-foreground)]"> ({share}%)</span>
      )}
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
  const inst = useInstitution();
  const site = useSiteMeta();
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const q = sp.get("q") ?? "";
  const [input, setInput] = React.useState(q);

  const level: OrgUnitLevel = sp.get("level") === "group" ? "group" : "faculty";
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
  const limitParam = parseInt(sp.get("limit") ?? "", 10);
  const pageSize = PAGE_SIZES.includes(limitParam) ? limitParam : 50;
  const offsetParam = parseInt(sp.get("offset") ?? "", 10);
  const offset =
    Number.isFinite(offsetParam) && offsetParam > 0 ? offsetParam : 0;

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
    offset: offset > 0 ? offset : undefined,
    limit: pageSize === 50 ? undefined : pageSize,
    include_facets: true,
  });

  const rows = data?.items ?? [];
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
      const next = works.includes(value)
        ? works.filter((v) => v !== value)
        : [...works, value];
      setParams({ works: next.join("|") || undefined });
      return;
    }
    if (key === "uses_deals") {
      setParams({ uses_deals: usesDeals ? undefined : "true" });
    }
  };

  const clearFilters = () =>
    setParams({ faculty: undefined, works: undefined, uses_deals: undefined });

  const groups: FacetGroupDef[] = [
    ...(level === "group"
      ? [
          {
            key: "faculty",
            label: "Faculty",
            defaultOpen: true,
            values: facetValues(facets?.faculty, faculty),
            activeValues: faculty,
          },
        ]
      : []),
    {
      key: "works",
      label: "Publications",
      defaultOpen: true,
      values: facetValues(facets?.size, works).map((v) => ({
        ...v,
        label: WORKS_LABELS[v.value] ?? v.value,
      })),
      activeValues: works,
    },
    // The backend only accepts uses_deals=true, so the "no" bucket is not
    // offered as a filter; the count is absent until facets load.
    {
      key: "uses_deals",
      label: "Open access deal",
      defaultOpen: true,
      values: [{ value: "yes", label: "Uses deals", count: facets?.uses_deals?.yes }],
      activeValues: usesDeals ? ["yes"] : [],
    },
  ];

  const unitHref = (unit: { level: OrgUnitLevel; name: string }) =>
    `/${inst}/orgunit/${unit.level}/${encodeNamePath(unit.name)}`;

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <div className="flex flex-col min-[960px]:grid min-[960px]:grid-cols-[15rem_minmax(0,1fr)] min-[960px]:items-start min-[960px]:gap-6 min-[1280px]:grid-cols-[18rem_minmax(0,1fr)] min-[1280px]:gap-8">
        <section className="order-1 mb-8 min-[960px]:col-start-2 min-[960px]:row-start-1 min-[960px]:mb-6">
          <h1 className="mb-3 text-3xl font-bold text-balance">Faculties</h1>
          <p className="mb-6 max-w-2xl text-[var(--muted-foreground)]">
            Browse the organisational units of {site.name}: faculties and their
            research groups, with publishing output, deal usage, and APC spend.
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
                placeholder={
                  level === "group"
                    ? "Search research groups"
                    : "Search faculties"
                }
                aria-label={level === "group" ? "Search research groups" : "Search faculties"}
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
            <Button type="submit">Search</Button>
          </form>
        </section>

        {/* Stacked filter card: the only filter UI below 960px. */}
        {data != null && (
          <section className="order-2 mb-6 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 min-[960px]:hidden">
            <FacetGroupList
              groups={groups}
              onToggle={toggleFacet}
              variant="chips"
            />
          </section>
        )}

        {/* Wide-screen sidebar: sticky, scrolls on its own when long. */}
        {data != null && (
          <aside className="sticky top-20 hidden max-h-[calc(100vh-6rem)] self-start overflow-y-auto rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 min-[960px]:col-start-1 min-[960px]:row-span-2 min-[960px]:row-start-1 min-[960px]:block">
            <FacetGroupList
              groups={groups}
              onToggle={toggleFacet}
              variant="rows"
            />
          </aside>
        )}

        <div className="order-3 min-w-0 min-[960px]:col-start-2 min-[960px]:row-start-2">
          <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
            {/* Level toggle: switching also drops the faculty facet, which
              only applies to research groups. */}
            <div
              role="group"
              aria-label="Unit level"
              className="flex overflow-hidden rounded-[var(--radius)] border border-[var(--input)]"
            >
              <Button
                variant={level === "faculty" ? "secondary" : "ghost"}
                size="sm"
                className="rounded-none"
                aria-pressed={level === "faculty"}
                onClick={() => setParams({ level: undefined, faculty: undefined })}
              >
                Faculties
              </Button>
              <Button
                variant={level === "group" ? "secondary" : "ghost"}
                size="sm"
                className="rounded-none"
                aria-pressed={level === "group"}
                onClick={() => setParams({ level: "group", faculty: undefined })}
              >
                Research groups
              </Button>
            </div>
            <label htmlFor="orgunit-sort" className="whitespace-nowrap">
              Sort by
            </label>
            <select
              id="orgunit-sort"
              title="Order of the results"
              value={sort ?? "default"}
              onChange={(event) =>
                setParams({
                  sort:
                    event.target.value === "default"
                      ? undefined
                      : event.target.value,
                })
              }
              className={SELECT_CLASS}
            >
              {/* The backend default is relevance with a query, works count
                without; say so instead of guessing one label. */}
              <option value="default">
                {q ? "Relevance" : "Works (high→low)"}
              </option>
              {(
                [
                  ["name", "Name (A→Z)"],
                  ["authors", "Authors (high→low)"],
                  ["works", "Works (high→low)"],
                  ["deal_works", "Deal-covered works (high→low)"],
                ] as [OrgUnitSearchSort, string][]
              ).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            <label htmlFor="orgunit-per-page" className="whitespace-nowrap">
              Per page
            </label>
            <select
              id="orgunit-per-page"
              title="Results per page"
              value={pageSize}
              onChange={(event) =>
                setParams({
                  limit:
                    event.target.value === "50" ? undefined : event.target.value,
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
                title="Clears all active filters"
                onClick={clearFilters}
              >
                Reset filters
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
                      ? `${data.total.toLocaleString("en")} ${level === "group" ? "research group" : "faculty"}${data.total === 1 ? "" : "s"}${q ? ` matching “${q}”` : ""}`
                      : ""}
                  </span>
                  {isFetching && data ? " · updating…" : ""}
                </p>
                {showPager && (
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      aria-label="Previous page"
                      disabled={offset === 0}
                      onClick={() =>
                        setParams({
                          offset: String(Math.max(0, offset - pageSize)),
                        })
                      }
                    >
                      <ChevronLeft aria-hidden className="size-4" /> Prev
                    </Button>
                    <span className="whitespace-nowrap text-sm tabular-nums text-[var(--muted-foreground)]">
                      Page {page.toLocaleString("en")} of{" "}
                      {pageCount.toLocaleString("en")}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      aria-label="Next page"
                      disabled={offset + pageSize >= total}
                      onClick={() => setParams({ offset: String(offset + pageSize) })}
                    >
                      Next <ChevronRight aria-hidden className="size-4" />
                    </Button>
                  </div>
                )}
              </div>

              {isError ? (
                <div className="py-10 text-center">
                  <p className="text-[var(--destructive)]">
                    {errorMessage(error)}
                  </p>
                  <Button
                    variant="outline"
                    size="sm"
                    className="mt-3"
                    onClick={() => refetch()}
                  >
                    Retry
                  </Button>
                </div>
              ) : isPending ? (
                <ListSkeletonRows rows={8} />
              ) : rows.length === 0 ? (
                <div className="py-10 text-center text-[var(--muted-foreground)]">
                  {q && !anyFilter ? (
                    <>No {level === "group" ? "research groups" : "faculties"} match &ldquo;{q}&rdquo;.</>
                  ) : (
                    <>
                      No{" "}
                      {level === "group" ? "research groups" : "faculties"}{" "}
                      match{anyFilter ? " these filters" : ""}.
                      {anyFilter && (
                        <div className="mt-3">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={clearFilters}
                          >
                            Clear filters
                          </Button>
                        </div>
                      )}
                    </>
                  )}
                </div>
              ) : (
                <>
                  {/* Stacked cards on narrow viewports: seven columns would
                    push the counts off-screen behind horizontal scrolling. */}
                  <ul
                    className={
                      isFetching ? "opacity-60 md:hidden" : "md:hidden"
                    }
                    aria-label="Organisational unit results"
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
                          <span>
                            {u.n_authors.toLocaleString("en")}{" "}
                            {u.n_authors === 1 ? "author" : "authors"}
                          </span>
                          <span>
                            {u.n_works.toLocaleString("en")}{" "}
                            {u.n_works === 1 ? "work" : "works"}
                          </span>
                          {u.deal_works > 0 && (
                            <span>{u.deal_works.toLocaleString("en")} deal-covered</span>
                          )}
                          {u.apc_n > 0 && (
                            <span>APC {formatEur(u.apc_euro_total)} €</span>
                          )}
                        </div>
                        {u.topics.length > 0 && (
                          <div className="mt-1 text-xs text-[var(--muted-foreground)]">
                            {u.topics.slice(0, 2).map((t) => t.name).join(" · ")}
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                  <div
                    className={
                      isFetching
                        ? "hidden opacity-60 md:block"
                        : "hidden md:block"
                    }
                  >
                    <Table>
                      <caption className="sr-only">
                        Organisational unit search results
                      </caption>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Name</TableHead>
                          {level === "group" && <TableHead>Faculty</TableHead>}
                          <TableHead className="text-right">Authors</TableHead>
                          <TableHead className="text-right">Works</TableHead>
                          <TableHead className="text-right">
                            Deal-covered
                          </TableHead>
                          <TableHead className="text-right">APC</TableHead>
                          <TableHead>Topics</TableHead>
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
                                <span
                                  className="block max-w-56 truncate"
                                  title={u.name}
                                >
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
                                    <span className="text-[var(--muted-foreground)]">
                                      —
                                    </span>
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
                            <TableCell className="whitespace-nowrap text-right tabular-nums">
                              {u.apc_n > 0 ? (
                                <span
                                  title={`APC paid for ${u.apc_n} ${
                                    u.apc_n === 1 ? "article" : "articles"
                                  }`}
                                >
                                  {formatEur(u.apc_euro_total)} €{" "}
                                  <span className="text-[var(--muted-foreground)]">
                                    ({u.apc_n})
                                  </span>
                                </span>
                              ) : (
                                <span className="text-[var(--muted-foreground)]">
                                  —
                                </span>
                              )}
                            </TableCell>
                            <TableCell>
                              {u.topics.length > 0 ? (
                                <span
                                  className="block max-w-40 truncate"
                                  title={u.topics
                                    .slice(0, 2)
                                    .map(
                                      (t) => `${t.name} (${Math.round(t.n)})`,
                                    )
                                    .join(" · ")}
                                >
                                  {u.topics.slice(0, 2).map((t) => t.name).join(" · ")}
                                </span>
                              ) : (
                                <span className="text-[var(--muted-foreground)]">
                                  —
                                </span>
                              )}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                  <p className="mt-4 text-xs text-[var(--muted-foreground)]">
                    Showing {rows.length.toLocaleString("en")} of{" "}
                    {(data?.total ?? 0).toLocaleString("en")}
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
