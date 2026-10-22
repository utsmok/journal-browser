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

import { DealBadge, OaFlag, QuartileBadge } from "@/components/badges";
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
import type { JournalListItem, SortKey } from "@/lib/api";

const SORTS: { value: SortKey; label: string }[] = [
  { value: "relevance", label: "Relevance" },
  { value: "title", label: "Title" },
  { value: "institution_works", label: "UT works" },
  { value: "2yr_mean_citedness", label: "2yr mean citedness" },
];

type FacetValue = { value: string; count?: number; label?: string };

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
  // A browse-all with no query has nothing to rank, so UT works is the
  // sensible default order.
  const sort = (sp.get("sort") ?? (spQ ? "relevance" : "institution_works")) as SortKey;
  const deal = sp.get("deal") ?? "";
  const oa = sp.get("oa");
  const doaj = sp.get("doaj");
  const quartile = sp.get("quartile") ?? "";
  const topic = sp.get("topic") ?? "";

  const [input, setInput] = React.useState(spQ);
  const [cursor, setCursor] = React.useState<string | undefined>();
  const [stack, setStack] = React.useState<string[]>([]);

  // Reset keyset position whenever the query itself changes.
  React.useEffect(() => {
    setStack([]);
    setCursor(undefined);
  }, [sp]);

  const update = React.useCallback(
    (patch: Record<string, string | undefined>) => {
      const next = new URLSearchParams(sp.toString());
      for (const [key, value] of Object.entries(patch)) {
        if (!value) next.delete(key);
        else next.set(key, value);
      }
      router.replace(`${pathname}?${next}`, { scroll: false });
    },
    [pathname, router, sp],
  );

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

  const query = {
    q: spQ || undefined,
    deal: (deal || undefined) as "covered" | "not_covered" | undefined,
    oa: oa === null ? undefined : oa === "true",
    doaj: doaj === null ? undefined : doaj === "true",
    quartile: quartile || undefined,
    topic: topic || undefined,
    sort,
    cursor,
    limit: 20,
  };
  const { data, isPending, isFetching, isError, error, refetch } =
    useJournals(query);

  const facets = data?.facets ?? {};

  const facetGroup = (
    key: string,
    values: FacetValue[],
    activeValues: string[],
  ) => (
    <div className="flex flex-wrap items-center gap-1.5">
      {values.map((f) => {
        const active = activeValues.includes(f.value);
        return (
          <button
            key={f.value}
            type="button"
            onClick={() =>
              update({ [key]: sp.get(key) === f.value ? undefined : f.value })
            }
            aria-pressed={active}
            className={
              active
                ? "rounded-full bg-[var(--primary)] px-3 py-1 text-xs font-medium text-[var(--primary-foreground)]"
                : "rounded-full border border-[var(--border)] bg-[var(--card)] px-3 py-1 text-xs text-[var(--muted-foreground)] hover:border-[var(--primary)] hover:text-[var(--foreground)]"
            }
          >
            {f.label ?? f.value}
            {f.count !== undefined && (
              <span className="ml-1 tabular-nums opacity-70">{f.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );

  const topicValues: FacetValue[] = Object.entries(facets.topic ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([value, count]) => ({ value, count }));
  if (topic && !topicValues.some((t) => t.value === topic))
    topicValues.unshift({ value: topic });

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
                className="font-medium text-[var(--foreground)] underline-offset-2 hover:text-[var(--primary)] hover:underline"
              >
                {row.title ?? row.issn_l}
              </Link>
              <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-[var(--muted-foreground)]">
                <span>{row.publisher_name ?? "Unknown publisher"}</span>
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
        cell: (info) => <OaFlag isOa={info.getValue<boolean | null>()} />,
      },
      {
        accessorKey: "twente_works",
        header: "UT works 2020+",
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
        header: "2yr citedness",
        cell: (info) => {
          const v = info.getValue<number | null>();
          return v === null ? (
            <span className="text-[var(--muted-foreground)]">—</span>
          ) : (
            <span
              className="tabular-nums"
              title="2yr mean citedness (OpenAlex)"
            >
              {v.toFixed(1)}
            </span>
          );
        },
      },
    ],
    [],
  );

  const rows = data?.items ?? [];
  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  const pageStart = stack.length * (query.limit ?? 20) + 1;
  const hasFilters = Boolean(
    spQ || deal || oa !== null || doaj !== null || quartile || topic,
  );

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
          <Input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Search by journal title or ISSN"
            aria-label="Search journals"
          />
          <Button type="submit">
            <Search aria-hidden className="size-4" /> Search
          </Button>
        </form>
      </section>

      <section className="mb-6 space-y-2.5 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm">
            <label htmlFor="sort">Sort by</label>
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
          </div>
        </div>
        {facetGroup(
          "deal",
          Object.entries(facets.deal_coverage ?? {}).map(([value, count]) => ({
            value,
            count,
            label: value === "covered" ? "Deal coverage" : "No deal",
          })),
          deal ? [deal] : [],
        )}
        {facetGroup(
          "oa",
          Object.entries(facets.oa ?? {}).map(([value, count]) => ({
            value,
            count,
            label: value === "true" ? "OA journal" : "Not OA",
          })),
          oa !== null ? [oa] : [],
        )}
        {facetGroup(
          "doaj",
          Object.entries(facets.doaj ?? {}).map(([value, count]) => ({
            value,
            count,
            label: value === "true" ? "In DOAJ" : "Not in DOAJ",
          })),
          doaj !== null ? [doaj] : [],
        )}
        {facetGroup(
          "quartile",
          ["Q1", "Q2", "Q3", "Q4"].map((q) => ({
            value: q,
            count: facets.quartile?.[q] ?? 0,
          })),
          quartile ? [quartile] : [],
        )}
        {topicValues.length > 0 &&
          facetGroup("topic", topicValues, topic ? [topic] : [])}
      </section>

      <Card>
        <CardContent className="pt-6">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <p aria-live="polite" className="text-sm text-[var(--muted-foreground)]">
              {data
                ? `${data.total.toLocaleString("en")} journals`
                : "Loading…"}
              {isFetching && data ? " · updating…" : ""}
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={stack.length === 0}
                onClick={() => {
                  const next = stack.slice(0, -1);
                  setStack(next);
                  setCursor(next[next.length - 1]);
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
                  setStack((s) => [...s, data.next_cursor!]);
                  setCursor(data.next_cursor);
                }}
              >
                Next <ChevronRight aria-hidden className="size-4" />
              </Button>
            </div>
          </div>

          {isError ? (
            <div className="py-10 text-center">
              <p className="text-[var(--destructive)]">
                {(error as Error)?.message ?? "Failed to load journals."}
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
              No journals match{hasFilters ? " these filters" : ""}.
              {hasFilters && (
                <div className="mt-3">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      update({
                        q: undefined,
                        deal: undefined,
                        oa: undefined,
                        doaj: undefined,
                        quartile: undefined,
                        topic: undefined,
                      })
                    }
                  >
                    Clear filters
                  </Button>
                </div>
              )}
            </div>
          ) : (
            <Table className={isFetching ? "opacity-60" : undefined}>
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
          )}

          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-xs text-[var(--muted-foreground)]">
            <span>
              Showing {rows.length > 0 ? pageStart : 0}–
              {pageStart + rows.length - 1} of{" "}
              {(data?.total ?? 0).toLocaleString("en")}
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
  );
}
