"use client";

import dynamic from "next/dynamic";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import * as React from "react";

import { ActiveFiltersBar } from "@/components/collaborations/active-filters";
import { CollaborationFacets } from "@/components/collaborations/facets";
import { CollaborationOverview } from "@/components/collaborations/overview-strip";
import { Pager } from "@/components/collaborations/pager";
import { PartnerTable, readSorting } from "@/components/collaborations/partner-list";
import { CollaborationSources } from "@/components/collaborations/sources";
import { EMPTY_COLLAB_FILTERS, writeCollabParams } from "@/components/collaborations/collab-params";
import { useCollabParams } from "@/components/collaborations/use-collab-params";
import { FilterLayout } from "@/components/filter-layout";
import { GapCsvButton } from "@/components/gap-csv-button";
import { MobileDisclosure } from "@/components/mobile-disclosure";
import { ListSkeletonRows } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useCollaborationMap, useCollaborations } from "@/hooks/use-api";
import { useDebounced } from "@/hooks/use-debounced";
import { useInstitution } from "@/hooks/use-institution";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { useYearRange } from "@/hooks/use-year-filter";
import {
  COLLAB_PAGE_SIZE,
  collaborationCsvHref,
  collaborationTrendCsvHref,
  errorMessage,
  type CollabMultiKey,
  type CollaborationLead,
  type CollaborationSize,
} from "@/lib/api";

const PartnerMap = dynamic(
  () => import("@/components/collaborations/partner-map").then((m) => m.PartnerMap),
  {
    ssr: false,
    loading: () => <div aria-hidden className="h-[22rem] sm:h-[26rem]" />,
  },
);

const selectClass =
  "h-11 min-w-0 max-w-full rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-2 text-xs text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] min-[960px]:h-8";

/** Multi-valued params that the facet sheet and sidebar set. */
const FACET_KEYS: CollabMultiKey[] = [
  "type",
  "country",
  "faculty",
  "oa_status",
  "topic",
  "funder",
  "project",
  "source",
];

function PartnersPageInner() {
  const t = useTranslations("collaborations");
  const tc = useTranslations("common");
  const inst = useInstitution();
  const site = useSiteMeta();
  const router = useRouter();
  const { year_from, year_to } = useYearRange();
  const [filters, update] = useCollabParams();

  // Keep search input synced with URL `q` so refresh & Back nav preserve it.
  const [input, setInput] = React.useState(filters.q ?? "");
  React.useEffect(() => {
    setInput(filters.q ?? "");
  }, [filters.q]);
  const debouncedInput = useDebounced(input.trim(), 250);
  React.useEffect(() => {
    if (debouncedInput !== (filters.q ?? "")) {
      update({ q: debouncedInput || undefined });
    }
  }, [debouncedInput, filters.q, update]);

  const [offset, setOffset] = React.useState(0);

  // Respect the global year header directly (no hidden 2020 override).
  const params = React.useMemo(
    () => ({ ...filters, year_from, year_to }),
    [filters, year_from, year_to],
  );

  React.useEffect(() => {
    setOffset(0);
  }, [params]);

  const list = useCollaborations(params, offset);
  const map = useCollaborationMap(params);
  const sorting = readSorting(filters);

  const from = list.data?.year_from ?? year_from ?? site.windowStart ?? 2010;
  const to = list.data?.year_to ?? year_to ?? new Date().getFullYear();
  const listQuery = writeCollabParams(filters);
  const query = listQuery ? `?${listQuery}` : "";
  const shown = list.data?.items.length ?? 0;
  const total = list.data?.total_partners ?? 0;

  // Auto-fit map when country or search filters narrow the geographic footprint.
  const autoFitKey = React.useMemo(() => {
    const parts = [
      filters.q ?? "",
      (filters.country ?? []).join(","),
      (filters.faculty ?? []).join(","),
    ].filter(Boolean);
    return parts.length ? parts.join("|") : undefined;
  }, [filters.q, filters.country, filters.faculty]);

  const toggleMapType = React.useCallback(
    (typeValue: string) => {
      const next = new Set(filters.type ?? []);
      if (!next.delete(typeValue)) next.add(typeValue);
      update({ type: next.size ? [...next] : undefined });
    },
    [filters.type, update],
  );

  const size: CollaborationSize = filters.size ?? "standard";
  const rollup = filters.rollup !== false;
  const lead: CollaborationLead = filters.lead ?? "all";
  const minWorks = filters.min_works ?? 1;

  const searchBox = (
    <Input
      type="search"
      value={input}
      onChange={(e) => setInput(e.target.value)}
      placeholder={t("search.placeholder")}
      aria-label={t("search.aria")}
    />
  );
  // Selections made in the facet sheet; the mode bar has its own controls.
  const facetCount = FACET_KEYS.reduce((n, key) => n + (filters[key]?.length ?? 0), 0);

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <h1 className="text-3xl font-bold text-balance">{t("title")}</h1>
          <p className="mt-1 max-w-prose text-sm text-[var(--muted-foreground)]">
            {t("intro", { inst: site.short })}
          </p>
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">
            {t("years.range", { from: String(from), to: String(to) })}
          </p>
        </div>
        <GapCsvButton href={collaborationCsvHref(inst, params)} />
      </header>

      {/* Analytical mode bar: mega-collab size, conservative roll-up, lead, min works, deals */}
      <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2.5 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] px-3.5 py-2.5 text-xs">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <span className="font-medium text-[var(--muted-foreground)]">{t("modes.sizeLabel")}</span>
          <div
            role="group"
            aria-label={t("modes.sizeLabel")}
            className="flex max-w-full flex-wrap overflow-hidden rounded-[var(--radius)] border border-[var(--input)]"
          >
            {(
              [
                {
                  value: "standard",
                  label: t("modes.sizeStandard"),
                  title: t("modes.sizeStandardHint"),
                },
                { value: "small", label: t("modes.sizeSmall"), title: t("modes.sizeSmallHint") },
                { value: "all", label: t("modes.sizeAll"), title: t("modes.sizeAllHint") },
              ] as const
            ).map((opt) => (
              <button
                key={opt.value}
                type="button"
                aria-pressed={size === opt.value}
                title={opt.title}
                onClick={() => update({ size: opt.value === "standard" ? undefined : opt.value })}
                className={`min-h-11 px-2.5 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] min-[1024px]:min-h-0 min-[1024px]:py-1 min-[1024px]:text-xs ${
                  size === opt.value
                    ? "bg-[var(--secondary)] font-medium text-[var(--secondary-foreground)]"
                    : "bg-[var(--card)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        <label
          className="inline-flex min-h-11 cursor-pointer items-center gap-1.5 select-none min-[1024px]:min-h-0"
          title={t("modes.rollupHint")}
        >
          <input
            type="checkbox"
            checked={rollup}
            onChange={(e) => update({ rollup: e.target.checked ? undefined : false })}
            className="size-3.5 accent-[var(--primary)]"
          />
          <span className="font-medium text-[var(--foreground)]">{t("modes.rollupOn")}</span>
        </label>

        <div className="flex min-h-11 min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 min-[960px]:min-h-0">
          <label htmlFor="collab-lead" className="text-[var(--muted-foreground)]">
            {t("modes.leadLabel")}
          </label>
          <select
            id="collab-lead"
            value={lead}
            onChange={(e) =>
              update({
                lead: e.target.value === "all" ? undefined : (e.target.value as CollaborationLead),
              })
            }
            className={selectClass}
          >
            <option value="all">{t("modes.leadAll")}</option>
            <option value="home">{t("modes.leadHome", { inst: site.short })}</option>
            <option value="partner">{t("modes.leadPartner")}</option>
          </select>
        </div>

        <div className="flex min-h-11 min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 min-[960px]:min-h-0">
          <label htmlFor="collab-min-works" className="text-[var(--muted-foreground)]">
            {t("modes.minWorksLabel")}
          </label>
          <select
            id="collab-min-works"
            value={String(minWorks)}
            onChange={(e) => {
              const v = Number.parseInt(e.target.value, 10);
              update({ min_works: v > 1 ? v : undefined });
            }}
            className={selectClass}
          >
            <option value="1">{t("modes.minWorksAny")}</option>
            <option value="5">{t("modes.minWorks5")}</option>
            <option value="20">{t("modes.minWorks20")}</option>
          </select>
        </div>

        <label className="inline-flex min-h-11 cursor-pointer items-center gap-1.5 select-none min-[1024px]:min-h-0">
          <input
            type="checkbox"
            checked={Boolean(filters.shares_deals)}
            onChange={(e) => update({ shares_deals: e.target.checked ? true : undefined })}
            className="size-3.5 accent-[var(--primary)]"
          />
          <span className="text-[var(--foreground)]">{t("modes.sharesDeals")}</span>
        </label>
      </div>

      <FilterLayout
        className="mt-5"
        filters={
          <CollaborationFacets
            params={filters}
            facets={list.data?.facets}
            onChange={update}
            variant="rows"
            loading={list.isPending}
          />
        }
        aboveFilters={searchBox}
        activeCount={facetCount}
        onReset={() => {
          setInput("");
          update(EMPTY_COLLAB_FILTERS);
        }}
      >
        <ActiveFiltersBar
          params={filters}
          facets={list.data?.facets}
          onChange={update}
          onResetAll={() => {
            setInput("");
            update(EMPTY_COLLAB_FILTERS);
          }}
        />

        <MobileDisclosure label={t("overview.toggle")} className="mb-6" lazy>
          {list.data && (
            <CollaborationOverview
              data={list.data}
              trendCsvHref={collaborationTrendCsvHref(inst, params)}
            />
          )}

          <section aria-labelledby="partners-map-title" className="mt-6">
            <h2 id="partners-map-title" className="text-base font-semibold">
              {t("map.title")}
            </h2>
            <div className="mt-2 overflow-hidden rounded-[var(--radius)] border border-[var(--border)] bg-[var(--muted)]">
              {map.isError ? (
                <p
                  role="alert"
                  className="flex h-[22rem] items-center justify-center px-6 text-center text-sm text-[var(--destructive)] sm:h-[26rem]"
                >
                  {errorMessage(tc, map.error)}
                </p>
              ) : (
                <PartnerMap
                  points={map.data?.items ?? []}
                  description={t("map.description")}
                  failedText={t("map.failed")}
                  retryText={t("search.retry")}
                  activeTypes={filters.type ?? []}
                  onToggleType={toggleMapType}
                  autoFitKey={autoFitKey}
                  onSelect={(ror) =>
                    router.push(`/${inst}/collaborations/${encodeURIComponent(ror)}${query}`)
                  }
                />
              )}
            </div>
            <p className="mt-2 text-xs text-[var(--muted-foreground)]">
              {t("map.caption")}{" "}
              {(map.data?.unmapped ?? 0) > 0 &&
                t("map.unmapped", { count: map.data?.unmapped ?? 0 })}
            </p>
          </section>
        </MobileDisclosure>

        <section aria-labelledby="partners-table-title">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 id="partners-table-title" className="text-base font-semibold">
              {t("table.title")}
            </h2>
            {list.data && (
              <p className="text-xs text-[var(--muted-foreground)]">
                {t("summary.bySource", {
                  openalex: list.data.works_by_source.openalex ?? 0,
                  openaire: list.data.works_by_source.openaire ?? 0,
                })}
              </p>
            )}
          </div>
          <div className="mt-3">
            {list.isPending && <ListSkeletonRows rows={8} />}
            {list.isError && (
              <div>
                <p role="alert" className="text-[var(--destructive)]">
                  {errorMessage(tc, list.error)}
                </p>
                <Button variant="outline" size="sm" className="mt-2" onClick={() => list.refetch()}>
                  {t("search.retry")}
                </Button>
              </div>
            )}
            {list.data && (
              <Card>
                <CardContent className="pt-6">
                  <PartnerTable
                    items={list.data.items}
                    sorting={sorting}
                    onSort={(next) => update({ sort: next.sort, dir: next.dir })}
                    inst={inst}
                    query={query}
                    pending={list.isPlaceholderData}
                  />
                  {total > COLLAB_PAGE_SIZE && (
                    <Pager
                      offset={offset}
                      shown={shown}
                      total={total}
                      pageSize={COLLAB_PAGE_SIZE}
                      onOffset={setOffset}
                    />
                  )}
                </CardContent>
              </Card>
            )}
          </div>
        </section>

        <div className="mt-6">
          <CollaborationSources />
        </div>
      </FilterLayout>
    </div>
  );
}

export default function CollaborationsPage() {
  return (
    <React.Suspense fallback={null}>
      <PartnersPageInner />
    </React.Suspense>
  );
}
