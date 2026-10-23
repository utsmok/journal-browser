"use client";

import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { DealBadge, OaTypeBadge, QuartileBadge } from "@/components/badges";
import { FilterPanel } from "@/components/filter-panel";
import { SourceNote } from "@/components/source-note";
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
import { useJournals } from "@/hooks/use-api";
import { errorMessage, type JournalListItem, type SearchIn, type SortKey } from "@/lib/api";

const SORTS: { value: SortKey; label: string }[] = [
  { value: "relevance", label: "Relevance" },
  { value: "title", label: "Title A–Z" },
  { value: "institution_works", label: "Twente works" },
  { value: "2yr_mean_citedness", label: "2-year mean citedness" },
];

const SEARCH_IN_OPTIONS: { value: SearchIn; label: string }[] = [
  { value: "all", label: "Everything" },
  { value: "title", label: "Title" },
  { value: "publisher", label: "Publisher" },
  { value: "topic", label: "Topic" },
];

const SEARCH_INPUT_ID = "journal-search";

/** Round an APC mean sensibly: nearest 10 euros at realistic price points. */
function formatApc(euro: number) {
  const rounded = Math.abs(euro) >= 100 ? Math.round(euro / 10) * 10 : Math.round(euro);
  return rounded.toLocaleString("en");
}

export default function HomePage() {
  // useSearchParams needs a Suspense boundary during prerender.
  return (
    <React.Suspense fallback={null}>
      <SearchView />
    </React.Suspense>
  );
}

function SearchView() {
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const spQ = sp.get("q") ?? "";
  // A browse-all with no query has nothing to rank, so Twente works is the
  // sensible default order.
  const sort = (sp.get("sort") ?? (spQ ? "relevance" : "institution_works")) as SortKey;
  const deal = sp.get("deal") ?? "";
  const oa = sp.get("oa");
  const doaj = sp.get("doaj");
  const quartile = sp.get("quartile") ?? "";
  const topic = sp.get("topic") ?? "";
  const publisher = sp.get("publisher") ?? "";
  const hasApc = sp.get("has_apc");
  const searchIn = (sp.get("search_in") ?? "all") as SearchIn;

  const [input, setInput] = React.useState(spQ);
  const [stack, setStack] = React.useState<string[]>([]);

  // Cursor is URL state (refresh/share keep your page). The visited-cursor
  // stack mirrors to sessionStorage so Prev survives a refresh in the same
  // tab; a fresh link simply starts over at that page.
  const cursor = sp.get("cursor") ?? undefined;

  // Reset keyset position whenever the filters change — not when the cursor
  // does, or paging would wipe its own history.
  const filtersKey = React.useMemo(() => {
    const withoutCursor = new URLSearchParams(sp.toString());
    withoutCursor.delete("cursor");
    withoutCursor.delete("p");
    return withoutCursor.toString();
  }, [sp]);
  const firstRun = React.useRef(true);
  React.useEffect(() => {
    if (firstRun.current) {
      firstRun.current = false;
      try {
        const saved = JSON.parse(sessionStorage.getItem("jb-cursor-stack") ?? "[]");
        if (Array.isArray(saved) && saved.length) {
          setStack(saved);
          return;
        }
      } catch {
        // corrupted storage: fall through to a fresh stack
      }
      if (cursor) setStack([cursor]);
      return;
    }
    setStack([]);
    sessionStorage.removeItem("jb-cursor-stack");
    // sp is read once per filter change; the cursor must not retrigger this.
  }, [filtersKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const update = React.useCallback(
    (patch: Record<string, string | undefined>) => {
      // Any filter change invalidates the current page: drop the cursor and
      // the stored stack synchronously so an in-flight fetch can never anchor
      // the new result set to an older page.
      setStack([]);
      sessionStorage.removeItem("jb-cursor-stack");
      const next = new URLSearchParams(sp.toString());
      next.delete("cursor");
      next.delete("p");
      for (const [key, value] of Object.entries(patch)) {
        if (!value) next.delete(key);
        else next.set(key, value);
      }
      router.replace(`${pathname}?${next}`, { scroll: false });
    },
    [pathname, router, sp],
  );

  // Page moves keep the stack; both cursor and page number live in the URL.
  const moveTo = (nextStack: string[], nextCursor: string | undefined) => {
    setStack(nextStack);
    sessionStorage.setItem("jb-cursor-stack", JSON.stringify(nextStack));
    const next = new URLSearchParams(sp.toString());
    if (nextCursor) next.set("cursor", nextCursor);
    else next.delete("cursor");
    // The stack excludes page 1, so the page number is length + 1.
    next.set("p", String(nextStack.length + 1));
    router.replace(`${pathname}?${next}`, { scroll: false });
  };

  // Live search with debounce; keep the input in sync with back/forward nav.
  React.useEffect(() => {
    setInput(spQ);
  }, [spQ]);
  React.useEffect(() => {
    const t = setTimeout(() => {
      if (input !== spQ) update({ q: input || undefined });
    }, 350);
    return () => clearTimeout(t);
  }, [input, spQ, update]);

  // "/" focuses search from anywhere outside a form field; Escape blurs it.
  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        event.key === "Escape" &&
        target?.id === SEARCH_INPUT_ID
      ) {
        target.blur();
        return;
      }
      if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey)
        return;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable)
      )
        return;
      event.preventDefault();
      document.getElementById(SEARCH_INPUT_ID)?.focus();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const query = {
    q: spQ || undefined,
    search_in: searchIn === "all" ? undefined : searchIn,
    deal: (deal || undefined) as "covered" | "not_covered" | undefined,
    oa: oa === null ? undefined : oa === "true",
    doaj: doaj === null ? undefined : doaj === "true",
    quartile: quartile || undefined,
    publisher: publisher || undefined,
    has_apc: hasApc === null ? undefined : hasApc === "true",
    topic: topic || undefined,
    sort,
    cursor,
    limit: 20,
  };
  const { data, isPending, isFetching, isError, error, refetch } =
    useJournals(query);

  const facets = data?.facets ?? {};

  const filterSelection = {
    deal,
    oa,
    doaj,
    quartile,
    topic,
    publisher,
    hasApc,
  };

  // Single-select per group: clicking the active value clears it.
  const toggleFilter = (key: string, value: string) =>
    update({ [key]: sp.get(key) === value ? undefined : value });

  const columns = React.useMemo<ColumnDef<JournalListItem>[]>(
    () => [
      {
        accessorKey: "title",
        header: "Journal",
        cell: (info) => {
          const row = info.row.original;
          return (
            <div className="max-w-md">
              <Link
                href={`/journals/${row.issn_l}`}
                className="font-medium text-[var(--foreground)] underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
              >
                {row.title ?? row.issn_l}
              </Link>
              <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-[var(--muted-foreground)]">
                <span>{row.publisher_name ?? "Unknown publisher"}</span>
                {row.apc_euro_mean != null && (
                  <span title="Average article processing charge reported by OpenAPC">
                    APC ≈ €{formatApc(row.apc_euro_mean)}
                    {row.apc_period ? ` (${row.apc_period}, OpenAPC)` : " (OpenAPC)"}
                  </span>
                )}
              </div>
            </div>
          );
        },
      },
      {
        accessorKey: "deal_covered",
        header: "Deal",
        cell: (info) => <DealBadge covered={info.getValue<boolean>()} />,
      },
      {
        accessorKey: "is_oa",
        header: "OA",
        cell: (info) => {
          const row = info.row.original;
          return <OaTypeBadge oaType={row.oa_type} isOa={row.is_oa} />;
        },
      },
      {
        accessorKey: "twente_works",
        header: () => (
          <span title="University of Twente publications in this journal, 2020 onwards">
            Twente works
          </span>
        ),
        cell: (info) => (
          <span className="tabular-nums">{info.getValue<number>()}</span>
        ),
      },
      {
        accessorKey: "quartile",
        header: "Quartile",
        cell: (info) => (
          <QuartileBadge quartile={info.getValue<string | null>()} />
        ),
      },
      {
        accessorKey: "twoyr_mean_citedness",
        header: () => (
          <span title="2-year mean citedness (OpenAlex)">2-yr citedness</span>
        ),
        cell: (info) => {
          const v = info.getValue<number | null>();
          return v === null ? (
            <span className="text-[var(--muted-foreground)]">—</span>
          ) : (
            <span
              className="tabular-nums"
              title="2-year mean citedness (OpenAlex)"
            >
              {v.toFixed(1)}
            </span>
          );
        },
      },
    ],
    [],
  );

  // Backend fields the generated types trail (see lib/api.ts).
  const rows = (data?.items ?? []) as JournalListItem[];
  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  const pParam = parseInt(sp.get("p") ?? "", 10);
  const page =
    Number.isFinite(pParam) && pParam > 0 ? pParam : stack.length + 1;
  const pageStart = (page - 1) * (query.limit ?? 20) + 1;
  const hasFilters = Boolean(
    spQ ||
      deal ||
      oa !== null ||
      doaj !== null ||
      quartile ||
      topic ||
      publisher ||
      hasApc !== null,
  );
  const hasNonQueryFilters = Boolean(
    deal ||
      oa !== null ||
      doaj !== null ||
      quartile ||
      topic ||
      publisher ||
      hasApc !== null,
  );
  const clearFilters = () =>
    update({
      q: undefined,
      search_in: undefined,
      deal: undefined,
      oa: undefined,
      doaj: undefined,
      quartile: undefined,
      topic: undefined,
      publisher: undefined,
      has_apc: undefined,
    });

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <section className="mb-8">
        <h1 className="mb-3 text-3xl font-bold">
          Find the best home for your next article
        </h1>
        <p className="mb-6 max-w-2xl text-[var(--muted-foreground)]">
          Search journals to see whether they are covered by an open access
          deal, what publishing there costs, and how the University of Twente
          publishes in them.
        </p>
        <form
          className="flex max-w-xl gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            update({ q: input || undefined });
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
              placeholder="Search by journal title or ISSN"
              aria-label="Search journals"
              className="pr-8"
            />
            {input === "" && (
              <kbd
                aria-hidden
                className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 rounded border border-[var(--border)] bg-[var(--muted)] px-1.5 py-0.5 text-[11px] text-[var(--muted-foreground)]"
              >
                /
              </kbd>
            )}
          </div>
          <select
            aria-label="Search scope"
            value={searchIn}
            onChange={(event) => update({ search_in: event.target.value })}
            className="h-10 rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-2 text-sm"
          >
            {SEARCH_IN_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <Button type="submit">
            <Search aria-hidden className="size-4" /> Search
          </Button>
        </form>
      </section>

      {/* Sidebar from ~960px up (user-set cutoff); narrower sidebar column
          between 960 and 1280 so the results keep enough width. */}
      <div className="min-[960px]:grid min-[960px]:grid-cols-[15rem_minmax(0,1fr)] min-[960px]:items-start min-[960px]:gap-6 min-[1280px]:grid-cols-[18rem_minmax(0,1fr)] min-[1280px]:gap-8">
        {/* Stacked filter card: the only filter UI below 960px. */}
        <section className="mb-6 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 min-[960px]:hidden">
          <FilterPanel
            facets={facets}
            selection={filterSelection}
            onToggle={toggleFilter}
            variant="chips"
          />
        </section>

        {/* Wide-screen sidebar: sticky, scrolls on its own when long. */}
        <aside className="sticky top-20 hidden max-h-[calc(100vh-6rem)] self-start overflow-y-auto rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 min-[960px]:block">
          <FilterPanel
            facets={facets}
            selection={filterSelection}
            onToggle={toggleFilter}
            variant="rows"
          />
        </aside>

        <div className="min-w-0">
          {/* Sort and reset belong with the results they act on. */}
          <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
            <label htmlFor="sort" className="whitespace-nowrap">Sort by</label>
            <select
              id="sort"
              value={sort}
              onChange={(event) => update({ sort: event.target.value })}
              className="h-9 rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-2"
            >
              {SORTS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
            {hasFilters && (
              <Button
                variant="ghost"
                size="sm"
                className="text-[var(--muted-foreground)]"
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
                {data ? `${data.total.toLocaleString("en")} journals` : ""}
              </span>
              {isFetching && data ? " · updating…" : ""}
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={stack.length === 0}
                onClick={() => {
                  const next = stack.slice(0, -1);
                  moveTo(next, next[next.length - 1]);
                }}
              >
                <ChevronLeft aria-hidden className="size-4" /> Prev
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={!data?.next_cursor}
                onClick={() => {
                  if (!data?.next_cursor) return;
                  moveTo([...stack, data.next_cursor], data.next_cursor);
                }}
              >
                Next <ChevronRight aria-hidden className="size-4" />
              </Button>
            </div>
          </div>

          {isError ? (
            <div className="py-10 text-center">
              <p className="text-[var(--destructive)]">{errorMessage(error)}</p>
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
              {spQ && !hasNonQueryFilters ? (
                <>
                  No journals match &ldquo;{spQ}&rdquo;.
                </>
              ) : (
                <>No journals match{hasFilters ? " these filters" : ""}.</>
              )}
              {hasFilters && (
                <div className="mt-3">
                  <Button variant="outline" size="sm" onClick={clearFilters}>
                    Clear filters
                  </Button>
                </div>
              )}
            </div>
          ) : (
            <>
              {/* Stacked cards on narrow viewports: the six-column table would
                  push the decision columns off-screen behind horizontal
                  scrolling. */}
              <ul
                className={
                  isFetching ? "opacity-60 md:hidden" : "md:hidden"
                }
                aria-label="Journal results"
              >
                {rows.map((row) => (
                  <li
                    key={row.issn_l}
                    className="border-b border-[var(--border)] py-3 first:pt-0 last:border-0 last:pb-0"
                  >
                    <Link
                      href={`/journals/${row.issn_l}`}
                      className="font-medium text-[var(--foreground)] underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                    >
                      {row.title ?? row.issn_l}
                    </Link>
                    <div className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                      {row.publisher_name ?? "Unknown publisher"}
                      {row.apc_euro_mean != null &&
                        ` · APC ≈ €${formatApc(row.apc_euro_mean)}`}
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                      <DealBadge covered={row.deal_covered} />
                      <OaTypeBadge oaType={row.oa_type} isOa={row.is_oa} />
                      <QuartileBadge quartile={row.quartile ?? null} />
                    </div>
                    <div className="mt-1 text-xs tabular-nums text-[var(--muted-foreground)]">
                      {row.twente_works.toLocaleString("en")} Twente works
                      {row.twoyr_mean_citedness != null &&
                        ` · ${row.twoyr_mean_citedness.toFixed(1)} citedness`}
                    </div>
                  </li>
                ))}
              </ul>
              <div className={isFetching ? "hidden opacity-60 md:block" : "hidden md:block"}>
                <Table>
                  <caption className="sr-only">Journal search results</caption>
                  <TableHeader>
                    {table.getHeaderGroups().map((group) => (
                      <TableRow key={group.id}>
                        {group.headers.map((header) => (
                          <TableHead key={header.id}>
                            {flexRender(
                              header.column.columnDef.header,
                              header.getContext(),
                            )}
                          </TableHead>
                        ))}
                      </TableRow>
                    ))}
                  </TableHeader>
                  <TableBody>
                    {table.getRowModel().rows.map((row) => (
                      <TableRow key={row.id}>
                        {row.getVisibleCells().map((cell) => (
                          <TableCell key={cell.id}>
                            {flexRender(
                              cell.column.columnDef.cell,
                              cell.getContext(),
                            )}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </>
          )}

          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-xs text-[var(--muted-foreground)]">
            {/* Only render a range while real rows exist; "0–-1 of 0" is noise. */}
            <span>
              {data && rows.length > 0
                ? `Showing ${pageStart}–${pageStart + rows.length - 1} of ${data.total.toLocaleString("en")}`
                : ""}
            </span>
            <SourceNote
              source="OpenAlex · Scimago · JCT · openaccess.nl"
              url="https://openalex.org"
              codes={[
                "window-2020",
                "openalex-coverage",
                "institution-affiliation",
                "jct-coverage",
                "issn-mapping",
              ]}
            />
          </div>
        </CardContent>
      </Card>
        </div>
      </div>
    </div>
  );
}
