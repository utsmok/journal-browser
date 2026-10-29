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
import { OaCompositionBar } from "@/components/oa-composition";
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
import { useSiteMeta } from "@/hooks/use-site-meta";
import {
  encodeNamePath,
  errorMessage,
  type PublisherListItem,
  type PublisherSearchSort,
} from "@/lib/api";
import { formatEur } from "@/lib/format";

const SEARCH_INPUT_ID = "publisher-search";

const PAGE_SIZES = [25, 50, 100];

const OA_TYPE_LABELS: Record<string, string> = {
  gold: "Gold OA",
  diamond: "Diamond OA",
  generic: "OA (model unknown)",
  hybrid: "Hybrid",
  subscription: "Subscription (closed)",
};

const DEAL_LABELS: Record<string, string> = {
  covered: "Has deal",
  none: "No deal",
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
  label?: (value: string) => string,
): FacetValue[] {
  const list: FacetValue[] = Object.entries(counts ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([value, count]) => ({ value, count, label: label?.(value) }));
  for (const value of active)
    if (!list.some((v) => v.value === value))
      list.unshift({ value, label: label?.(value) });
  return list;
}

/** Compact Q1–Q4 chips with counts; a quartile with no journals dims out. */
function QuartileChips({ item }: { item: PublisherListItem }) {
  return (
    <span className="flex flex-wrap gap-1 text-[11px] tabular-nums">
      {(["q1", "q2", "q3", "q4"] as const).map((q) => {
        const n = item.quartiles[q] ?? 0;
        return (
          <span
            key={q}
            title={
              n
                ? `${q.toUpperCase()}: ${n} ${n === 1 ? "journal" : "journals"}`
                : `No ${q.toUpperCase()} journals`
            }
            className={
              n
                ? "rounded bg-[var(--secondary)] px-1 py-0.5"
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
  const { n_journals, eur_min: min, eur_max: max } = item.apc;
  if (n_journals === 0 || (min == null && max == null))
    return <span className="text-[var(--muted-foreground)]">—</span>;
  const range =
    min != null && max != null && min !== max
      ? `${formatEur(min)}–${formatEur(max)}`
      : formatEur(max ?? (min as number));
  return (
    <span
      className="tabular-nums"
      title={`APC known for ${n_journals} ${n_journals === 1 ? "journal" : "journals"}; list prices and OpenAPC ranges combined`}
    >
      {range} €{" "}
      <span className="text-[var(--muted-foreground)]">({n_journals})</span>
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
  const inst = useInstitution();
  const site = useSiteMeta();
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const q = sp.get("q") ?? "";
  const [input, setInput] = React.useState(q);

  const oaTypes = paramValues(sp, "oa_type");
  const dealParam = sp.get("deal");
  const deal: "covered" | "none" | null =
    dealParam === "covered" || dealParam === "none" ? dealParam : null;
  const quartiles = paramValues(sp, "quartile");
  const sizes = paramValues(sp, "size");
  const topic = sp.get("topic") ?? "";
  const apcParam = sp.get("has_apc");
  const hasApc: "yes" | "no" | null =
    apcParam === "yes" || apcParam === "no" ? apcParam : null;
  const anyFilter =
    oaTypes.length > 0 ||
    deal !== null ||
    quartiles.length > 0 ||
    sizes.length > 0 ||
    topic !== "" ||
    hasApc !== null;

  // The backend default is relevance-with-q, else works desc.
  const sortParam = sp.get("sort");
  const sort: PublisherSearchSort | undefined = [
    "relevance",
    "name",
    "journals",
    "works",
    "deals",
    "apc",
  ].includes(sortParam ?? "")
    ? (sortParam as PublisherSearchSort)
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

  const { data, isPending, isFetching, isError, error, refetch } = usePublishers(
    {
      q: q || undefined,
      oa_type: oaTypes.length > 0 ? oaTypes : undefined,
      deal: deal ?? undefined,
      quartile: quartiles.length > 0 ? quartiles : undefined,
      size: sizes.length > 0 ? sizes : undefined,
      topic: topic || undefined,
      has_apc: hasApc === null ? undefined : hasApc === "yes",
      sort,
      offset: offset > 0 ? offset : undefined,
      limit: pageSize === 50 ? undefined : pageSize,
      include_facets: true,
    },
  );

  const rows = data?.items ?? [];
  const facets = data?.facets;

  // Pager math; total is the unpaginated filtered count.
  const total = data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.min(Math.floor(offset / pageSize) + 1, pageCount);
  const showPager = total > pageSize;

  const toggleFacet = (key: string, value: string) => {
    if (key === "oa_type" || key === "quartile" || key === "size") {
      const current =
        key === "oa_type" ? oaTypes : key === "quartile" ? quartiles : sizes;
      const next = current.includes(value)
        ? current.filter((v) => v !== value)
        : [...current, value];
      setParams({ [key]: next.join("|") || undefined });
      return;
    }
    if (key === "deal") {
      setParams({ deal: deal === value ? undefined : value });
      return;
    }
    if (key === "topic") {
      setParams({ topic: topic === value ? undefined : value });
      return;
    }
    if (key === "has_apc") {
      setParams({ has_apc: hasApc === value ? undefined : value });
    }
  };

  const clearFilters = () =>
    setParams({
      oa_type: undefined,
      deal: undefined,
      quartile: undefined,
      size: undefined,
      topic: undefined,
      has_apc: undefined,
    });

  const groups: FacetGroupDef[] = [
    {
      key: "oa_type",
      label: "Open access",
      defaultOpen: true,
      values: facetValues(facets?.oa_type, oaTypes, (v) => OA_TYPE_LABELS[v] ?? v),
      activeValues: oaTypes,
    },
    {
      key: "deal",
      label: "Open access deal",
      defaultOpen: true,
      values: facetValues(facets?.deal, deal ? [deal] : [], (v) => DEAL_LABELS[v] ?? v),
      activeValues: deal ? [deal] : [],
    },
    {
      key: "quartile",
      label: "Quartile",
      defaultOpen: true,
      values: facetValues(facets?.quartile, quartiles),
      activeValues: quartiles,
    },
    {
      key: "has_apc",
      label: "APC price",
      defaultOpen: true,
      values: facetValues(facets?.has_apc, hasApc ? [hasApc] : [], (v) =>
        v === "yes" ? "Has price info" : "No price info",
      ),
      activeValues: hasApc ? [hasApc] : [],
    },
    {
      key: "size",
      label: "Journal count",
      defaultOpen: false,
      values: facetValues(facets?.size, sizes),
      activeValues: sizes,
    },
    {
      key: "topic",
      label: "Topic",
      defaultOpen: false,
      values: facetValues(facets?.topic, topic ? [topic] : []),
      activeValues: topic ? [topic] : [],
    },
  ].filter((group) => group.values.length > 0);

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <div className="flex flex-col min-[960px]:grid min-[960px]:grid-cols-[15rem_minmax(0,1fr)] min-[960px]:items-start min-[960px]:gap-6 min-[1280px]:grid-cols-[18rem_minmax(0,1fr)] min-[1280px]:gap-8">
        <section className="order-1 mb-8 min-[960px]:col-start-2 min-[960px]:row-start-1 min-[960px]:mb-6">
          <h1 className="mb-3 text-3xl font-bold text-balance">Publishers</h1>
          <p className="mb-6 max-w-2xl text-[var(--muted-foreground)]">
            Browse the journals of {site.name} by publisher, with their output,
            open access mix, deals, and article costs.
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
                placeholder="Search by publisher name"
                aria-label="Search publishers"
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
            <label htmlFor="publisher-sort" className="whitespace-nowrap">
              Sort by
            </label>
            <select
              id="publisher-sort"
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
                  ["journals", "Journals (high→low)"],
                  ["works", "Works (high→low)"],
                  ["deals", "Deal-covered journals (high→low)"],
                  ["apc", "APC (high→low)"],
                ] as [PublisherSearchSort, string][]
              ).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            <label htmlFor="publisher-per-page" className="whitespace-nowrap">
              Per page
            </label>
            <select
              id="publisher-per-page"
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
                      ? `${data.total.toLocaleString("en")} publisher${data.total === 1 ? "" : "s"}${q ? ` matching “${q}”` : ""}`
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
                <div className="space-y-2 py-4">
                  {Array.from({ length: 8 }).map((_, i) => (
                    <div
                      key={i}
                      className="h-9 animate-pulse rounded bg-[var(--muted)]"
                    />
                  ))}
                </div>
              ) : rows.length === 0 ? (
                <div className="py-10 text-center text-[var(--muted-foreground)]">
                  {q && !anyFilter ? (
                    <>No publishers match &ldquo;{q}&rdquo;.</>
                  ) : (
                    <>
                      No publishers match{anyFilter ? " these filters" : ""}.
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
                  {/* Stacked cards on narrow viewports: eight columns would
                    push the counts off-screen behind horizontal scrolling. */}
                  <ul
                    className={
                      isFetching ? "opacity-60 md:hidden" : "md:hidden"
                    }
                    aria-label="Publisher results"
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
                          {p.name}
                        </Link>
                        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs tabular-nums text-[var(--muted-foreground)]">
                          <span>
                            {p.n_journals.toLocaleString("en")}{" "}
                            {p.n_journals === 1 ? "journal" : "journals"}
                          </span>
                          <span>
                            {p.n_works.toLocaleString("en")}{" "}
                            {p.n_works === 1 ? "work" : "works"}
                          </span>
                          {p.deal_journals > 0 && (
                            <span>
                              {p.deal_journals} deal-covered
                            </span>
                          )}
                        </div>
                        <div className="mt-1.5 max-w-48">
                          <OaCompositionBar
                            counts={p.oa_types}
                            total={p.n_journals}
                          />
                        </div>
                        {p.topics.length > 0 && (
                          <div className="mt-1 text-xs text-[var(--muted-foreground)]">
                            {p.topics
                              .slice(0, 2)
                              .map((t) => t.name)
                              .join(" · ")}
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
                        Publisher search results
                      </caption>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Publisher</TableHead>
                          <TableHead className="text-right">Journals</TableHead>
                          <TableHead className="text-right">Works</TableHead>
                          <TableHead>OA composition</TableHead>
                          <TableHead className="text-right">Deals</TableHead>
                          <TableHead>Quartiles</TableHead>
                          <TableHead>APC</TableHead>
                          <TableHead>Topics</TableHead>
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
                                  title={p.name}
                                >
                                  {p.name}
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
                                <OaCompositionBar
                                  counts={p.oa_types}
                                  total={p.n_journals}
                                />
                              </div>
                            </TableCell>
                            <TableCell className="whitespace-nowrap text-right tabular-nums">
                              {p.deal_journals}
                              <span className="text-[var(--muted-foreground)]">
                                {" "}
                                of {p.n_journals}
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
                                    .map(
                                      (t) => `${t.name} (${Math.round(t.n)})`,
                                    )
                                    .join(" · ")}
                                >
                                  {p.topics.slice(0, 2).map((t) => t.name).join(" · ")}
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
