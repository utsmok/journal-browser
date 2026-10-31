"use client";

import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { CollapsibleCard } from "@/components/collapsible-card";
import { FacetGroupList, type FacetGroupDef, type FacetValue } from "@/components/filter-panel";
import { OrcidLink } from "@/components/orcid-link";
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
import { useSiteMeta } from "@/hooks/use-site-meta";
import {
  errorMessage,
  fetchAuthors,
  type AuthorFacetBucket,
  type AuthorSearchFilters,
  type AuthorSearchSort,
} from "@/lib/api";

const SEARCH_INPUT_ID = "author-search";

const SORTS: { value: AuthorSearchSort; label: string }[] = [
  { value: "works_desc", label: "Publications (high→low)" },
  { value: "name_asc", label: "Name (A→Z)" },
  { value: "name_desc", label: "Name (Z→A)" },
  { value: "last_pub_desc", label: "Last publication (new→old)" },
];

const PAGE_SIZES = [25, 50, 100];

/** Matches the journal page's sort-select styling. */
const SELECT_CLASS =
  "h-9 rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2";

const WORKS_LABELS: Record<string, string> = {
  "1-4": "1–4 works",
  "5-19": "5–19 works",
  "20-49": "20–49 works",
  "50+": "50+ works",
};

const LAST_PUB_LABELS: Record<string, string> = {
  "2025-2026": "2025–2026",
  "2022-2024": "2022–2024",
  "2020-2021": "2020–2021",
  none: "Nothing since 2020",
};

/** Comma-joined multi-select param → list of values (journal-search convention). */
function paramValues(sp: { get(key: string): string | null }, key: string): string[] {
  return (sp.get(key) ?? "").split("|").filter(Boolean);
}

/** Top 8 buckets, with every active value kept visible even outside the top 8. */
function topBuckets(buckets: AuthorFacetBucket[] | undefined, active: string[]): FacetValue[] {
  const list: FacetValue[] = (buckets ?? [])
    .slice(0, 8)
    .map((b) => ({ value: b.value, count: b.count }));
  for (const value of active) if (!list.some((b) => b.value === value)) list.unshift({ value });
  return list;
}

export default function AuthorSearchPage() {
  // useSearchParams needs a Suspense boundary during prerender.
  return (
    <React.Suspense fallback={null}>
      <AuthorsView />
    </React.Suspense>
  );
}

function AuthorsView() {
  const inst = useInstitution();
  const site = useSiteMeta();
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const q = sp.get("q") ?? "";
  const [input, setInput] = React.useState(q);

  // Facet selections mirror the journal search's URL style: comma-joined
  // values per multi-select param, plus one single-select yes/no group.
  const orcidParam = sp.get("has_orcid");
  const hasOrcid: "yes" | "no" | null =
    orcidParam === "yes" || orcidParam === "no" ? orcidParam : null;
  const selected = {
    faculty: paramValues(sp, "faculty"),
    org: paramValues(sp, "org"),
    works: paramValues(sp, "works"),
    last_pub: paramValues(sp, "last_pub"),
    topic: paramValues(sp, "topic"),
  };
  const anyFilter =
    hasOrcid !== null || Object.values(selected).some((values) => values.length > 0);

  // Sort and paging are URL state too; defaults stay out of the params.
  const sortParam = sp.get("sort");
  const sort: AuthorSearchSort = SORTS.some((s) => s.value === sortParam)
    ? (sortParam as AuthorSearchSort)
    : "works_desc";
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

  const filters: AuthorSearchFilters = {
    faculty: selected.faculty.length > 0 ? selected.faculty : undefined,
    org: selected.org.length > 0 ? selected.org : undefined,
    works: selected.works.length > 0 ? selected.works : undefined,
    last_pub: selected.last_pub.length > 0 ? selected.last_pub : undefined,
    topic: selected.topic.length > 0 ? selected.topic : undefined,
    has_orcid: hasOrcid ?? undefined,
  };

  const { data, isPending, isFetching, isError, error, refetch } = useQuery({
    queryKey: ["authors", inst, sp.toString()],
    queryFn: () =>
      fetchAuthors(inst, q || undefined, filters, {
        sort: sort === "works_desc" ? undefined : sort,
        offset: offset > 0 ? offset : undefined,
        limit: pageSize === 50 ? undefined : pageSize,
      }),
    placeholderData: keepPreviousData,
  });

  const rows = data?.items ?? [];
  const disabled = data != null && !data.enabled;
  const facets = data?.facets;

  // Pager math; total is the unpaginated filtered count.
  const total = data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.min(Math.floor(offset / pageSize) + 1, pageCount);
  const showPager = total > pageSize;

  const toggleFacet = (key: string, value: string) => {
    if (key === "has_orcid") {
      setParams({ has_orcid: hasOrcid === value ? undefined : value });
      return;
    }
    const current = selected[key as keyof typeof selected];
    const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value];
    setParams({ [key]: next.join("|") || undefined });
  };

  const clearFilters = () =>
    setParams({
      faculty: undefined,
      org: undefined,
      works: undefined,
      last_pub: undefined,
      topic: undefined,
      has_orcid: undefined,
    });

  const groups: FacetGroupDef[] = [
    {
      key: "faculty",
      label: "Faculty",
      defaultOpen: true,
      values: topBuckets(facets?.faculty, selected.faculty),
      activeValues: selected.faculty,
    },
    {
      key: "org",
      label: "Research group",
      defaultOpen: true,
      values: topBuckets(facets?.org, selected.org),
      activeValues: selected.org,
    },
    {
      key: "works",
      label: "Publications",
      defaultOpen: true,
      values: (facets?.works ?? []).map((b) => ({
        value: b.value,
        count: b.count,
        label: WORKS_LABELS[b.value] ?? b.value,
      })),
      activeValues: selected.works,
    },
    {
      key: "last_pub",
      label: "Last publication",
      defaultOpen: true,
      values: (facets?.last_pub ?? []).map((b) => ({
        value: b.value,
        count: b.count,
        label: LAST_PUB_LABELS[b.value] ?? b.value,
      })),
      activeValues: selected.last_pub,
    },
    {
      key: "topic",
      label: "Topic",
      defaultOpen: false,
      values: topBuckets(facets?.topic, selected.topic),
      activeValues: selected.topic,
    },
    {
      key: "has_orcid",
      label: "ORCID",
      defaultOpen: true,
      values: [
        { value: "yes", label: "Has ORCID" },
        { value: "no", label: "No ORCID" },
      ],
      activeValues: hasOrcid ? [hasOrcid] : [],
    },
  ].filter((group) => group.values.length > 0);

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <div className="flex flex-col min-[960px]:grid min-[960px]:grid-cols-[15rem_minmax(0,1fr)] min-[960px]:items-start min-[960px]:gap-6 min-[1280px]:grid-cols-[18rem_minmax(0,1fr)] min-[1280px]:gap-8">
        <section className="order-1 mb-8 min-[960px]:col-start-2 min-[960px]:row-start-1 min-[960px]:mb-6">
          <h1 className="mb-3 text-3xl font-bold text-balance">Authors</h1>
          <p className="mb-6 max-w-2xl text-[var(--muted-foreground)]">
            Search researchers at {site.name} to find experts, co-authors, or reviewers, and see
            where they publish.
          </p>
          {!disabled && (
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
                  placeholder="Search by author name"
                  aria-label="Search authors"
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
          )}
        </section>

        {/* Stacked filter card: the only filter UI below 960px. */}
        {!disabled && data != null && (
          <section className="order-2 mb-6 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 min-[960px]:hidden">
            <FacetGroupList groups={groups} onToggle={toggleFacet} variant="chips" />
          </section>
        )}

        {/* Wide-screen sidebar: sticky, scrolls on its own when long. */}
        {!disabled && data != null && (
          <aside className="sticky top-20 hidden max-h-[calc(100vh-6rem)] self-start overflow-y-auto rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 min-[960px]:col-start-1 min-[960px]:row-span-2 min-[960px]:row-start-1 min-[960px]:block">
            <FacetGroupList groups={groups} onToggle={toggleFacet} variant="rows" />
          </aside>
        )}

        <div className="order-3 min-w-0 min-[960px]:col-start-2 min-[960px]:row-start-2">
          {/* Sort, page size, and reset belong with the results they act on. */}
          {!disabled && (
            <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
              <label htmlFor="author-sort" className="whitespace-nowrap">
                Sort by
              </label>
              <select
                id="author-sort"
                title="Order of the results"
                value={sort}
                onChange={(event) =>
                  setParams({
                    sort: event.target.value === "works_desc" ? undefined : event.target.value,
                  })
                }
                className={SELECT_CLASS}
              >
                {SORTS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
              <label htmlFor="author-per-page" className="whitespace-nowrap">
                Per page
              </label>
              <select
                id="author-per-page"
                title="Results per page"
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
                  title="Clears all active filters"
                  onClick={clearFilters}
                >
                  Reset filters
                </Button>
              )}
            </div>
          )}
          {disabled ? (
            <CollapsibleCard
              id="authors-disabled"
              title="Author profiles"
              contentClassName="text-sm text-[var(--muted-foreground)]"
            >
              Author profiles are not available for this institution.
            </CollapsibleCard>
          ) : (
            <Card>
              <CardContent className="pt-6">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm text-[var(--muted-foreground)]">
                    {/* Announce only settled counts: while a fetch runs the live
                      region keeps its previous text, so typing never chatters. */}
                    <span aria-live="polite">
                      {data
                        ? `${data.total.toLocaleString("en")} author${data.total === 1 ? "" : "s"}${q ? ` matching “${q}”` : ""}`
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
                        Page {page.toLocaleString("en")} of {pageCount.toLocaleString("en")}
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
                    <p className="text-[var(--destructive)]">{errorMessage(error)}</p>
                    <Button variant="outline" size="sm" className="mt-3" onClick={() => refetch()}>
                      Retry
                    </Button>
                  </div>
                ) : isPending ? (
                  <ListSkeletonRows rows={8} />
                ) : rows.length === 0 ? (
                  <div className="py-10 text-center text-[var(--muted-foreground)]">
                    {q && !anyFilter ? (
                      <>No authors match &ldquo;{q}&rdquo;.</>
                    ) : (
                      <>
                        No authors match{anyFilter ? " these filters" : ""}.
                        {anyFilter && (
                          <div className="mt-3">
                            <Button variant="outline" size="sm" onClick={clearFilters}>
                              Clear filters
                            </Button>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                ) : (
                  <>
                    {/* Stacked cards on narrow viewports: seven columns would push
                      the works count off-screen behind horizontal scrolling. */}
                    <ul
                      className={isFetching ? "opacity-60 md:hidden" : "md:hidden"}
                      aria-label="Author results"
                    >
                      {rows.map((a) => (
                        <li
                          key={a.pure_uuid}
                          className="border-b border-[var(--border)] py-3 first:pt-0 last:border-0 last:pb-0"
                        >
                          <Link
                            href={`/${inst}/author/${a.pure_uuid}`}
                            className="font-medium text-[var(--foreground)] underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                          >
                            {a.name}
                          </Link>
                          <div className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                            {[a.faculty, a.research_group].filter(Boolean).join(" · ") || "—"}
                          </div>
                          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs tabular-nums text-[var(--muted-foreground)]">
                            <span>
                              {a.n_works.toLocaleString("en")} {a.n_works === 1 ? "work" : "works"}
                            </span>
                            {a.last_pub_year != null && <span>Last pub {a.last_pub_year}</span>}
                            {a.primary_topic && (
                              <span className="max-w-52 truncate" title={a.primary_topic}>
                                {a.primary_topic}
                              </span>
                            )}
                            {a.orcid && <OrcidLink orcid={a.orcid} />}
                          </div>
                        </li>
                      ))}
                    </ul>
                    <div className={isFetching ? "hidden opacity-60 md:block" : "hidden md:block"}>
                      <Table>
                        <caption className="sr-only">Author search results</caption>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Name</TableHead>
                            <TableHead>Faculty</TableHead>
                            <TableHead>Research group</TableHead>
                            <TableHead className="text-right">Works</TableHead>
                            <TableHead className="text-right">Last pub</TableHead>
                            <TableHead>Topic</TableHead>
                            <TableHead>ORCID</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {rows.map((a) => (
                            <TableRow key={a.pure_uuid}>
                              <TableCell className="font-medium">
                                <Link
                                  href={`/${inst}/author/${a.pure_uuid}`}
                                  className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                                >
                                  {a.name}
                                </Link>
                              </TableCell>
                              <TableCell>
                                <span
                                  className="block max-w-44 truncate"
                                  title={a.faculty ?? undefined}
                                >
                                  {a.faculty || (
                                    <span className="text-[var(--muted-foreground)]">—</span>
                                  )}
                                </span>
                              </TableCell>
                              <TableCell>
                                <span
                                  className="block max-w-44 truncate"
                                  title={a.research_group ?? undefined}
                                >
                                  {a.research_group || (
                                    <span className="text-[var(--muted-foreground)]">—</span>
                                  )}
                                </span>
                              </TableCell>
                              <TableCell className="text-right tabular-nums">
                                {a.n_works.toLocaleString("en")}
                              </TableCell>
                              <TableCell className="text-right tabular-nums">
                                {a.last_pub_year ?? (
                                  <span className="text-[var(--muted-foreground)]">—</span>
                                )}
                              </TableCell>
                              <TableCell>
                                {a.primary_topic ? (
                                  <span className="block max-w-40 truncate" title={a.primary_topic}>
                                    {a.primary_topic}
                                  </span>
                                ) : (
                                  <span className="text-[var(--muted-foreground)]">—</span>
                                )}
                              </TableCell>
                              <TableCell>
                                {a.orcid ? <OrcidLink orcid={a.orcid} /> : null}
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
          )}
        </div>
      </div>
    </div>
  );
}
