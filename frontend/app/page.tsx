"use client";

import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import {
  ArrowDown,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  ChevronsUpDown,
  Search,
} from "lucide-react";
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
import { useSiteMeta } from "@/hooks/use-site-meta";
import { useFacets, useJournals } from "@/hooks/use-api";
import { errorMessage, type JournalListItem, type SearchIn, type SortKey } from "@/lib/api";

const SORTS: { value: SortKey; label: string }[] = [
  { value: "relevance", label: "Relevance" },
  { value: "title", label: "Title A–Z" },
  { value: "publisher", label: "Publisher A–Z" },
  { value: "institution_works", label: "Twente works" },
  { value: "quartile", label: "Quartile" },
  { value: "topic", label: "Topic A–Z" },
  { value: "apc", label: "APC (high–low)" },
];

// Sortable columns: backend key + natural direction. The header button
// cycles natural → reversed → off (back to the mode's default sort).
const COLUMN_SORTS: Record<string, { key: SortKey; natural: "asc" | "desc" }> = {
  title: { key: "title", natural: "asc" },
  publisher: { key: "publisher", natural: "asc" },
  twente_works: { key: "institution_works", natural: "desc" },
  quartile: { key: "quartile", natural: "asc" },
  apc: { key: "apc", natural: "desc" },
  topic: { key: "topic", natural: "asc" },
};

function SortHead({
  columnId,
  label,
  state,
  title,
}: {
  columnId: string;
  label: string;
  state: {
    sort: SortKey;
    dir: "asc" | "desc" | null;
    cycleSort: (columnId: string) => void;
    disabled?: boolean;
  };
  title?: string;
}) {
  // Semantic ranking ignores sort params, so the buttons would lie.
  if (state.disabled)
    return <span className="inline-flex items-center gap-1 opacity-60">{label}</span>;
  const spec = COLUMN_SORTS[columnId];
  const active = !!spec && state.sort === spec.key;
  const current = active ? (state.dir ?? spec!.natural) : null;
  const atNatural = active && current === spec!.natural;
  const Icon = !active ? ChevronsUpDown : current === "asc" ? ArrowUp : ArrowDown;
  return (
    <button
      type="button"
      onClick={() => state.cycleSort(columnId)}
      title={
        title ??
        (active
          ? `Sorted ${current === "asc" ? "A–Z, low–high" : "Z–A, high–low"}; click to ${atNatural ? "reverse" : "reset"}`
          : `Sort by ${label}`)
      }
      className="inline-flex items-center gap-1 hover:text-[var(--foreground)]"
    >
      {label}
      <Icon
        aria-hidden
        className={`size-3 ${active ? "text-[var(--primary-text)]" : "opacity-50"}`}
      />
    </button>
  );
}

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
  const site = useSiteMeta();

  const spQ = sp.get("q") ?? "";
  // A browse-all with no query has nothing to rank, so Twente works is the
  // sensible default order.
  const sort = (sp.get("sort") ?? (spQ ? "relevance" : "institution_works")) as SortKey;
  const dirParam = sp.get("dir");
  const dir: "asc" | "desc" | null =
    dirParam === "asc" || dirParam === "desc" ? dirParam : null;
  const deal = sp.get("deal") ?? "";
  const oa = sp.get("oa");
  const doaj = sp.get("doaj");
  const quartile = sp.get("quartile") ?? "";
  const topic = sp.get("topic") ?? "";
  const publisher = sp.get("publisher") ?? "";
  const hasApc = sp.get("has_apc");
  const hasUtWorks = sp.get("has_ut_works");
  const searchIn = (sp.get("search_in") ?? "all") as SearchIn;
  // oa_type is the one multi-select facet: comma-joined in the URL, OR'd
  // server-side.
  const oaTypes = (sp.get("oa_type") ?? "").split(",").filter(Boolean);
  // mode=semantic: rank by embedding similarity instead of FTS. Filters and
  // sort do not apply to the vector ranking, so their UI is hidden. Needs a
  // real query: the UI follows the toggle so it never lies about the active
  // mode, while shorter input just falls back to a normal browse.
  const semanticMode = sp.get("mode") === "semantic";
  const semantic = semanticMode && spQ.trim().length >= 2;

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
    has_ut_works: hasUtWorks === null ? undefined : hasUtWorks === "true",
    topic: topic || undefined,
    oa_type: oaTypes.join(",") || undefined,
    sort,
    dir: dir ?? undefined,
    cursor,
    limit: 40,
    include_facets: false,
  };
  const { data, isPending, isFetching, isError, error, refetch } =
    useJournals(query, semantic);
  const facetsQuery = useFacets(query, { enabled: !semantic });

  const facets = facetsQuery.data?.facets ?? {};

  const filterSelection = {
    deal,
    oa,
    doaj,
    quartile,
    topic,
    publisher,
    hasApc,
    hasUtWorks,
    oaTypes,
  };

  // Single-select per group: clicking the active value clears it.
  const toggleFilter = (key: string, value: string) =>
    update({ [key]: sp.get(key) === value ? undefined : value });

  // The oa_type group ORs values: toggle membership instead of clearing.
  const toggleOaType = (value: string) => {
    const next = oaTypes.includes(value)
      ? oaTypes.filter((v) => v !== value)
      : [...oaTypes, value];
    update({ oa_type: next.join(",") || undefined });
  };
  const handleFacetToggle = (key: string, value: string) =>
    key === "oa_type" ? toggleOaType(value) : toggleFilter(key, value);

  // Tri-state column sort: natural → reversed → off. Off removes both
  // params so the mode default applies (relevance with a query, Twente
  // works for browse-all).
  const cycleSort = (columnId: string) => {
    const spec = COLUMN_SORTS[columnId];
    if (!spec) return;
    if (sort !== spec.key) {
      update({ sort: spec.key, dir: spec.natural });
      return;
    }
    const atNatural = (dir ?? spec.natural) === spec.natural;
    update(
      atNatural
        ? { sort: spec.key, dir: spec.natural === "asc" ? "desc" : "asc" }
        : { sort: undefined, dir: undefined },
    );
  };

  // Headers render through memoized column defs; the ref keeps their
  // closures reading the current sort state without re-creating the defs.
  const sortRef = React.useRef({ sort, dir, cycleSort, disabled: semanticMode });
  sortRef.current = { sort, dir, cycleSort, disabled: semanticMode };

  const columns = React.useMemo<ColumnDef<JournalListItem>[]>(
    () => [
      {
        accessorKey: "title",
        meta: { columnId: "title" },
        header: () => (
          <SortHead
            columnId="title"
            label="Journal"
            state={sortRef.current}
          />
        ),
        cell: (info) => (
          <div className="max-w-md">
            <Link
              href={`/journals/${info.row.original.issn_l}`}
              className="font-medium text-[var(--foreground)] underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
            >
              {info.row.original.title ?? info.row.original.issn_l}
            </Link>
          </div>
        ),
      },
      {
        accessorKey: "publisher_name",
        meta: { columnId: "publisher" },
        header: () => (
          <SortHead
            columnId="publisher"
            label="Publisher"
            state={sortRef.current}
          />
        ),
        cell: (info) => {
          const v = info.getValue<string | null>();
          return (
            <span className="block max-w-40 truncate" title={v ?? undefined}>
              {v ?? "—"}
            </span>
          );
        },
      },
      {
        accessorKey: "deal_covered",
        // Orderable via the facet, not the column; screen readers still get
        // a column name.
        header: () => <span className="sr-only">Deal coverage</span>,
        cell: (info) => <DealBadge covered={info.getValue<boolean>()} />,
      },
      {
        accessorKey: "is_oa",
        header: () => <span className="sr-only">Open access type</span>,
        cell: (info) => {
          const row = info.row.original;
          return <OaTypeBadge oaType={row.oa_type} isOa={row.is_oa} />;
        },
      },
      {
        accessorKey: "twente_works",
        meta: { columnId: "twente_works" },
        header: () => (
          <SortHead
            columnId="twente_works"
            label="Works"
            title={`${site.name} publications in this journal, 2020 onwards. Click to sort, again to reverse, again to reset`}
            state={sortRef.current}
          />
        ),
        cell: (info) => (
          <span className="tabular-nums">{info.getValue<number>()}</span>
        ),
      },
      {
        accessorKey: "quartile",
        meta: { columnId: "quartile" },
        header: () => (
          <SortHead
            columnId="quartile"
            label="Q"
            title="SCImago quartile. Click to sort, again to reverse, again to reset"
            state={sortRef.current}
          />
        ),
        cell: (info) => (
          <QuartileBadge quartile={info.getValue<string | null>()} />
        ),
      },
      {
        accessorKey: "apc_euro_latest",
        header: () => (
          <SortHead
            columnId="apc"
            label="APC"
            title="Latest APC reported to OpenAPC (highest single cost in the journal's newest reporting period). Click to sort, again to reverse, again to reset"
            state={sortRef.current}
          />
        ),
        cell: (info) => {
          const row = info.row.original;
          if (row.apc_euro_latest == null)
            return <span className="text-[var(--muted-foreground)]">—</span>;
          return (
            <span
              className="tabular-nums"
              title={`Latest APC reported to OpenAPC (period ${row.apc_period ?? "unknown"}; highest single cost)`}
            >
              €{formatApc(row.apc_euro_latest)}
            </span>
          );
        },
      },
      {
        accessorKey: "primary_topic",
        meta: { columnId: "topic" },
        header: () => (
          <SortHead
            columnId="topic"
            label="Topic"
            title="Primary OpenAlex topic of the journal's works. Click to sort, again to reverse, again to reset"
            state={sortRef.current}
          />
        ),
        cell: (info) => {
          const v = info.getValue<string | null>();
          return (
            <span className="block max-w-44 truncate" title={v ?? undefined}>
              {v || "—"}
            </span>
          );
        },
      },
    ],
    [site],
  );

  // Backend fields the generated types trail (see lib/api.ts).
  const rows = (data?.items ?? []) as JournalListItem[];
  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  // Screen readers learn the live sort order from the th, not the button.
  const ariaSortFor = (meta: unknown): "ascending" | "descending" | undefined => {
    const columnId = (meta as { columnId?: string } | undefined)?.columnId;
    const spec = columnId ? COLUMN_SORTS[columnId] : undefined;
    if (!spec || semanticMode || sortRef.current.sort !== spec.key) return undefined;
    return (sortRef.current.dir ?? spec.natural) === "asc" ? "ascending" : "descending";
  };

  const pParam = parseInt(sp.get("p") ?? "", 10);
  const page =
    Number.isFinite(pParam) && pParam > 0 ? pParam : stack.length + 1;
  const pageStart = (page - 1) * (query.limit ?? 40) + 1;
  const hasFilters = Boolean(
    spQ ||
      deal ||
      oa !== null ||
      doaj !== null ||
      quartile ||
      topic ||
      publisher ||
      hasApc !== null ||
      hasUtWorks !== null ||
      oaTypes.length > 0,
  );
  const hasNonQueryFilters = Boolean(
    deal ||
      oa !== null ||
      doaj !== null ||
      quartile ||
      topic ||
      publisher ||
      hasApc !== null ||
      hasUtWorks !== null ||
      oaTypes.length > 0,
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
      has_ut_works: undefined,
      oa_type: undefined,
    });

  // Detail pages offer a "Back to search" that restores this exact URL.
  React.useEffect(() => {
    if (hasFilters)
      sessionStorage.setItem("jb-last-search", `${pathname}?${sp.toString()}`);
  }, [hasFilters, pathname, sp]);

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      {/* Sidebar from ~960px up (user-set cutoff); narrower sidebar column
          between 960 and 1280 so the results keep enough width. Search and
          hero sit in the results column, above the results list. */}
      <div className="flex flex-col min-[960px]:grid min-[960px]:grid-cols-[15rem_minmax(0,1fr)] min-[960px]:items-start min-[960px]:gap-6 min-[1280px]:grid-cols-[18rem_minmax(0,1fr)] min-[1280px]:gap-8">
        {/* Hero and search: first in stacked flow, top of the results column from 960px. */}
        <section className="order-1 mb-8 min-[960px]:col-start-2 min-[960px]:row-start-1 min-[960px]:mb-6">
        <h1 className="mb-3 text-3xl font-bold text-balance">
          Find the best home for your next article
        </h1>
        <p className="mb-6 max-w-2xl text-[var(--muted-foreground)]">
          Search journals to see whether they are covered by an open access
          deal, what publishing there costs, and how the {site.name}{" "}
          publishes in them.
        </p>
        <form
          className="flex max-w-2xl flex-wrap gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            update({ q: input || undefined });
          }}
        >
          <div className="relative w-full min-[560px]:w-auto min-[560px]:flex-1">
            <Input
              id={SEARCH_INPUT_ID}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape") event.currentTarget.blur();
              }}
              placeholder={
                semanticMode
                  ? "Describe your topic, or paste an abstract"
                  : "Search by title, ISSN, publisher, or topic"
              }
              aria-label="Search journals"
              className="pr-8"
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
          {!semanticMode && (
            <select
              aria-label="Search scope"
              title="Which field the query matches: everything, journal title, publisher, or topic"
              value={searchIn}
              onChange={(event) => update({ search_in: event.target.value })}
              className="h-10 rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2"
            >
              {SEARCH_IN_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          )}
          <label
            className="flex h-10 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-2.5 text-sm select-none"
            title="Rank journals by meaning instead of exact words; filters and sorting are off in this mode"
          >
            <input
              type="checkbox"
              className="size-4 accent-[var(--primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2"
              checked={sp.get("mode") === "semantic"}
              onChange={(event) =>
                update({ mode: event.target.checked ? "semantic" : undefined })
              }
            />
            Match by meaning
          </label>
          <Button type="submit" className="flex-1 min-[560px]:flex-none">
            <Search aria-hidden className="size-4" /> Search
          </Button>
        </form>
        </section>

        {/* Stacked filter card: the only filter UI below 960px. */}
        {!semanticMode && (
          <section className="order-2 mb-6 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 min-[960px]:hidden">
            <FilterPanel
              facets={facets}
              selection={filterSelection}
              onToggle={handleFacetToggle}
              variant="chips"
            />
          </section>
        )}

        {/* Wide-screen sidebar: sticky, scrolls on its own when long. */}
        {!semanticMode && (
          <aside className="sticky top-20 hidden max-h-[calc(100vh-6rem)] self-start overflow-y-auto rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 min-[960px]:col-start-1 min-[960px]:row-span-2 min-[960px]:row-start-1 min-[960px]:block">
            <FilterPanel
              facets={facets}
              selection={filterSelection}
              onToggle={handleFacetToggle}
              variant="rows"
            />
          </aside>
        )}

        <div className="order-3 min-w-0 min-[960px]:col-start-2 min-[960px]:row-start-2">
          {/* Sort and reset belong with the results they act on. */}
          <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
            {!semanticMode && (
              <>
                <label htmlFor="sort" className="whitespace-nowrap">Sort by</label>
                <select
                  id="sort"
                  title="Order of the results. Match by meaning always ranks by similarity instead"
                  value={sort}
                  onChange={(event) => update({ sort: event.target.value })}
                  className="h-9 rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2"
                >
                  {SORTS.map((s) => (
                    <option key={s.value} value={s.value}>
                      {s.value === "institution_works"
                        ? `${site.short} works`
                        : s.label}
                    </option>
                  ))}
                </select>
                {hasFilters && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-[var(--muted-foreground)]"
                    title="Clears the search text and all active filters"
                    onClick={clearFilters}
                  >
                    {hasNonQueryFilters ? "Reset filters" : "Reset search"}
                  </Button>
                )}
              </>
            )}
            {semanticMode && (
              <p className="text-[var(--muted-foreground)]">
                {semantic
                  ? "Ranked by meaning; filters and sorting are off in this mode."
                  : "Match by meaning activates from two characters; regular search runs until then."}
              </p>
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
                  ? `${data.total.toLocaleString("en")} journal${data.total === 1 ? "" : "s"}`
                  : ""}
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
              {(cursor || sp.get("p")) && (
                // A stale or hand-edited cursor 400s forever; Retry re-sends
                // it. This drops cursor/page and restarts at page 1.
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-3 ml-2"
                  onClick={() => update({})}
                >
                  Back to page 1
                </Button>
              )}
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
                <>No journals match &ldquo;{spQ}&rdquo;.</>
              ) : (
                <>
                  No journals match
                  {hasNonQueryFilters ? " these filters" : ""}.
                </>
              )}
              {/* Zero hits still leaves pivots: facets stay query-free (see
                  useFacets) and meaning-based ranking skips the exact words. */}
              {spQ && !semanticMode && (
                <div className="mt-3">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => update({ mode: "semantic" })}
                  >
                    Try match by meaning
                  </Button>
                </div>
              )}
              {hasNonQueryFilters && (
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
                    className="relative border-b border-[var(--border)] py-3 first:pt-0 last:border-0 last:pb-0"
                  >
                    <Link
                      href={`/journals/${row.issn_l}`}
                      className="font-medium text-[var(--foreground)] underline-offset-2 after:absolute after:inset-0 after:content-[''] hover:text-[var(--primary-text)] hover:underline"
                    >
                      {row.title ?? row.issn_l}
                    </Link>
                    <div className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                      {row.publisher_name ?? "Unknown publisher"}
                      {row.primary_topic && ` · ${row.primary_topic}`}
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                      <DealBadge covered={row.deal_covered} />
                      <OaTypeBadge oaType={row.oa_type} isOa={row.is_oa} />
                      <QuartileBadge quartile={row.quartile ?? null} />
                    </div>
                    <div className="mt-1 text-xs tabular-nums text-[var(--muted-foreground)]">
                      {row.twente_works.toLocaleString("en")} {site.short} works
                      {row.apc_euro_latest != null &&
                        ` · APC €${formatApc(row.apc_euro_latest)}`}
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
                          <TableHead
                            key={header.id}
                            aria-sort={ariaSortFor(header.column.columnDef.meta)}
                          >
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
                    {table.getRowModel().rows.map((row) => {
                      // Whole-row click target; ctrl/cmd-click opens a tab.
                      const href = `/journals/${row.original.issn_l}`;
                      return (
                        <TableRow
                          key={row.id}
                          className={[
                            "cursor-pointer",
                            row.original.deal_covered
                              ? "bg-emerald-50/80 hover:bg-emerald-100 dark:bg-emerald-400/[0.08] dark:hover:bg-emerald-400/[0.12]"
                              : "",
                          ].join(" ")}
                          onClick={(event) => {
                            if (event.metaKey || event.ctrlKey)
                              window.open(href, "_blank", "noopener");
                            else router.push(href);
                          }}
                        >
                          {row.getVisibleCells().map((cell) => (
                            <TableCell key={cell.id}>
                              {flexRender(
                                cell.column.columnDef.cell,
                                cell.getContext(),
                              )}
                            </TableCell>
                          ))}
                        </TableRow>
                      );
                    })}
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
