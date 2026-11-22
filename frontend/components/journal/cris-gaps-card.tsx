"use client";

import { useTranslations } from "next-intl";

import { CollapsibleCard } from "@/components/collapsible-card";
import { GapCsvButton } from "@/components/gap-csv-button";
import { GapEntryList } from "@/components/gap-entries";
import { ProcessLink } from "@/components/source-note";
import { useYearRange, yearQuery } from "@/hooks/use-year-filter";
import { entriesTotal, toGapEntries } from "@/lib/gap-entries";
import type { OpenalexOnly } from "@/components/journal/shared";

/** OpenAlex works attributed to this journal that match no Pure record:
 * candidates missing from the research information system. */
export function CrisGapsCard({
  openalexOnly,
  inst,
  issnL,
}: {
  openalexOnly: OpenalexOnly;
  inst: string;
  issnL: string;
}) {
  const t = useTranslations("journals");
  const { year_from, year_to } = useYearRange();
  const { total } = openalexOnly;
  const entries = toGapEntries(openalexOnly.items);
  const shownTotal = entriesTotal(openalexOnly);
  return (
    <CollapsibleCard
      id="cris-gaps"
      title={t("crisGaps.title")}
      description={
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <p className="text-sm text-[var(--muted-foreground)]">
            {t("crisGaps.description", { count: total })} {t("crisGaps.matchNote")}
            {shownTotal > entries.length
              ? ` ${t("crisGaps.showingRecent", { count: entries.length })}`
              : ""}
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <ProcessLink anchor="how-authors" />
            {total > 0 && (
              <GapCsvButton
                href={`/api/v1/${inst}/journals/${issnL}/openalex-only.csv${yearQuery("?", year_from, year_to)}`}
              />
            )}
          </div>
        </div>
      }
      contentClassName="text-sm"
    >
      {total === 0 ? (
        <p className="text-[var(--muted-foreground)]">{t("crisGaps.empty")}</p>
      ) : (
        <GapEntryList
          entries={entries}
          inst={inst}
          untitledLabel={t("publications.untitled")}
          showUtAuthors
        />
      )}
    </CollapsibleCard>
  );
}
