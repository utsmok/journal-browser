"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
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
import { errorMessage, type FunderListItem, type FunderSearchSort } from "@/lib/api";
import { countryName } from "@/lib/format";
import { FUNDER_COLUMN_SORTS } from "@/lib/search-config";

import { funderDirectoryParams } from "./params";

const OPF_URL = "https://openpolicyfinder.jisc.ac.uk/";
const SEARCH_INPUT_ID = "funder-search";

const SELECT_CLASS =
  "h-9 w-full rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-2 text-sm min-[768px]:w-auto focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2";

const REQ_ORDER = ["requires", "encourages", "no_policy_for", "does_not_mention", "none"] as const;

function toggleMultiParam(list: string[], value: string): string | undefined {
  const next = list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
  return next.join("|") || undefined;
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

  const {
    params,
    q,
    countries,
    hasWorksParam,
    hasWorks,
    oaPub,
    greenArch,
    dataPolicy,
    policyParam,
    policyStructured,
    sort,
    dir,
    pageSize,
    offset,
  } = funderDirectoryParams(sp, { year_from, year_to });
  const [input, setInput] = React.useState(q);

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

  const { data, isPending, isFetching, isError, error, refetch } = useFunderDirectory(params);

  const rows = data?.items ?? [];
  const total = data?.total ?? 0;
  const facets = data?.facets;
  const anyFilter =
    countries.length > 0 ||
    hasWorks !== undefined ||
    oaPub.length > 0 ||
    greenArch.length > 0 ||
    dataPolicy.length > 0 ||
    policyStructured !== undefined;

  const reqLabel = React.useCallback(
    (code: string | null | undefined): string => {
      const normalized = (code || "none").toLowerCase();
      if (normalized === "requires") return t("search.facets.reqRequires");
      if (normalized === "encourages") return t("search.facets.reqEncourages");
      if (normalized === "no_policy_for") return t("search.facets.reqNone");
      if (normalized === "does_not_mention") return t("search.facets.reqNotMentioned");
      if (normalized === "none") return t("search.facets.reqMissing");
      return normalized.replaceAll("_", " ");
    },
    [t],
  );

  const toggleFacet = (key: string, value: string) => {
    if (key === "has_works") {
      setParams({ has_works: hasWorksParam === value ? undefined : value });
      return;
    }
    if (key === "oa_publishing") {
      setParams({ oa_publishing: toggleMultiParam(oaPub, value) });
      return;
    }
    if (key === "green_archiving") {
      setParams({ green_archiving: toggleMultiParam(greenArch, value) });
      return;
    }
    if (key === "data_policy") {
      setParams({ data_policy: toggleMultiParam(dataPolicy, value) });
      return;
    }
    if (key === "country") {
      setParams({ country: toggleMultiParam(countries, value) });
      return;
    }
    if (key === "policy_structured") {
      setParams({ policy_structured: policyParam === value ? undefined : value });
    }
  };

  const clearAll = () => {
    setInput("");
    setParams({
      q: undefined,
      country: undefined,
      has_works: undefined,
      oa_publishing: undefined,
      green_archiving: undefined,
      data_policy: undefined,
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

  const reqValues = (
    counts: Record<string, number> | undefined,
    active: string[],
  ): FacetValue[] => {
    const seen = new Set<string>();
    const list: FacetValue[] = [];
    for (const key of REQ_ORDER) {
      const count = counts?.[key];
      if (count !== undefined && (count > 0 || active.includes(key))) {
        seen.add(key);
        list.push({ value: key, count, label: reqLabel(key) });
      }
    }
    for (const [value, count] of Object.entries(counts ?? {})) {
      if (!seen.has(value) && (count > 0 || active.includes(value))) {
        list.push({ value, count, label: reqLabel(value) });
      }
    }
    for (const value of active) {
      if (!list.some((v) => v.value === value)) {
        list.unshift({ value, count: 0, label: reqLabel(value) });
      }
    }
    return list;
  };

  const countryBuckets: FacetValue[] = Object.entries(facets?.country ?? {}).map(
    ([value, count]) => ({
      value,
      count,
      label: countryName(value),
    }),
  );
  for (const code of countries) {
    if (!countryBuckets.some((b) => b.value === code)) {
      countryBuckets.unshift({ value: code, count: 0, label: countryName(code) });
    }
  }

  const groups: FacetGroupDef[] = [
    {
      key: "has_works",
      label: t("search.facets.instWorks", { inst: site.short }),
      defaultOpen: true,
      values: [
        {
          value: "true",
          count: facets?.has_works?.true,
          label: t("search.facets.hasWorksYes", { inst: site.short }),
        },
        {
          value: "false",
          count: facets?.has_works?.false,
          label: t("search.facets.hasWorksNo", { inst: site.short }),
        },
      ],
      activeValues: hasWorksParam ? [hasWorksParam] : [],
    },
    {
      key: "oa_publishing",
      label: t("search.facets.oaPublishing"),
      defaultOpen: true,
      values: reqValues(facets?.oa_publishing, oaPub),
      activeValues: oaPub,
    },
    {
      key: "green_archiving",
      label: t("search.facets.greenArchiving"),
      defaultOpen: true,
      values: reqValues(facets?.green_archiving, greenArch),
      activeValues: greenArch,
    },
    {
      key: "data_policy",
      label: t("search.facets.dataPolicy"),
      defaultOpen: true,
      values: reqValues(facets?.data_policy, dataPolicy),
      activeValues: dataPolicy,
    },
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
    ...(hasWorks !== undefined
      ? [
          {
            id: "has_works",
            label: `${t("search.facets.instWorks", { inst: site.short })}: ${
              hasWorks
                ? t("search.facets.hasWorksYes", { inst: site.short })
                : t("search.facets.hasWorksNo", { inst: site.short })
            }`,
            onRemove: () => setParams({ has_works: undefined }),
          },
        ]
      : []),
    ...oaPub.map((v) => ({
      id: `oa_publishing:${v}`,
      label: `${t("search.facets.oaPublishing")}: ${reqLabel(v)}`,
      onRemove: () => toggleFacet("oa_publishing", v),
    })),
    ...greenArch.map((v) => ({
      id: `green_archiving:${v}`,
      label: `${t("search.facets.greenArchiving")}: ${reqLabel(v)}`,
      onRemove: () => toggleFacet("green_archiving", v),
    })),
    ...dataPolicy.map((v) => ({
      id: `data_policy:${v}`,
      label: `${t("search.facets.dataPolicy")}: ${reqLabel(v)}`,
      onRemove: () => toggleFacet("data_policy", v),
    })),
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

  const policySummary = (f: FunderListItem) => {
    const parts: { label: string; req: string | null | undefined }[] = [
      { label: t("search.facets.oaPublishing"), req: f.oa_publishing_req },
      { label: t("search.facets.greenArchiving"), req: f.green_archiving_req },
      { label: t("search.facets.dataPolicy"), req: f.data_policy_req },
    ];
    return (
      <div className="flex flex-wrap gap-1.5">
        {parts.map((part) => {
          const val = (part.req || "none").toLowerCase();
          const tone =
            val === "requires"
              ? "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-400/35 dark:bg-emerald-400/15 dark:text-emerald-200"
              : val === "encourages"
                ? "border-blue-300 bg-blue-50 text-blue-900 dark:border-blue-400/35 dark:bg-blue-400/15 dark:text-blue-200"
                : "border-[var(--border)] bg-[var(--muted)] text-[var(--muted-foreground)]";
          return (
            <span
              key={part.label}
              className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] leading-tight ${tone}`}
            >
              <span className="opacity-80">{part.label}:</span>
              <span className="font-medium">{reqLabel(val)}</span>
            </span>
          );
        })}
      </div>
    );
  };

  const from = rows.length > 0 ? offset + 1 : 0;
  const to = offset + rows.length;

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
          <Button type="submit">{t("search.searchButton")}</Button>
        </form>
      </header>

      <FilterLayout
        filters={<FacetGroupList groups={groups} onToggle={toggleFacet} />}
        activeCount={chips.length}
        onReset={clearAll}
        disabled={data == null || !hasVisibleGroups(groups)}
      >
        <ActiveFiltersBar
          chips={chips}
          onClearAll={clearAll}
          ariaLabel={tc("activeFilters.label")}
          clearLabel={tc("activeFilters.clearAll")}
          removeAriaPrefix={tc("activeFilters.remove")}
        />

        <Card>
          <CardContent className="pt-5">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] pb-3">
              <p className="text-sm text-[var(--muted-foreground)]">
                <span aria-live="polite">
                  {data ? (total > 0 ? t("search.range", { from, to, total }) : "0") : ""}
                </span>
              </p>
              <div className="flex min-w-0 flex-col items-start gap-1 text-sm min-[768px]:flex-row min-[768px]:items-center min-[768px]:gap-2">
                <label
                  htmlFor="funder-sort"
                  className="whitespace-nowrap text-xs text-[var(--muted-foreground)]"
                >
                  {t("search.sortBy")}
                </label>
                <select
                  id="funder-sort"
                  title={t("search.sortHint")}
                  value={sort ?? "works"}
                  onChange={(event) => {
                    const nextSort = event.target.value as FunderSearchSort;
                    setParams({
                      sort: nextSort === "works" ? undefined : nextSort,
                      dir: undefined,
                    });
                  }}
                  className={SELECT_CLASS}
                >
                  <option value="works">{t("search.sortWorks", { inst: site.short })}</option>
                  <option value="name">{t("search.sortName")}</option>
                </select>
              </div>
            </div>

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
                      <div className="flex items-start justify-between gap-3">
                        <Link
                          href={`/${inst}/funders/${f.id}`}
                          className="inline-flex min-h-11 items-center font-medium text-[var(--foreground)] underline-offset-2 hover:text-[var(--primary-text)] hover:underline min-[1024px]:min-h-0"
                        >
                          {f.name ?? t("unnamedFunder", { id: f.id })}
                        </Link>
                        <span className="shrink-0 text-xs tabular-nums text-[var(--muted-foreground)]">
                          {f.n_ut_works.toLocaleString("en")} {t("instWorks", { inst: site.short })}
                        </span>
                      </div>
                      <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                        {countryName(f.country)}
                      </p>
                      <div className="mt-2">{policySummary(f)}</div>
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
                        <TableHead>{t("search.facets.policies")}</TableHead>
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
                          <TableCell>{policySummary(f)}</TableCell>
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
      </FilterLayout>
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
