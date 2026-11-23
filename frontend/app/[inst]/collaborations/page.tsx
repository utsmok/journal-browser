"use client";

import { X } from "lucide-react";
import dynamic from "next/dynamic";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import * as React from "react";

import { CollaborationFacets } from "@/components/collaborations/facets";
import { Pager } from "@/components/collaborations/pager";
import { PartnerTable, readSorting } from "@/components/collaborations/partner-list";
import { CollaborationSources } from "@/components/collaborations/sources";
import { useCollabParams, writeCollabParams } from "@/components/collaborations/use-collab-params";
import { GapCsvButton } from "@/components/gap-csv-button";
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
  COLLAB_DEFAULT_YEARS,
  COLLAB_MULTI_KEYS,
  COLLAB_PAGE_SIZE,
  collaborationCsvHref,
  errorMessage,
} from "@/lib/api";

/** The map and its library load in the browser only; the spacer keeps the
 * page from jumping while they arrive. */
const PartnerMap = dynamic(
  () => import("@/components/collaborations/partner-map").then((m) => m.PartnerMap),
  {
    ssr: false,
    loading: () => <div aria-hidden className="h-[22rem] sm:h-[26rem]" />,
  },
);

function PartnersPageInner() {
  const t = useTranslations("collaborations");
  const tc = useTranslations("common");
  const inst = useInstitution();
  const site = useSiteMeta();
  const router = useRouter();
  const { year_from, year_to } = useYearRange();
  const [filters, update] = useCollabParams();

  // The name search stays in page state, as it does in the other directories.
  const [input, setInput] = React.useState("");
  const q = useDebounced(input.trim(), 250);
  const [offset, setOffset] = React.useState(0);

  // Without a range in the header's year control, partners start in 2020.
  const params = React.useMemo(
    () =>
      year_from === undefined
        ? { ...filters, ...COLLAB_DEFAULT_YEARS, q: q || undefined }
        : { ...filters, year_from, year_to, q: q || undefined },
    [filters, year_from, year_to, q],
  );

  // A new filter set starts at the first page.
  React.useEffect(() => {
    setOffset(0);
  }, [params]);

  const list = useCollaborations(params, offset);
  const map = useCollaborationMap(params);
  const sorting = readSorting(filters);

  const from = params.year_from ?? COLLAB_DEFAULT_YEARS.year_from;
  const to = params.year_to ?? COLLAB_DEFAULT_YEARS.year_to;
  const listQuery = writeCollabParams(filters);
  const query = listQuery ? `?${listQuery}` : "";
  const filtered =
    input !== "" ||
    filters.level !== undefined ||
    COLLAB_MULTI_KEYS.some((key) => filters[key]?.length);
  const shown = list.data?.items.length ?? 0;
  const total = list.data?.total_partners ?? 0;

  const search = (
    <div className="space-y-2">
      <Input
        type="search"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        placeholder={t("search.placeholder")}
        aria-label={t("search.aria")}
      />
      {filtered && (
        <Button
          variant="ghost"
          size="sm"
          className="-ml-3"
          onClick={() => {
            setInput("");
            update({
              type: undefined,
              country: undefined,
              faculty: undefined,
              funder: undefined,
              project: undefined,
              source: undefined,
              level: undefined,
            });
          }}
        >
          <X aria-hidden className="size-3.5" /> {t("search.clear")}
        </Button>
      )}
    </div>
  );

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <h1 className="text-3xl font-bold text-balance">{t("title")}</h1>
          <p className="mt-1 max-w-prose text-sm text-[var(--muted-foreground)]">
            {t("intro", { inst: site.short })}
          </p>
          <p className="mt-1 text-sm text-[var(--muted-foreground)]">
            {t(year_from === undefined ? "years.default" : "years.selected", { from, to })}
          </p>
        </div>
        <GapCsvButton href={collaborationCsvHref(inst, params)} />
      </header>

      {/* Stacked filters: the only filter UI below 960px. */}
      <section className="mt-6 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 min-[960px]:hidden">
        {search}
        <div className="mt-4">
          <CollaborationFacets
            params={filters}
            facets={list.data?.facets}
            onChange={update}
            variant="chips"
            loading={list.isPending}
          />
        </div>
      </section>

      <div className="mt-6 flex flex-col gap-6 min-[960px]:flex-row min-[960px]:items-start">
        {/* Wide-screen sidebar: sticky, scrolls on its own when long. */}
        <aside className="sticky top-20 hidden max-h-[calc(100vh-6rem)] w-72 shrink-0 overflow-y-auto rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 min-[960px]:block">
          {search}
          <div className="mt-4">
            <CollaborationFacets
              params={filters}
              facets={list.data?.facets}
              onChange={update}
              variant="rows"
              loading={list.isPending}
            />
          </div>
        </aside>

        <div className="min-w-0 flex-1 space-y-8">
          <section aria-labelledby="partners-map-title">
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
                  pointLabel={(works) => t("map.point", { works })}
                  failedText={t("map.failed")}
                  retryText={t("search.retry")}
                  onSelect={(ror) =>
                    router.push(`/${inst}/collaborations/${encodeURIComponent(ror)}${query}`)
                  }
                />
              )}
            </div>
            <p className="mt-2 text-sm text-[var(--muted-foreground)]">
              {t("map.caption")}{" "}
              {(map.data?.unmapped ?? 0) > 0 &&
                t("map.unmapped", { count: map.data?.unmapped ?? 0 })}
            </p>
          </section>

          <section aria-labelledby="partners-table-title">
            <h2 id="partners-table-title" className="text-base font-semibold">
              {t("table.title")}
            </h2>
            {/* Counts of the whole filter set, not only of the page shown. */}
            {list.data && (
              <div className="mt-2 text-sm">
                <p>
                  {t("summary.line", {
                    partners: list.data.total_partners,
                    withPartner: list.data.works_with_partner,
                    works: list.data.total_works.toLocaleString("en"),
                    inst: site.short,
                    from,
                    to,
                  })}
                </p>
                <p className="mt-1 text-[var(--muted-foreground)]">
                  {t("summary.bySource", {
                    openalex: list.data.works_by_source.openalex ?? 0,
                    openaire: list.data.works_by_source.openaire ?? 0,
                  })}
                </p>
              </div>
            )}
            <div className="mt-3">
              {list.isPending && <ListSkeletonRows rows={8} />}
              {list.isError && (
                <div>
                  <p role="alert" className="text-[var(--destructive)]">
                    {errorMessage(tc, list.error)}
                  </p>
                  <Button
                    variant="outline"
                    size="sm"
                    className="mt-2"
                    onClick={() => list.refetch()}
                  >
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

          <CollaborationSources />
        </div>
      </div>
    </div>
  );
}

/** useSearchParams needs a Suspense boundary during prerender. */
export default function CollaborationsPage() {
  return (
    <React.Suspense fallback={null}>
      <PartnersPageInner />
    </React.Suspense>
  );
}
