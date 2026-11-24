"use client";

import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import { Compass, Search, SlidersHorizontal } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { notFound, usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { ActiveFiltersBar, type ActiveFilterChip } from "@/components/active-filters-bar";
import { DealBadge, FunderFitBadge, OaTypeBadge, QuartileBadge } from "@/components/badges";
import { FilterPanel } from "@/components/filter-panel";
import { GuideWizard } from "@/components/guide/guide-wizard";
import { rememberDirectoryUrl } from "@/components/journal/section-nav";
import { FunderPicker } from "@/components/search/funder-picker";
import { Pagination } from "@/components/search/pagination";
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
import { useDeals, useFacets, useInstitutionsDirectory, useJournals } from "@/hooks/use-api";
import { useInstitution } from "@/hooks/use-institution";
import { useSearchShortcut } from "@/hooks/use-search-shortcut";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { useYearRange } from "@/hooks/use-year-filter";
import {
  encodeNamePath,
  errorMessage,
  type JournalListItem,
  type JournalsSearchIn,
  type SortKey,
} from "@/lib/api";
import { displayPublisherName } from "@/lib/deal-links";
import { apcAmount, apcStatsText, formatApc, formatInt } from "@/lib/format";
import { useFunderPrefs } from "@/lib/funder-prefs";
import { COLUMN_SORTS, PUB_TYPE_LABELS, SEARCH_IN_OPTIONS, SORTS } from "@/lib/search-config";

const SEARCH_INPUT_ID = "journal-search";

export function JournalsLanding({ initialView = "browse" }: { initialView?: "browse" | "guide" }) {
  const t = useTranslations("home");
  const ts = useTranslations("search");
  const tc = useTranslations("common");
  const tg = useTranslations("guide");
  const inst = useInstitution();

  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const site = useSiteMeta();
  const institutions = useInstitutionsDirectory();
  const instShort = site.short || site.name;

  const spView = sp.get("view");
  const view: "browse" | "guide" =
    spView === "guide" || (initialView === "guide" && spView !== "browse") ? "guide" : "browse";

  const pubTypeLabel = React.useCallback(
    (code: string) => {
      const labelKey = PUB_TYPE_LABELS[code];
      return labelKey ? ts(labelKey) : code;
    },
    [ts],
  );

  const spQ = sp.get("q") ?? "";
  const sort = (sp.get("sort") ?? (spQ ? "relevance" : "institution_works")) as SortKey;
  const dirParam = sp.get("dir");
  const dir: "asc" | "desc" | null = dirParam === "asc" || dirParam === "desc" ? dirParam : null;
  const deal = sp.get("deal") ?? "";
  const dealIdRaw = sp.get("deal_id");
  const dealId = dealIdRaw && /^\d+$/.test(dealIdRaw) ? Number(dealIdRaw) : undefined;
  const oa = sp.get("oa");
  const doaj = sp.get("doaj");
  const quartile = sp.get("quartile") ?? "";
  const topic = sp.get("topic") ?? "";
  const publisher = sp.get("publisher") ?? "";
  const hasApc = sp.get("has_apc");
  const hasWorks = sp.get("has_works");
  const greenOa = sp.get("green_oa");
  const searchIn = (sp.get("search_in") ?? "all") as JournalsSearchIn;
  const oaTypes = (sp.get("oa_type") ?? "").split(",").filter(Boolean);
  const pubType = sp.get("pub_type") ?? "";
  const language = sp.get("language") ?? "";
  const semanticMode = sp.get("mode") === "semantic";
  const semantic = view === "browse" && semanticMode && spQ.trim().length >= 2;
  const [funder] = useFunderPrefs();
  const funderFit = sp.get("funder_fit") ?? "";
  const { year_from, year_to } = useYearRange();

  const [input, setInput] = React.useState(spQ);
  const [stack, setStack] = React.useState<string[]>([]);
  const cursor = sp.get("cursor") ?? undefined;

  useSearchShortcut(SEARCH_INPUT_ID);

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
  }, [filtersKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const update = React.useCallback(
    (patch: Record<string, string | undefined>) => {
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

  const moveTo = (nextStack: string[], nextCursor: string | undefined) => {
    setStack(nextStack);
    sessionStorage.setItem("jb-cursor-stack", JSON.stringify(nextStack));
    const next = new URLSearchParams(sp.toString());
    if (nextCursor) next.set("cursor", nextCursor);
    else next.delete("cursor");
    next.set("p", String(nextStack.length + 1));
    router.replace(`${pathname}?${next}`, { scroll: false });
  };

  const yearsKey = `${year_from ?? ""}-${year_to ?? ""}`;
  const prevYearsKey = React.useRef(yearsKey);
  React.useEffect(() => {
    if (prevYearsKey.current === yearsKey) return;
    prevYearsKey.current = yearsKey;
    if (cursor !== undefined || sp.get("p") !== null) update({ cursor: undefined, p: undefined });
  }, [yearsKey]); // eslint-disable-line react-hooks/exhaustive-deps

  React.useEffect(() => {
    setInput(spQ);
  }, [spQ]);
  React.useEffect(() => {
    if (view !== "browse") return;
    const timer = setTimeout(() => {
      if (input !== spQ) update({ q: input || undefined });
    }, 350);
    return () => clearTimeout(timer);
  }, [input, spQ, update, view]);

  const query = {
    q: spQ || undefined,
    search_in: searchIn === "all" ? undefined : searchIn,
    deal: (deal || undefined) as "covered" | "not_covered" | undefined,
    deal_id: dealId,
    oa: oa === null ? undefined : oa === "true",
    doaj: doaj === null ? undefined : doaj === "true",
    quartile: quartile || undefined,
    publisher: publisher || undefined,
    has_apc: hasApc === null ? undefined : hasApc === "true",
    has_works: hasWorks === null ? undefined : hasWorks === "true",
    green_oa: greenOa ?? undefined,
    funder: funder && !semanticMode ? funder.id : undefined,
    funder_fit: funderFit || undefined,
    topic: topic || undefined,
    oa_type: oaTypes.join(",") || undefined,
    pub_type: pubType || undefined,
    language: language || undefined,
    year_from,
    year_to,
    sort,
    dir: dir ?? undefined,
    cursor,
    limit: 40,
    include_facets: false,
  };
  const { data, isPending, isFetching, isError, error, refetch } = useJournals(query, semantic);
  const facetsQuery = useFacets(query, { enabled: view === "browse" && !semantic });
  const dealsQuery = useDeals("all", { enabled: dealId !== undefined });

  const facets = facetsQuery.isPending ? undefined : (facetsQuery.data?.facets ?? {});
  const facetsError = facetsQuery.isError;

  const filterSelection = {
    deal,
    oa,
    doaj,
    quartile,
    topic,
    publisher,
    hasApc,
    hasWorks,
    greenOa,
    funderFit,
    oaTypes,
    pubType,
    language,
  };

  const toggleFilter = (key: string, value: string) =>
    update({ [key]: sp.get(key) === value ? undefined : value });

  const toggleOaType = (value: string) => {
    const next = oaTypes.includes(value) ? oaTypes.filter((v) => v !== value) : [...oaTypes, value];
    update({ oa_type: next.join(",") || undefined });
  };
  const handleFacetToggle = (key: string, value: string) =>
    key === "oa_type" ? toggleOaType(value) : toggleFilter(key, value);

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

  const sortRef = React.useRef({ sort, dir, cycleSort, disabled: semanticMode });
  sortRef.current = { sort, dir, cycleSort, disabled: semanticMode };

  const columns = React.useMemo<ColumnDef<JournalListItem>[]>(
    () => [
      {
        accessorKey: "title",
        meta: { columnId: "title" },
        header: () => (
          <SortHead columnId="title" label={t("table.journal")} state={sortRef.current} />
        ),
        cell: (info) => (
          <div className="max-w-md">
            <Link
              href={`/${inst}/journals/${info.row.original.issn_l}`}
              onClick={(event) => event.stopPropagation()}
              className="font-medium text-[var(--foreground)] underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
            >
              {info.row.original.title ?? info.row.original.issn_l}
            </Link>
            {info.row.original.pub_type && info.row.original.pub_type !== "journal" && (
              <span
                className="ml-2 text-xs text-[var(--muted-foreground)]"
                title={t("table.pubTypeTooltip", { type: info.row.original.pub_type })}
              >
                {pubTypeLabel(info.row.original.pub_type)}
              </span>
            )}
            {info.row.original.is_in_doaj && (
              <span
                className="ml-2 cursor-help align-middle text-[10px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]"
                title={t("table.doajTooltip")}
              >
                DOAJ
              </span>
            )}
          </div>
        ),
      },
      {
        id: "publisher",
        meta: { columnId: "publisher" },
        header: () => (
          <SortHead columnId="publisher" label={t("table.publisher")} state={sortRef.current} />
        ),
        cell: (info) => {
          const row = info.row.original;
          const v = row.publisher_canonical ?? row.publisher_name;
          if (!v) return <span>—</span>;
          return (
            <Link
              href={`/${inst}/publisher/${encodeNamePath(v)}`}
              onClick={(event) => event.stopPropagation()}
              className="block max-w-40 truncate underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
              title={v}
            >
              {v}
            </Link>
          );
        },
      },
      {
        accessorKey: "deal_covered",
        header: () => <span className="sr-only">{t("table.dealCoverage")}</span>,
        cell: (info) => {
          const row = info.row.original;
          return <DealBadge covered={row.deal_covered} capped={row.deal_cap_reached} />;
        },
      },
      {
        accessorKey: "funder_fit",
        header: () => <span className="sr-only">{t("table.funderFit")}</span>,
        cell: (info) => {
          const fit = info.row.original.funder_fit;
          return <FunderFitBadge status={fit?.status ?? null} reasons={fit?.reasons ?? []} />;
        },
      },
      {
        accessorKey: "is_oa",
        header: () => <span className="sr-only">{t("table.oaType")}</span>,
        cell: (info) => {
          const row = info.row.original;
          return <OaTypeBadge oaType={row.oa_type} isOa={row.is_oa} />;
        },
      },
      {
        accessorKey: "works",
        meta: { columnId: "works" },
        header: () => (
          <SortHead
            columnId="works"
            label={t("table.works")}
            title={`${t("table.worksTitle", {
              inst: instShort,
              windowStart: site.windowStart === undefined ? "none" : String(site.windowStart),
              yearRange: year_from === undefined ? "none" : `${year_from} to ${year_to}`,
            })} ${t("table.sortHint")}`}
            state={sortRef.current}
          />
        ),
        cell: (info) => <span className="tabular-nums">{formatInt(info.getValue<number>())}</span>,
      },
      {
        accessorKey: "twoyr_mean_citedness",
        meta: { columnId: "citedness" },
        header: () => (
          <SortHead
            columnId="citedness"
            label={t("table.citedness")}
            title={`${t("table.citednessTooltip")} ${t("table.sortHint")}`}
            state={sortRef.current}
          />
        ),
        cell: (info) => {
          const v = info.getValue<number | null>();
          return v == null ? (
            <span className="text-[var(--muted-foreground)]">—</span>
          ) : (
            <span className="tabular-nums" title={t("table.citednessCellTitle")}>
              {v.toFixed(2)}
            </span>
          );
        },
      },
      {
        accessorKey: "quartile",
        meta: { columnId: "quartile" },
        header: () => (
          <SortHead
            columnId="quartile"
            label={t("table.quartile")}
            title={`${t("table.quartileTooltip")} ${t("table.sortHint")}`}
            state={sortRef.current}
          />
        ),
        cell: (info) => <QuartileBadge quartile={info.getValue<string | null>()} />,
      },
      {
        accessorKey: "apc_low",
        header: () => (
          <SortHead
            columnId="apc"
            label={t("table.apc")}
            title={`${t("table.apcTooltip")} ${t("table.sortHint")}`}
            state={sortRef.current}
          />
        ),
        cell: (info) => {
          const row = info.row.original;
          if (row.apc_source === "openalex" && row.apc_price != null) {
            return (
              <span className="tabular-nums" title={t("table.listPriceTitle")}>
                {apcAmount(row.apc_currency, row.apc_price)}
              </span>
            );
          }
          if (row.apc_source === "openapc" && row.apc_low != null) {
            const range =
              row.apc_low !== row.apc_high
                ? `${formatApc(row.apc_low)} to ${formatApc(row.apc_high ?? row.apc_low)}`
                : formatApc(row.apc_low);
            const detail = row.apc_stats ? apcStatsText(row.apc_stats) : "";
            return (
              <span className="inline-flex items-center gap-1 whitespace-nowrap">
                <span className="tabular-nums" title={detail || undefined}>
                  €{range}
                </span>
                {detail && (
                  <span
                    className="cursor-help rounded-full border border-[var(--muted-foreground)]/50 px-[5px] text-[10px] leading-[14px] text-[var(--muted-foreground)]"
                    title={t("table.openapcDetail", { detail })}
                    aria-label={t("table.openapcAria")}
                  >
                    ?
                  </span>
                )}
              </span>
            );
          }
          return <span className="text-[var(--muted-foreground)]">—</span>;
        },
      },
      {
        accessorKey: "primary_topic",
        meta: { columnId: "topic" },
        header: () => (
          <SortHead
            columnId="topic"
            label={t("table.topic")}
            title={`${t("table.topicTooltip")} ${t("table.sortHint")}`}
            state={sortRef.current}
          />
        ),
        cell: (info) => {
          const v = info.getValue<string | null>();
          if (!v) return <span className="text-[var(--muted-foreground)]">—</span>;
          return (
            <button
              type="button"
              className="block max-w-44 truncate text-left underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
              title={t("table.topicFilterTitle", { topic: v })}
              onClick={(event) => {
                event.stopPropagation();
                update({ topic: v });
              }}
            >
              {v}
            </button>
          );
        },
      },
    ],
    [site, instShort, inst, update, year_from, year_to, t, pubTypeLabel],
  );

  const rows = data?.items ?? [];
  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  const ariaSortFor = (meta: unknown): "ascending" | "descending" | undefined => {
    const columnId = (meta as { columnId?: string } | undefined)?.columnId;
    const spec = columnId ? COLUMN_SORTS[columnId] : undefined;
    if (!spec || semanticMode || sortRef.current.sort !== spec.key) return undefined;
    return (sortRef.current.dir ?? spec.natural) === "asc" ? "ascending" : "descending";
  };

  const pParam = parseInt(sp.get("p") ?? "", 10);
  const page = Number.isFinite(pParam) && pParam > 0 ? pParam : stack.length + 1;
  const pageStart = (page - 1) * (query.limit ?? 40) + 1;
  const hasNonQueryFilters = Boolean(
    deal ||
      dealId !== undefined ||
      oa !== null ||
      doaj !== null ||
      quartile ||
      topic ||
      publisher ||
      hasApc !== null ||
      hasWorks !== null ||
      greenOa !== null ||
      funderFit ||
      oaTypes.length > 0 ||
      Boolean(pubType) ||
      Boolean(language),
  );
  const hasFilters = Boolean(spQ) || hasNonQueryFilters;

  const clearFilters = () => {
    setInput("");
    update({
      q: undefined,
      search_in: undefined,
      deal: undefined,
      deal_id: undefined,
      oa: undefined,
      doaj: undefined,
      quartile: undefined,
      topic: undefined,
      publisher: undefined,
      has_apc: undefined,
      has_works: undefined,
      green_oa: undefined,
      funder_fit: undefined,
      oa_type: undefined,
      pub_type: undefined,
      language: undefined,
    });
  };

  React.useEffect(() => {
    if (view !== "browse") return;
    if (hasFilters) rememberDirectoryUrl("jb-last-search", `${pathname}?${sp.toString()}`);
  }, [hasFilters, pathname, sp, view]);

  if (institutions.isSuccess && !institutions.data?.some((i) => i.code === inst)) notFound();

  const matchedDeal =
    dealId !== undefined ? dealsQuery.data?.find((d) => d.id === dealId) : undefined;
  const dealChipLabel = matchedDeal
    ? displayPublisherName(matchedDeal.publisher_name) || `#${dealId}`
    : `#${dealId}`;

  const filterChips: ActiveFilterChip[] = [
    ...(spQ
      ? [
          {
            id: "q",
            label: t("toolbar.chipSearch", { value: spQ }),
            onRemove: () => {
              setInput("");
              update({ q: undefined });
            },
          },
        ]
      : []),
    ...(searchIn !== "all" && spQ
      ? [
          {
            id: "search_in",
            label: t("toolbar.chipScope", { value: pubTypeLabel(searchIn) }),
            onRemove: () => update({ search_in: undefined }),
          },
        ]
      : []),
    ...(dealId !== undefined
      ? [
          {
            id: "deal_id",
            label: t("toolbar.chipDealId", { name: dealChipLabel }),
            onRemove: () => update({ deal_id: undefined }),
          },
        ]
      : []),
    ...(deal
      ? [
          {
            id: "deal",
            label: `${tc("facets.groupDeal")}: ${
              deal === "covered" ? tc("facets.dealCovered") : tc("facets.dealNone")
            }`,
            onRemove: () => update({ deal: undefined }),
          },
        ]
      : []),
    ...(oa !== null
      ? [
          {
            id: "oa",
            label: `${tc("facets.groupOpenAccess")}: ${
              oa === "true" ? tc("facets.oaYes") : tc("facets.oaNo")
            }`,
            onRemove: () => update({ oa: undefined }),
          },
        ]
      : []),
    ...oaTypes.map((v) => ({
      id: `oa_type:${v}`,
      label: `${tc("facets.groupOaType")}: ${v}`,
      onRemove: () => toggleOaType(v),
    })),
    ...(doaj !== null
      ? [
          {
            id: "doaj",
            label: `${tc("facets.groupDoaj")}: ${
              doaj === "true" ? tc("facets.doajYes") : tc("facets.doajNo")
            }`,
            onRemove: () => update({ doaj: undefined }),
          },
        ]
      : []),
    ...(quartile
      ? [
          {
            id: "quartile",
            label: `${tc("facets.groupQuartile")}: ${quartile}`,
            onRemove: () => update({ quartile: undefined }),
          },
        ]
      : []),
    ...(pubType
      ? [
          {
            id: "pub_type",
            label: `${tc("facets.groupVenueType")}: ${pubTypeLabel(pubType)}`,
            onRemove: () => update({ pub_type: undefined }),
          },
        ]
      : []),
    ...(language
      ? [
          {
            id: "language",
            label: `${tc("facets.groupLanguage")}: ${
              ts.has(`languages.${language}`) ? ts(`languages.${language}`) : language
            }`,
            onRemove: () => update({ language: undefined }),
          },
        ]
      : []),
    ...(hasApc !== null
      ? [
          {
            id: "has_apc",
            label: `${tc("facets.groupApc")}: ${
              hasApc === "true" ? tc("facets.apcKnown") : tc("facets.apcUnknown")
            }`,
            onRemove: () => update({ has_apc: undefined }),
          },
        ]
      : []),
    ...(hasWorks !== null
      ? [
          {
            id: "has_works",
            label: `${tc("facets.groupInstWorks", { short: site.short })}: ${
              hasWorks === "true"
                ? tc("facets.instWorksYes", { short: site.short })
                : tc("facets.instWorksNo", { short: site.short })
            }`,
            onRemove: () => update({ has_works: undefined }),
          },
        ]
      : []),
    ...(greenOa
      ? [
          {
            id: "green_oa",
            label: `${tc("facets.groupGreenOa")}: ${greenOa}`,
            onRemove: () => update({ green_oa: undefined }),
          },
        ]
      : []),
    ...(funderFit
      ? [
          {
            id: "funder_fit",
            label: `${tc("facets.groupFunderFit")}: ${funderFit}`,
            onRemove: () => update({ funder_fit: undefined }),
          },
        ]
      : []),
    ...(topic
      ? [
          {
            id: "topic",
            label: `${tc("facets.groupTopic")}: ${topic}`,
            onRemove: () => update({ topic: undefined }),
          },
        ]
      : []),
    ...(publisher
      ? [
          {
            id: "publisher",
            label: `${tc("facets.groupPublisher")}: ${publisher}`,
            onRemove: () => update({ publisher: undefined }),
          },
        ]
      : []),
  ];

  const switchView = (target: "browse" | "guide") => {
    if (target === view) return;
    if (target === "guide") {
      if (pathname.endsWith("/guide")) return;
      update({ view: "guide" });
    } else if (pathname.endsWith("/guide")) {
      router.push(`/${inst}/`);
    } else {
      update({ view: undefined });
    }
  };

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <header className="mb-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="mb-2 text-3xl font-bold text-balance">
              {view === "guide" ? tg("header.heading") : t("hero.title")}
            </h1>
            <p className="max-w-2xl text-sm text-[var(--muted-foreground)]">
              {view === "guide"
                ? t("hero.modeGuideIntro")
                : t("hero.intro", { institution: site.name })}
            </p>
          </div>
          <div
            role="tablist"
            aria-label={t("hero.title")}
            className="flex shrink-0 overflow-hidden rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)]"
          >
            <button
              type="button"
              role="tab"
              aria-selected={view === "browse"}
              onClick={() => switchView("browse")}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] ${
                view === "browse"
                  ? "bg-[var(--secondary)] text-[var(--secondary-foreground)]"
                  : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              }`}
            >
              <SlidersHorizontal aria-hidden className="size-3.5" />
              {t("hero.modeBrowse")}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={view === "guide"}
              onClick={() => switchView("guide")}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] ${
                view === "guide"
                  ? "bg-[var(--secondary)] text-[var(--secondary-foreground)]"
                  : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              }`}
            >
              <Compass aria-hidden className="size-3.5" />
              {t("hero.modeGuide")}
            </button>
          </div>
        </div>

        {view === "browse" && (
          <div className="mt-5 space-y-2">
            <form
              className="flex max-w-3xl flex-wrap gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                update({ q: input || undefined });
              }}
            >
              <div className="relative w-full min-[560px]:w-auto min-[560px]:flex-1 min-[960px]:min-w-[24rem]">
                <Input
                  id={SEARCH_INPUT_ID}
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") event.currentTarget.blur();
                  }}
                  placeholder={
                    semanticMode ? t("search.placeholderSemantic") : t("search.placeholder")
                  }
                  aria-label={t("search.inputLabel")}
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
                  aria-label={t("search.scopeLabel")}
                  title={t("search.scopeTitle")}
                  value={searchIn}
                  onChange={(event) => update({ search_in: event.target.value })}
                  className="h-10 rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2"
                >
                  {SEARCH_IN_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {ts(o.labelKey)}
                    </option>
                  ))}
                </select>
              )}
              <label
                className="flex h-10 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-2.5 text-sm select-none"
                title={t("search.semanticTitle")}
              >
                <input
                  type="checkbox"
                  className="size-4 accent-[var(--primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2"
                  checked={sp.get("mode") === "semantic"}
                  onChange={(event) =>
                    update({ mode: event.target.checked ? "semantic" : undefined })
                  }
                />
                {t("search.semanticLabel")}
              </label>
              <Button type="submit" className="flex-1 min-[560px]:flex-none">
                <Search aria-hidden className="size-4" /> {t("search.submit")}
              </Button>
            </form>
            <div className="max-w-3xl">
              <FunderPicker />
            </div>
          </div>
        )}
      </header>

      {view === "guide" ? (
        <GuideWizard embedded />
      ) : (
        <>
          {/* Stacked filter card: the only filter UI below 960px. */}
          {!semanticMode && (
            <section className="mb-6 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 min-[960px]:hidden">
              <FilterPanel
                facets={facets}
                selection={filterSelection}
                onToggle={handleFacetToggle}
                variant="chips"
                error={facetsError}
                onRetry={() => facetsQuery.refetch()}
              />
            </section>
          )}

          <div className="flex flex-col gap-6 min-[960px]:grid min-[960px]:grid-cols-[15rem_minmax(0,1fr)] min-[960px]:items-start min-[1280px]:grid-cols-[18rem_minmax(0,1fr)] min-[1280px]:gap-8">
            {/* Wide-screen sidebar: sticky, scrolls on its own when long. */}
            {!semanticMode && (
              <aside className="sticky top-20 hidden max-h-[calc(100vh-6rem)] self-start overflow-y-auto rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 min-[960px]:block">
                <FilterPanel
                  facets={facets}
                  selection={filterSelection}
                  onToggle={handleFacetToggle}
                  variant="rows"
                  error={facetsError}
                  onRetry={() => facetsQuery.refetch()}
                />
              </aside>
            )}

            <div className={semanticMode ? "min-w-0 min-[960px]:col-span-2" : "min-w-0"}>
              <ActiveFiltersBar
                chips={filterChips}
                onClearAll={clearFilters}
                ariaLabel={tc("activeFilters.label")}
                clearLabel={tc("activeFilters.clearAll")}
                removeAriaPrefix={tc("activeFilters.remove")}
              />

              {/* Sort and reset belong with the results they act on. */}
              <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
                {!semanticMode && (
                  <>
                    <label htmlFor="sort" className="whitespace-nowrap">
                      {t("toolbar.sortBy")}
                    </label>
                    <select
                      id="sort"
                      title={t("toolbar.sortTitle")}
                      value={sort}
                      onChange={(event) => update({ sort: event.target.value, dir: undefined })}
                      className="h-9 rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2"
                    >
                      {SORTS.map((s) => (
                        <option key={s.value} value={s.value}>
                          {s.value === "institution_works"
                            ? t("toolbar.sortInstitutionWorks", { inst: instShort })
                            : ts(s.labelKey)}
                        </option>
                      ))}
                    </select>
                    {hasFilters && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-[var(--muted-foreground)]"
                        title={t("toolbar.resetTitle")}
                        onClick={clearFilters}
                      >
                        {hasNonQueryFilters ? t("toolbar.resetFilters") : t("toolbar.resetSearch")}
                      </Button>
                    )}
                  </>
                )}
                {semanticMode && (
                  <p className="text-[var(--muted-foreground)]">
                    {semantic
                      ? t("toolbar.semanticStatusActive")
                      : t("toolbar.semanticStatusPending")}
                  </p>
                )}
              </div>

              <Card>
                <CardContent className="pt-6">
                  <Pagination data={data} isFetching={isFetching} stack={stack} moveTo={moveTo} />

                  {isError ? (
                    <div className="py-10 text-center">
                      <p className="text-[var(--destructive)]">{errorMessage(tc, error)}</p>
                      <Button
                        variant="outline"
                        size="sm"
                        className="mt-3"
                        onClick={() => refetch()}
                      >
                        {t("error.retry")}
                      </Button>
                      {(cursor || sp.get("p")) && (
                        <Button
                          variant="outline"
                          size="sm"
                          className="mt-3 ml-2"
                          onClick={() => update({})}
                        >
                          {t("error.backToPage1")}
                        </Button>
                      )}
                    </div>
                  ) : isPending ? (
                    <ListSkeletonRows rows={8} />
                  ) : rows.length === 0 ? (
                    <div className="py-10 text-center text-[var(--muted-foreground)]">
                      {spQ && !hasNonQueryFilters ? (
                        <>{t("empty.query", { query: spQ })}</>
                      ) : (
                        <>{hasNonQueryFilters ? t("empty.filters") : t("empty.plain")}</>
                      )}
                      {spQ && !semanticMode && (
                        <div className="mt-3">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => update({ mode: "semantic" })}
                          >
                            {t("empty.trySemantic")}
                          </Button>
                        </div>
                      )}
                      {spQ && !hasNonQueryFilters && (
                        <p className="mt-4 text-sm">
                          {t("empty.crossHintLead")}{" "}
                          <Link
                            href={`/${inst}/author?q=${encodeURIComponent(spQ)}`}
                            className="underline underline-offset-2 hover:text-[var(--foreground)]"
                          >
                            {t("empty.crossAuthors", { query: spQ })}
                          </Link>
                          {" · "}
                          <Link
                            href={`/${inst}/funders?q=${encodeURIComponent(spQ)}`}
                            className="underline underline-offset-2 hover:text-[var(--foreground)]"
                          >
                            {t("empty.crossFunders", { query: spQ })}
                          </Link>
                        </p>
                      )}
                      {hasNonQueryFilters && (
                        <div className="mt-3">
                          <Button variant="outline" size="sm" onClick={clearFilters}>
                            {t("empty.clearFilters")}
                          </Button>
                        </div>
                      )}
                    </div>
                  ) : (
                    <>
                      {data.fuzzy && spQ && (
                        <p className="mb-3 text-sm text-[var(--muted-foreground)]" role="status">
                          {t("table.fuzzy", { query: spQ })}
                        </p>
                      )}
                      <ul
                        className={isFetching ? "opacity-60 md:hidden" : "md:hidden"}
                        aria-label={t("table.listAria")}
                      >
                        {rows.map((row) => {
                          const pub = row.publisher_canonical ?? row.publisher_name;
                          const topicVal = row.primary_topic;
                          return (
                            <li
                              key={row.issn_l}
                              className="relative border-b border-[var(--border)] py-3 first:pt-0 last:border-0 last:pb-0"
                            >
                              <Link
                                href={`/${inst}/journals/${row.issn_l}`}
                                className="font-medium text-[var(--foreground)] underline-offset-2 after:absolute after:inset-0 after:content-[''] hover:text-[var(--primary-text)] hover:underline"
                              >
                                {row.title ?? row.issn_l}
                              </Link>
                              <div className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                                {pub ? (
                                  <Link
                                    href={`/${inst}/publisher/${encodeNamePath(pub)}`}
                                    className="relative z-10 underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                                  >
                                    {pub}
                                  </Link>
                                ) : (
                                  t("table.unknownPublisher")
                                )}
                                {row.pub_type && row.pub_type !== "journal" && (
                                  <>
                                    {" · "}
                                    {pubTypeLabel(row.pub_type)}
                                  </>
                                )}
                                {topicVal && (
                                  <>
                                    {" · "}
                                    <button
                                      type="button"
                                      className="relative z-10 text-left underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                                      title={t("table.topicFilterTitle", { topic: topicVal })}
                                      onClick={(event) => {
                                        event.stopPropagation();
                                        update({ topic: topicVal });
                                      }}
                                    >
                                      {topicVal}
                                    </button>
                                  </>
                                )}
                              </div>
                              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                                <DealBadge
                                  covered={row.deal_covered}
                                  capped={row.deal_cap_reached}
                                />
                                <FunderFitBadge
                                  status={row.funder_fit?.status ?? null}
                                  reasons={row.funder_fit?.reasons ?? []}
                                />
                                <OaTypeBadge oaType={row.oa_type} isOa={row.is_oa} />
                                <QuartileBadge quartile={row.quartile ?? null} />
                              </div>
                              <div className="mt-1 text-xs tabular-nums text-[var(--muted-foreground)]">
                                {t("table.listWorks", {
                                  count: row.works.toLocaleString("en"),
                                  inst: site.short,
                                })}
                                {row.apc_source === "openalex" && row.apc_price != null && (
                                  <>
                                    {" · "}
                                    {t("table.listApcOpenalex", {
                                      amount: apcAmount(row.apc_currency, row.apc_price),
                                    })}
                                  </>
                                )}
                                {row.apc_source === "openapc" && row.apc_low != null && (
                                  <>
                                    {" · "}
                                    {t("table.listApcOpenapc", {
                                      range:
                                        row.apc_low !== row.apc_high
                                          ? `${formatApc(row.apc_low)} to ${formatApc(
                                              row.apc_high ?? row.apc_low,
                                            )}`
                                          : formatApc(row.apc_low),
                                    })}
                                  </>
                                )}
                              </div>
                            </li>
                          );
                        })}
                      </ul>
                      <div
                        className={isFetching ? "hidden opacity-60 md:block" : "hidden md:block"}
                      >
                        <Table>
                          <caption className="sr-only">{t("table.resultsCaption")}</caption>
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
                              const href = `/${inst}/journals/${row.original.issn_l}`;
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
                                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
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
                    <span>
                      {data && rows.length > 0
                        ? t("footer.showing", {
                            start: String(pageStart),
                            end: String(pageStart + rows.length - 1),
                            total: data.total.toLocaleString("en"),
                          })
                        : ""}
                    </span>
                    <SourceNote
                      source={t("footer.sources")}
                      url="https://doaj.org"
                      howBuilt={tc("sourceNote.explain.journals")}
                      codes={[
                        "stats-window",
                        "openalex-coverage",
                        "institution-affiliation",
                        "doaj-canon",
                        "jct-coverage",
                        "issn-mapping",
                        ...(funder ? ["jisc-policy-currency"] : []),
                      ]}
                    />
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
