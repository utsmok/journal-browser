"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { ActiveFiltersBar, type ActiveFilterChip } from "@/components/active-filters-bar";
import { DirectoryPager } from "@/components/directory-pager";
import { FacetGroupList, type FacetGroupDef } from "@/components/filter-panel";
import { rememberDirectoryUrl } from "@/components/journal/section-nav";
import { SortHead } from "@/components/search/sort-head";
import { SourceNote } from "@/components/source-note";
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
import { useFunderDirectory } from "@/hooks/use-api";
import { useInstitution } from "@/hooks/use-institution";
import { useSearchShortcut } from "@/hooks/use-search-shortcut";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { useYearRange } from "@/hooks/use-year-filter";
import { errorMessage, type FunderSearchSort } from "@/lib/api";
import { countryName } from "@/lib/format";
import { FUNDER_COLUMN_SORTS } from "@/lib/search-config";

const OPF_URL = "https://openpolicyfinder.jisc.ac.uk/";
const SEARCH_INPUT_ID = "funder-search";
const PAGE_SIZES = [25, 50, 100];

function paramValues(sp: { get(key: string): string | null }, key: string): string[] {
  return (sp.get(key) ?? "").split("|").filter(Boolean);
}

function FundersPageInner() {
  const t = useTranslations("funders");
  const tc = useTranslations("common");
  const inst = useInstitution();
  const site = useSiteMeta();
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { year_from, year_to } = useYearRange();

  useSearchShortcut(SEARCH_INPUT_ID);

  const q = sp.get("q") ?? "";
  const [input, setInput] = React.useState(q);
  const countries = paramValues(sp, "country");
  const policyParam = sp.get("policy_structured");
  const policyStructured =
    policyParam === "true" ? true : policyParam === "false" ? false : undefined;
  const sortParam = sp.get("sort");
  const sort: FunderSearchSort | undefined =
    sortParam === "works" || sortParam === "name" ? sortParam : undefined;
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
      if (!("offset" in patch)) next.delete("offset");
      router.replace(`${pathname}?${next}`, { scroll: false });
    },
    [pathname, router, sp],
  );

  React.useEffect(() => {
    setInput(q);
  }, [q]);
  React.useEffect(() => {
    const timer = setTimeout(() => {
      if (input !== q) setParams({ q: input || undefined });
    }, 300);
    return () => clearTimeout(timer);
  }, [input, q, setParams]);

  const yearsKey = `${year_from ?? ""}-${year_to ?? ""}`;
  const prevYearsKey = React.useRef(yearsKey);
  React.useEffect(() => {
    if (prevYearsKey.current === yearsKey) return;
    prevYearsKey.current = yearsKey;
    if (offset > 0) setParams({ offset: undefined });
  }, [yearsKey, offset, setParams]);

  React.useEffect(() => {
    const qs = sp.toString();
    rememberDirectoryUrl("jb-last-funders", qs ? `${pathname}?${qs}` : pathname);
  }, [pathname, sp]);

  const { data, isPending, isFetching, isError, error, refetch } = useFunderDirectory({
    q: q || undefined,
    country: countries.length > 0 ? countries : undefined,
    policy_structured: policyStructured,
    sort,
    dir: dir ?? undefined,
    offset,
    limit: pageSize,
    year_from,
    year_to,
  });

  const rows = data?.items ?? [];
  const total = data?.total ?? 0;
  const facets = data?.facets;
  const anyFilter = countries.length > 0 || policyStructured !== undefined;

  const toggleFacet = (key: string, value: string) => {
    if (key === "country") {
      const next = countries.includes(value)
        ? countries.filter((c) => c !== value)
        : [...countries, value];
      setParams({ country: next.join("|") || undefined });
      return;
    }
    if (key === "policy_structured") {
      setParams({
        policy_structured: policyParam === value ? undefined : value,
      });
    }
  };

  const clearAll = () => {
    setInput("");
    setParams({
      q: undefined,
      country: undefined,
      policy_structured: undefined,
    });
  };

  const cycleSort = (columnId: string) => {
    const spec = FUNDER_COLUMN_SORTS[columnId];
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
  const sortHeadState = { sort, dir, cycleSort, specs: FUNDER_COLUMN_SORTS };
  const ariaSortFor = (columnId: string): "ascending" | "descending" | undefined => {
    const spec = FUNDER_COLUMN_SORTS[columnId];
    if (!spec || sort !== spec.key) return undefined;
    return (dir ?? spec.natural) === "asc" ? "ascending" : "descending";
  };

  const countryBuckets = Object.entries(facets?.country ?? {}).map(([value, count]) => ({
    value,
    count,
    label: countryName(value),
  }));
  for (const code of countries) {
    if (!countryBuckets.some((b) => b.value === code)) {
      countryBuckets.unshift({ value: code, count: 0, label: countryName(code) });
    }
  }

  const groups: FacetGroupDef[] = [
    ...(countryBuckets.length > 0
      ? [
          {
            key: "country",
            label: t("search.facets.country"),
            defaultOpen: true,
            searchable: true,
            initialVisible: 8,
            values: countryBuckets,
            activeValues: countries,
          },
        ]
      : []),
    {
      key: "policy_structured",
      label: t("search.facets.policy"),
      defaultOpen: true,
      values: [
        {
          value: "true",
          count: facets?.policy_structured?.true,
          label: t("search.facets.policyStructured"),
        },
        {
          value: "false",
          count: facets?.policy_structured?.false,
          label: t("search.facets.policyTextOnly"),
        },
      ],
      activeValues: policyParam ? [policyParam] : [],
    },
  ];

  const chips: ActiveFilterChip[] = [
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
    ...countries.map((code) => ({
      id: `country:${code}`,
      label: `${t("search.facets.country")}: ${countryName(code)}`,
      onRemove: () => toggleFacet("country", code),
    })),
    ...(policyStructured !== undefined
      ? [
          {
            id: "policy_structured",
            label: `${t("search.facets.policy")}: ${
              policyStructured
                ? t("search.facets.policyStructured")
                : t("search.facets.policyTextOnly")
            }`,
            onRemove: () => setParams({ policy_structured: undefined }),
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
            setParams({ q: input.trim() || undefined });
          }}
        >
          <div className="relative flex-1">
            <Input
              id={SEARCH_INPUT_ID}
              type="search"
              value={input}
              onChange={(e) => setInput(e.target.value)}
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
          <Button type="submit">{t("search.funder")}</Button>
        </form>
      </header>

      {/* Stacked filters (<960px) */}
      {data != null && groups.length > 0 && (
        <section className="mb-6 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 min-[960px]:hidden">
          <FacetGroupList groups={groups} onToggle={toggleFacet} variant="chips" />
        </section>
      )}

      <div className="flex flex-col gap-6 min-[960px]:grid min-[960px]:grid-cols-[15rem_minmax(0,1fr)] min-[960px]:items-start min-[1280px]:grid-cols-[18rem_minmax(0,1fr)] min-[1280px]:gap-8">
        {/* Sticky sidebar (>=960px) */}
        {data != null && groups.length > 0 ? (
          <aside className="sticky top-20 hidden max-h-[calc(100vh-6rem)] self-start overflow-y-auto rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 min-[960px]:block">
            <FacetGroupList groups={groups} onToggle={toggleFacet} variant="rows" />
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
            <CardContent className="pt-6">
              {isError ? (
                <div className="py-10 text-center">
                  <p className="text-[var(--destructive)]">{errorMessage(tc, error)}</p>
                  <Button variant="outline" size="sm" className="mt-3" onClick={() => refetch()}>
                    {t("search.retry")}
                  </Button>
                </div>
              ) : isPending ? (
                <ListSkeletonRows rows={8} />
              ) : rows.length === 0 ? (
                <div className="py-10 text-center text-[var(--muted-foreground)]">
                  <p>{anyFilter ? t("search.emptyFilters") : t("search.empty", { q })}</p>
                  {(anyFilter || q) && (
                    <div className="mt-3">
                      <Button variant="outline" size="sm" onClick={clearAll}>
                        {tc("activeFilters.clearAll")}
                      </Button>
                    </div>
                  )}
                </div>
              ) : (
                <>
                  {/* Stacked mobile cards */}
                  <ul className={isFetching ? "opacity-60 md:hidden" : "md:hidden"}>
                    {rows.map((f) => (
                      <li
                        key={f.id}
                        className="border-b border-[var(--border)] py-3 first:pt-0 last:border-0 last:pb-0"
                      >
                        <Link
                          href={`/${inst}/funders/${f.id}`}
                          className="font-medium text-[var(--foreground)] underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                        >
                          {f.name ?? t("unnamedFunder", { id: f.id })}
                        </Link>
                        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs tabular-nums text-[var(--muted-foreground)]">
                          <span>{countryName(f.country)}</span>
                          <span>
                            {f.n_ut_works.toLocaleString("en")}{" "}
                            {t("instWorks", { inst: site.short })}
                          </span>
                          <span>
                            {f.policy_structured
                              ? t("search.facets.policyStructured")
                              : t("search.facets.policyTextOnly")}
                          </span>
                        </div>
                      </li>
                    ))}
                  </ul>

                  {/* Desktop table */}
                  <div className={isFetching ? "hidden opacity-60 md:block" : "hidden md:block"}>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead aria-sort={ariaSortFor("name")}>
                            <SortHead
                              columnId="name"
                              label={t("search.funder")}
                              state={sortHeadState}
                            />
                          </TableHead>
                          <TableHead>{t("search.country")}</TableHead>
                          <TableHead>{t("search.facets.policy")}</TableHead>
                          <TableHead className="text-right" aria-sort={ariaSortFor("works")}>
                            <SortHead
                              columnId="works"
                              label={t("instWorks", { inst: site.short })}
                              state={sortHeadState}
                            />
                          </TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {rows.map((f) => (
                          <TableRow key={f.id}>
                            <TableCell className="font-medium">
                              <Link
                                href={`/${inst}/funders/${f.id}`}
                                className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                              >
                                {f.name ?? t("unnamedFunder", { id: f.id })}
                              </Link>
                            </TableCell>
                            <TableCell className="text-[var(--muted-foreground)]">
                              {countryName(f.country)}
                            </TableCell>
                            <TableCell className="text-xs text-[var(--muted-foreground)]">
                              {f.policy_structured
                                ? t("search.facets.policyStructured")
                                : t("search.facets.policyTextOnly")}
                            </TableCell>
                            <TableCell className="text-right tabular-nums">
                              {f.n_ut_works.toLocaleString("en")}
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
                    perPageLabel={tc("pagination.perPage")}
                    prevLabel={t("search.prev")}
                    nextLabel={t("search.next")}
                    isFetching={isFetching}
                  />
                </>
              )}
              <div className="mt-3">
                <SourceNote
                  source={t("sourceJisc")}
                  url={OPF_URL}
                  codes={["jisc-policy-currency"]}
                  howBuilt={tc("sourceNote.explain.greenOa")}
                />
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

/** useSearchParams needs a Suspense boundary during prerender. */
export default function FundersPage() {
  return (
    <React.Suspense fallback={null}>
      <FundersPageInner />
    </React.Suspense>
  );
}
