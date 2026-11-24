"use client";

import { BookOpen, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { CardPager } from "@/components/card-pager";
import { CollapsibleCard } from "@/components/collapsible-card";
import { GapCsvButton } from "@/components/gap-csv-button";
import { GapEntryList } from "@/components/gap-entries";
import { SourceNote } from "@/components/source-note";
import { Button } from "@/components/ui/button";
import { useJournalCrisGaps, useOrgUnitCrisGaps, usePublisherCrisGaps } from "@/hooks/use-api";
import { useInstitution } from "@/hooks/use-institution";
import { useYearRange, yearQuery } from "@/hooks/use-year-filter";
import {
  encodeNamePath,
  errorMessage,
  type OrgUnitLevel,
  type PublisherPartsFilter,
} from "@/lib/api";
import { entriesTotal, toGapEntries } from "@/lib/gap-entries";

const GAP_PAGE_SIZE = 10;

type CrisGapsTarget =
  | { kind: "publisher"; name: string }
  | { kind: "orgunit"; level: OrgUnitLevel; name: string }
  | { kind: "journal"; issnL: string };

/**
 * Shared lazy-loaded CRIS-gap section ("Works not matched in Pure") for
 * Publisher, OrgUnit, and Journal detail views.
 *
 * Starts collapsed (`defaultOpen={false}`) and only fetches `/cris-gaps` once
 * expanded. Work-type filter buttons stay visible even on empty slices, show
 * exact per-kind counts, disable zero-count slices, and display an inline
 * spinner while loading or switching filters.
 */
export function CrisGapsSection({
  target,
  available,
  initialTotal,
  initialPartsCounts,
}: {
  target: CrisGapsTarget;
  available: boolean;
  initialTotal?: number;
  initialPartsCounts?: Record<string, number>;
}) {
  const tc = useTranslations("common");
  const tp = useTranslations("publishers");
  const to = useTranslations("orgunits");
  const tj = useTranslations("journals");
  const inst = useInstitution();
  const { year_from, year_to } = useYearRange();

  const [expanded, setExpanded] = React.useState(false);
  const [parts, setParts] = React.useState<PublisherPartsFilter | undefined>(undefined);
  const [page, setPage] = React.useState(1);

  const targetKey =
    target.kind === "publisher"
      ? `p:${target.name}`
      : target.kind === "orgunit"
        ? `u:${target.level}:${target.name}`
        : `j:${target.issnL}`;

  React.useEffect(() => {
    setParts(undefined);
    setPage(1);
  }, [targetKey, year_from, year_to]);

  React.useEffect(() => {
    setPage(1);
  }, [parts]);

  const pubQuery = usePublisherCrisGaps(
    target.kind === "publisher" ? target.name : undefined,
    { year_from, year_to },
    parts,
    available && expanded && target.kind === "publisher",
  );
  const unitQuery = useOrgUnitCrisGaps(
    target.kind === "orgunit" ? target.level : undefined,
    target.kind === "orgunit" ? target.name : undefined,
    { year_from, year_to },
    parts,
    available && expanded && target.kind === "orgunit",
  );
  const journalQuery = useJournalCrisGaps(
    target.kind === "journal" ? target.issnL : undefined,
    { year_from, year_to },
    parts,
    available && expanded && target.kind === "journal",
  );

  const activeQuery =
    target.kind === "publisher" ? pubQuery : target.kind === "orgunit" ? unitQuery : journalQuery;

  if (!available) return null;

  const data = activeQuery.data;
  const openalexOnly = data?.openalex_only;
  const chapters = data?.chapter_rollup;
  const partsCounts =
    (openalexOnly as { parts_counts?: Record<string, number> } | undefined)?.parts_counts ??
    (initialPartsCounts && Object.keys(initialPartsCounts).length > 0
      ? initialPartsCounts
      : undefined);
  const unfilteredTotal = partsCounts?.all ?? openalexOnly?.total ?? initialTotal ?? 0;
  const total = data ? (openalexOnly?.total ?? 0) : (initialTotal ?? 0);
  const headerCount = data ? total : initialTotal;
  const entries = openalexOnly ? toGapEntries(openalexOnly.items) : [];
  const shownTotal = openalexOnly ? entriesTotal(openalexOnly) : 0;
  const pages = Math.max(1, Math.ceil(entries.length / GAP_PAGE_SIZE));
  const safePage = Math.min(page, pages);
  const pagedEntries = entries.slice((safePage - 1) * GAP_PAGE_SIZE, safePage * GAP_PAGE_SIZE);

  const yearQs = yearQuery("?", year_from, year_to);
  const csvHref =
    target.kind === "publisher"
      ? `/api/v1/${inst}/publishers/${encodeNamePath(target.name)}/openalex-only.csv${yearQs}${parts ? `${yearQs ? "&" : "?"}parts=${parts}` : ""}`
      : target.kind === "journal"
        ? `/api/v1/${inst}/journals/${encodeURIComponent(target.issnL)}/openalex-only.csv${yearQs}`
        : null;

  const title =
    target.kind === "publisher"
      ? tp("detail.crisGaps")
      : target.kind === "orgunit"
        ? to("detail.crisGaps.title")
        : tj("crisGaps.title");

  const untitledLabel =
    target.kind === "publisher"
      ? tp("detail.untitled")
      : target.kind === "orgunit"
        ? to("detail.crisGaps.untitled")
        : tj("publications.untitled");

  const emptyLabel =
    target.kind === "publisher"
      ? tp("detail.crisGapsEmpty")
      : target.kind === "orgunit"
        ? to("detail.crisGaps.empty")
        : tj("crisGaps.empty");

  const showFilterBar = unfilteredTotal > 0 || parts !== undefined;

  const filterOptions: {
    value: PublisherPartsFilter | undefined;
    countKey: string;
    label: string;
  }[] = [
    { value: undefined, countKey: "all", label: tc("crisGaps.all") },
    { value: "chapter", countKey: "chapter", label: tc("crisGaps.chapters") },
    { value: "part", countKey: "part", label: tc("crisGaps.parts") },
    { value: "standalone", countKey: "standalone", label: tc("crisGaps.standalone") },
  ];

  const introText = !expanded
    ? initialTotal === 0
      ? emptyLabel
      : initialTotal !== undefined && initialTotal > 0
        ? tc("crisGaps.loadHintCount", { count: initialTotal })
        : tc("crisGaps.loadHint")
    : activeQuery.isPending && !data
      ? tc("crisGaps.loading")
      : target.kind === "publisher"
        ? tp("detail.crisGapsIntro", { count: total })
        : target.kind === "orgunit"
          ? to("detail.crisGaps.description", { count: total })
          : `${tj("crisGaps.description", { count: total })} ${tj("crisGaps.matchNote")}`;

  return (
    <CollapsibleCard
      id="cris-gaps"
      title={title}
      count={headerCount}
      defaultOpen={false}
      compact
      onOpenChange={setExpanded}
      description={
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <p className="text-xs text-[var(--muted-foreground)]">
            {introText}
            {data &&
              shownTotal > entries.length &&
              ` ${
                target.kind === "publisher"
                  ? tp("detail.crisGapsShowing", { count: entries.length })
                  : target.kind === "orgunit"
                    ? to("detail.crisGaps.showing", { count: entries.length })
                    : tj("crisGaps.showingRecent", { count: entries.length })
              }`}
          </p>
          {expanded && (showFilterBar || activeQuery.isFetching || csvHref) && (
            <div className="flex flex-wrap items-center gap-2">
              {activeQuery.isFetching && (
                <span
                  className="inline-flex items-center gap-1.5 text-xs text-[var(--muted-foreground)]"
                  aria-live="polite"
                >
                  <Loader2 aria-hidden className="size-3.5 animate-spin" />
                  {tc("crisGaps.filtering")}
                </span>
              )}
              {showFilterBar && (
                <div
                  role="group"
                  aria-label={tc("crisGaps.filterLabel")}
                  className="flex overflow-hidden rounded-[var(--radius)] border border-[var(--input)]"
                >
                  {filterOptions.map((opt) => {
                    const selected = parts === opt.value;
                    const kindCount = partsCounts?.[opt.countKey];
                    const disabled = kindCount !== undefined && kindCount === 0 && !selected;
                    return (
                      <Button
                        key={opt.value ?? "all"}
                        variant={selected ? "secondary" : "ghost"}
                        size="sm"
                        className="h-7 rounded-none px-2.5 text-xs tabular-nums"
                        aria-pressed={selected}
                        disabled={disabled}
                        onClick={() => setParts(opt.value)}
                      >
                        {opt.label}
                        {kindCount !== undefined && (
                          <span className="ml-1 text-[11px] opacity-75">
                            ({kindCount.toLocaleString("en")})
                          </span>
                        )}
                      </Button>
                    );
                  })}
                </div>
              )}
              {csvHref && total > 0 && <GapCsvButton href={csvHref} />}
            </div>
          )}
        </div>
      }
      contentClassName="space-y-3 text-sm"
    >
      {expanded && activeQuery.isPending && !data ? (
        <div className="space-y-2 py-1" aria-hidden>
          {[88, 72, 80, 64].map((w, i) => (
            <div
              key={i}
              className="h-4 animate-pulse rounded bg-[var(--muted)]"
              style={{ width: `${w}%` }}
            />
          ))}
        </div>
      ) : activeQuery.isError ? (
        <p role="alert" className="text-sm text-[var(--destructive)]">
          {errorMessage(tc, activeQuery.error)}
        </p>
      ) : total === 0 ? (
        <p className="text-[var(--muted-foreground)]">{emptyLabel}</p>
      ) : (
        <div className={activeQuery.isFetching ? "opacity-60 transition-opacity" : undefined}>
          <GapEntryList
            entries={pagedEntries}
            inst={inst}
            untitledLabel={untitledLabel}
            showJournalLinks={target.kind === "publisher"}
            showUtAuthors={target.kind !== "orgunit"}
          />
          {pages > 1 && (
            <div className="mt-3">
              <CardPager
                page={safePage}
                pages={pages}
                total={entries.length}
                onPage={setPage}
                isFetching={activeQuery.isFetching}
                label={tc("crisGaps.pagerLabel")}
              />
            </div>
          )}
        </div>
      )}

      {chapters && chapters.chapters_total > 0 && (
        <details className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--muted)]/25 px-3 py-2">
          <summary className="flex cursor-pointer list-none items-center gap-2 text-xs font-semibold text-[var(--foreground)]">
            <BookOpen aria-hidden className="size-3.5 text-[var(--muted-foreground)]" />
            <span>{tp("detail.bookChapters")}</span>
            <span className="font-normal text-[var(--muted-foreground)]">
              —{" "}
              {tp("detail.bookChaptersIntro", {
                chapters: chapters.chapters_total,
                books: chapters.books_total,
              })}
            </span>
          </summary>
          <ul className="mt-2 divide-y divide-[var(--border)] text-xs">
            {chapters.books.map((b) => (
              <li key={b.parent_id ?? b.name} className="py-1.5 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-medium">{b.name}</span>
                  <span className="tabular-nums text-[var(--muted-foreground)]">
                    {tp("detail.chapterCount", { count: b.chapters })}
                  </span>
                </div>
                {b.sample.length > 0 && (
                  <p className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
                    {b.sample.join(" · ")}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}

      <div className="border-t border-[var(--border)] pt-2.5">
        <SourceNote
          source={tc("sourceNote.howListLabel")}
          howBuilt={tc("sourceNote.explain.crisGaps")}
        />
      </div>
    </CollapsibleCard>
  );
}
