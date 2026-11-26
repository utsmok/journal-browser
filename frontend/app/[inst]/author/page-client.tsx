"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { ActiveFiltersBar, type ActiveFilterChip } from "@/components/active-filters-bar";
import { CollapsibleCard } from "@/components/collapsible-card";
import { DirectoryPager } from "@/components/directory-pager";
import { FilterLayout } from "@/components/filter-layout";
import {
  FacetGroupList,
  hasVisibleGroups,
  type FacetGroupDef,
  type FacetValue,
} from "@/components/filter-panel";
import { rememberDirectoryUrl } from "@/components/journal/section-nav";
import { OrcidLink } from "@/components/orcid-link";
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
import { useAuthorDirectory } from "@/hooks/use-api";
import { useInstitution } from "@/hooks/use-institution";
import { useSearchShortcut } from "@/hooks/use-search-shortcut";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { useYearRange } from "@/hooks/use-year-filter";
import { errorMessage, type AuthorFacetBucket, type AuthorSearchSort } from "@/lib/api";
import { AUTHOR_COLUMN_SORTS } from "@/lib/search-config";

import { authorDirectoryParams } from "./params";

const SEARCH_INPUT_ID = "author-search";

/** Matches the journal page's sort-select styling. */
const SELECT_CLASS =
  "h-9 w-full rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-2 min-[768px]:w-auto focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2";

/** Top N buckets, with every active value kept visible even outside the slice. */
function topBuckets(
  buckets: AuthorFacetBucket[] | undefined,
  active: string[],
  limit = 8,
): FacetValue[] {
  const list: FacetValue[] = (buckets ?? [])
    .slice(0, limit)
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
  const t = useTranslations("authors");
  const tc = useTranslations("common");
  const inst = useInstitution();
  const site = useSiteMeta();
  const sorts: { value: AuthorSearchSort; label: string }[] = [
    { value: "works_desc", label: t("sort.mostPublications") },
    { value: "name_asc", label: t("sort.nameAZ") },
    { value: "name_desc", label: t("sort.nameZA") },
    { value: "last_pub_desc", label: t("sort.latestPublication") },
  ];
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  // The publication-year lens is context state (header control), like the
  // journal search: it scopes the counts, not the URL.
  const { year_from, year_to } = useYearRange();
  useSearchShortcut(SEARCH_INPUT_ID);

  // URL → state mapping lives in params.ts, shared with the server page, so
  // the seeded React Query key matches this first render exactly. The year
  // lens is context state (header control): it scopes the counts, not the
  // URL.
  const { q, query, hasOrcid, selected, sort, pageSize, offset, filters, opts } =
    authorDirectoryParams(sp, { year_from, year_to });
  const [input, setInput] = React.useState(q);
  const anyFilter =
    hasOrcid !== null || Object.values(selected).some((values) => values.length > 0);

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

  const yearsKey = `${year_from ?? ""}-${year_to ?? ""}`;
  const prevYearsKey = React.useRef(yearsKey);
  React.useEffect(() => {
    if (prevYearsKey.current === yearsKey) return;
    prevYearsKey.current = yearsKey;
    if (offset > 0) setParams({ offset: undefined });
  }, [yearsKey, offset, setParams]);

  React.useEffect(() => {
    const qs = sp.toString();
    rememberDirectoryUrl("jb-last-authors", qs ? `${pathname}?${qs}` : pathname);
  }, [pathname, sp]);

  const { data, isPending, isFetching, isError, error, refetch } = useAuthorDirectory(
    query,
    filters,
    opts,
  );

  const rows = data?.items ?? [];
  const disabled = data != null && !data.enabled;
  const facets = data?.facets;

  const total = data?.total ?? 0;

  const sortHeadState = {
    sort: sort === "name_desc" ? "name_asc" : sort,
    dir: (sort === "name_asc" ? "asc" : "desc") as "asc" | "desc",
    specs: AUTHOR_COLUMN_SORTS,
    cycleSort: (columnId: string) => {
      if (columnId === "name") {
        if (sort === "name_asc") setParams({ sort: "name_desc" });
        else if (sort === "name_desc") setParams({ sort: undefined });
        else setParams({ sort: "name_asc" });
        return;
      }
      if (columnId === "works") {
        setParams({ sort: undefined });
        return;
      }
      if (columnId === "last_pub") {
        setParams({ sort: sort === "last_pub_desc" ? undefined : "last_pub_desc" });
      }
    },
  };
  const ariaSortFor = (columnId: string): "ascending" | "descending" | undefined => {
    if (columnId === "name") {
      if (sort === "name_asc") return "ascending";
      if (sort === "name_desc") return "descending";
      return undefined;
    }
    if (columnId === "works" && sort === "works_desc") return "descending";
    if (columnId === "last_pub" && sort === "last_pub_desc") return "descending";
    return undefined;
  };

  const toggleFacet = (key: string, value: string) => {
    if (key === "has_orcid") {
      setParams({ has_orcid: hasOrcid === value ? undefined : value });
      return;
    }
    const current = selected[key as keyof typeof selected];
    const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value];
    setParams({ [key]: next.join("|") || undefined });
  };

  const clearFilters = () => {
    setInput("");
    setParams({
      q: undefined,
      faculty: undefined,
      org: undefined,
      works: undefined,
      last_pub: undefined,
      topic: undefined,
      has_orcid: undefined,
    });
  };

  const worksLabels: Record<string, string> = {
    "1-4": t("filters.works1to4"),
    "5-19": t("filters.works5to19"),
    "20-49": t("filters.works20to49"),
    "50+": t("filters.works50plus"),
  };
  const lastPubLabels: Record<string, string> = {
    "2025-2026": t("filters.lastPub2025to2026"),
    "2022-2024": t("filters.lastPub2022to2024"),
    "2020-2021": t("filters.lastPub2020to2021"),
    none: t("filters.lastPubNone"),
  };

  const groups: FacetGroupDef[] = [
    {
      key: "faculty",
      label: t("filters.faculty"),
      defaultOpen: true,
      searchable: true,
      initialVisible: 8,
      values: topBuckets(facets?.faculty, selected.faculty, 30),
      activeValues: selected.faculty,
    },
    {
      key: "org",
      label: t("filters.group"),
      defaultOpen: true,
      searchable: true,
      initialVisible: 8,
      values: topBuckets(facets?.org, selected.org, 40),
      activeValues: selected.org,
    },
    {
      key: "works",
      label: t("filters.publications"),
      defaultOpen: true,
      values: (facets?.works ?? []).map((b) => ({
        value: b.value,
        count: b.count,
        label: worksLabels[b.value] ?? b.value,
      })),
      activeValues: selected.works,
    },
    {
      key: "last_pub",
      label: t("filters.lastPublication"),
      defaultOpen: true,
      values: (facets?.last_pub ?? []).map((b) => ({
        value: b.value,
        count: b.count,
        label: lastPubLabels[b.value] ?? b.value,
      })),
      activeValues: selected.last_pub,
    },
    {
      key: "topic",
      label: t("filters.topic"),
      defaultOpen: false,
      searchable: true,
      initialVisible: 8,
      values: topBuckets(facets?.topic, selected.topic, 30),
      activeValues: selected.topic,
    },
    {
      key: "has_orcid",
      label: t("filters.orcid"),
      defaultOpen: true,
      values: [
        { value: "yes", label: t("filters.hasOrcid") },
        { value: "no", label: t("filters.noOrcid") },
      ],
      activeValues: hasOrcid ? [hasOrcid] : [],
    },
  ].filter((group) => group.values.length > 0);

  const filterChips: ActiveFilterChip[] = [
    ...(q
      ? [
          {
            id: "q",
            label: `Search: “${q}”`,
            onRemove: () => {
              setInput("");
              setParams({ q: undefined });
            },
          },
        ]
      : []),
    ...selected.faculty.map((v) => ({
      id: `faculty:${v}`,
      label: `${t("filters.faculty")}: ${v}`,
      onRemove: () => toggleFacet("faculty", v),
    })),
    ...selected.org.map((v) => ({
      id: `org:${v}`,
      label: `${t("filters.group")}: ${v}`,
      onRemove: () => toggleFacet("org", v),
    })),
    ...selected.works.map((v) => ({
      id: `works:${v}`,
      label: `${t("filters.publications")}: ${worksLabels[v] ?? v}`,
      onRemove: () => toggleFacet("works", v),
    })),
    ...selected.last_pub.map((v) => ({
      id: `last_pub:${v}`,
      label: `${t("filters.lastPublication")}: ${lastPubLabels[v] ?? v}`,
      onRemove: () => toggleFacet("last_pub", v),
    })),
    ...selected.topic.map((v) => ({
      id: `topic:${v}`,
      label: `${t("filters.topic")}: ${v}`,
      onRemove: () => toggleFacet("topic", v),
    })),
    ...(hasOrcid
      ? [
          {
            id: `has_orcid:${hasOrcid}`,
            label: `${t("filters.orcid")}: ${hasOrcid === "yes" ? t("filters.hasOrcid") : t("filters.noOrcid")}`,
            onRemove: () => toggleFacet("has_orcid", hasOrcid),
          },
        ]
      : []),
  ];

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <header className="mb-6">
        <h1 className="mb-2 text-3xl font-bold text-balance">{t("list.heading")}</h1>
        <p className="mb-4 max-w-2xl text-sm text-[var(--muted-foreground)]">
          {t("list.intro", { name: site.name })}
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
                placeholder={t("list.searchPlaceholder")}
                aria-label={t("list.searchLabel")}
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
            <Button type="submit">{t("list.searchButton")}</Button>
          </form>
        )}
      </header>

      <FilterLayout
        filters={<FacetGroupList groups={groups} onToggle={toggleFacet} />}
        activeCount={filterChips.length}
        onReset={clearFilters}
        resetTitle={t("list.resetTitle")}
        disabled={disabled || data == null || !hasVisibleGroups(groups)}
      >
        {!disabled && (
          <ActiveFiltersBar
            chips={filterChips}
            onClearAll={clearFilters}
            ariaLabel={tc("activeFilters.label")}
            clearLabel={tc("activeFilters.clearAll")}
            removeAriaPrefix={tc("activeFilters.remove")}
          />
        )}

        {disabled ? (
          <CollapsibleCard
            id="authors-disabled"
            title={t("list.disabledTitle")}
            contentClassName="text-sm text-[var(--muted-foreground)]"
          >
            {t("list.disabledBody")}
          </CollapsibleCard>
        ) : (
          <Card>
            <CardContent className="pt-5">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] pb-3">
                <p className="text-sm text-[var(--muted-foreground)]">
                  {/* Announce only settled counts: while a fetch runs the live
                      region keeps its previous text, so typing never chatters. */}
                  <span aria-live="polite">
                    {data
                      ? q
                        ? t("results.countMatching", { count: data.total, query: q })
                        : t("results.count", { count: data.total })
                      : ""}
                  </span>
                  {isFetching && data ? ` · ${t("results.updating")}` : ""}
                </p>
                <div className="flex min-w-0 flex-col items-start gap-1 text-sm min-[768px]:flex-row min-[768px]:items-center min-[768px]:gap-2">
                  <label
                    htmlFor="author-sort"
                    className="whitespace-nowrap text-xs text-[var(--muted-foreground)]"
                  >
                    {t("list.sortBy")}
                  </label>
                  <select
                    id="author-sort"
                    title={t("list.sortTitle")}
                    value={sort}
                    onChange={(event) =>
                      setParams({
                        sort: event.target.value === "works_desc" ? undefined : event.target.value,
                      })
                    }
                    className={SELECT_CLASS}
                  >
                    {sorts.map((s) => (
                      <option key={s.value} value={s.value}>
                        {s.label}
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
                    <>{t("results.emptyQuery", { query: q })}</>
                  ) : (
                    <>
                      {anyFilter ? t("results.emptyFiltered") : t("results.empty")}
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
                  {q && data?.q_match && data.q_match !== "name" && (
                    <p className="mb-3 text-sm text-[var(--muted-foreground)]">
                      {t(data.q_match === "topic" ? "results.matchTopic" : "results.matchGroup", {
                        query: q,
                      })}
                    </p>
                  )}
                  {q && rows.every((r) => !r.confirmed) && (
                    <p className="mb-3 text-sm text-[var(--muted-foreground)]">
                      {t("results.unverifiedHint", { query: q })}
                    </p>
                  )}
                  {/* Stacked cards on narrow viewports: seven columns would push
                      the works count off-screen behind horizontal scrolling. */}
                  <ul
                    className={isFetching ? "opacity-60 md:hidden" : "md:hidden"}
                    aria-label={t("results.listLabel")}
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
                          <span>{t("worksCount", { count: a.n_works })}</span>
                          {a.last_pub_year != null && (
                            <span>{t("results.lastPub", { year: a.last_pub_year })}</span>
                          )}
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
                      <caption className="sr-only">{t("results.caption")}</caption>
                      <TableHeader>
                        <TableRow>
                          <TableHead aria-sort={ariaSortFor("name")}>
                            <SortHead
                              columnId="name"
                              label={t("results.colName")}
                              state={sortHeadState}
                            />
                          </TableHead>
                          <TableHead>{t("results.colFaculty")}</TableHead>
                          <TableHead>{t("results.colGroup")}</TableHead>
                          <TableHead className="text-right" aria-sort={ariaSortFor("works")}>
                            <SortHead
                              columnId="works"
                              label={t("results.colWorks")}
                              state={sortHeadState}
                            />
                          </TableHead>
                          <TableHead className="text-right" aria-sort={ariaSortFor("last_pub")}>
                            <SortHead
                              columnId="last_pub"
                              label={t("results.colLastPub")}
                              state={sortHeadState}
                            />
                          </TableHead>
                          <TableHead>{t("results.colTopic")}</TableHead>
                          <TableHead>{t("results.colOrcid")}</TableHead>
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
                            <TableCell>{a.orcid ? <OrcidLink orcid={a.orcid} /> : null}</TableCell>
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
                    perPageLabel={t("list.perPage")}
                    prevLabel={t("results.prevShort")}
                    nextLabel={t("results.nextShort")}
                    isFetching={isFetching}
                  />
                </>
              )}
            </CardContent>
          </Card>
        )}
      </FilterLayout>
    </div>
  );
}
