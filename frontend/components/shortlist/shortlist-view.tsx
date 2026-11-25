"use client";

import { Bookmark, Download, Link2, Printer, Trash2 } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import * as React from "react";

import {
  ShortlistTable,
  shortlistCsv,
  useShortlistLabels,
  type ShortlistRow,
} from "@/components/shortlist/shortlist-table";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useJournalBatch } from "@/hooks/use-api";
import { useInstitution } from "@/hooks/use-institution";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { useYearRange } from "@/hooks/use-year-filter";
import { errorMessage } from "@/lib/api";
import {
  clearShortlist,
  downloadCsv,
  removeJournal,
  saveJournals,
  shareHref,
  shortlistCsvFilename,
  useShortlist,
} from "@/lib/shortlist";

const NOTICE =
  "mb-3 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-sm";

/**
 * The shortlist page. Without a share link it shows the journals saved in
 * this browser, with remove, clear, CSV, share-link and print actions. With
 * `?j=` it shows the shared list and a button that saves it here.
 */
export function ShortlistView({
  shared,
  sharedIssnLs,
}: {
  /** True when the URL carries a `j` parameter, even an empty or invalid one. */
  shared: boolean;
  sharedIssnLs: string[];
}) {
  const t = useTranslations("shortlist");
  const tc = useTranslations("common");
  const inst = useInstitution();
  const site = useSiteMeta();
  const { year_from, year_to } = useYearRange();
  const labels = useShortlistLabels();
  const entries = useShortlist(inst);

  // The store reads localStorage, so the server and the first client render
  // see an empty list. Wait for that render before calling the list empty.
  const [hydrated, setHydrated] = React.useState(false);
  React.useEffect(() => setHydrated(true), []);

  const [copyResult, setCopyResult] = React.useState<{ copied: boolean; url: string } | null>(null);
  const [justSaved, setJustSaved] = React.useState(false);

  const issnLs = React.useMemo(
    () => (shared ? sharedIssnLs : entries.map((entry) => entry.issnL)),
    [shared, sharedIssnLs, entries],
  );
  const query = useJournalBatch(issnLs, { year_from, year_to });
  const savedByIssn = React.useMemo(
    () => new Map(entries.map((entry) => [entry.issnL, entry])),
    [entries],
  );

  const rows = React.useMemo<ShortlistRow[]>(() => {
    const items = new Map((query.data?.items ?? []).map((item) => [item.issn_l, item]));
    const missing = new Set(query.data?.missing ?? []);
    return issnLs.flatMap((issnL) => {
      const item = items.get(issnL);
      // Until the API answers for an ISSN-L there is no row to show.
      if (!item && !missing.has(issnL)) return [];
      const entry = shared ? undefined : savedByIssn.get(issnL);
      return [
        {
          issnL,
          savedTitle: entry?.title ?? issnL,
          addedAt: entry?.addedAt ?? null,
          item: item ?? null,
        },
      ];
    });
  }, [issnLs, query.data, savedByIssn, shared]);

  const listLength = shared ? sharedIssnLs.length : entries.length;
  const unavailable = rows.filter((row) => row.item === null).length;
  const toAdd = sharedIssnLs.filter((issnL) => !savedByIssn.has(issnL)).length;

  const copyLink = async () => {
    const url = `${window.location.origin}${shareHref(inst, issnLs)}`;
    try {
      await navigator.clipboard.writeText(url);
      setCopyResult({ copied: true, url });
    } catch {
      // The clipboard needs a secure context; then the link is shown to copy by hand.
      setCopyResult({ copied: false, url });
    }
  };

  const saveShared = () => {
    saveJournals(
      inst,
      rows.map((row) => ({ issnL: row.issnL, title: row.item?.title ?? row.savedTitle })),
    );
    setJustSaved(true);
  };

  const loading = (
    <p role="status" className="py-10 text-sm text-[var(--muted-foreground)]">
      {t("states.loading")}
    </p>
  );

  let body: React.ReactNode;
  if (!hydrated) {
    body = loading;
  } else if (listLength === 0) {
    body = <EmptyState shared={shared} inst={inst} />;
  } else if (!query.data) {
    body = query.isError ? (
      <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-6">
        <p className="text-[var(--destructive)]">{errorMessage(tc, query.error)}</p>
        <Button variant="outline" size="sm" className="mt-3" onClick={() => void query.refetch()}>
          {t("states.retry")}
        </Button>
      </div>
    ) : (
      loading
    );
  } else {
    body = (
      <>
        <div className="shortlist-actions mb-4 flex flex-wrap items-center gap-2">
          {shared ? (
            <>
              {toAdd > 0 && (
                <Button size="sm" className="gap-1.5" onClick={saveShared}>
                  <Bookmark aria-hidden className="size-3.5" />
                  {entries.length === 0 ? t("shared.save") : t("shared.add", { count: toAdd })}
                </Button>
              )}
              {entries.length > 0 && (
                <Link
                  href={`/${inst}/shortlist`}
                  className={buttonVariants({ variant: "outline", size: "sm" })}
                >
                  {t("shared.goToMine")}
                </Link>
              )}
            </>
          ) : (
            <>
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5"
                disabled={rows.length === 0}
                onClick={() => downloadCsv(shortlistCsvFilename(inst), shortlistCsv(rows, labels))}
              >
                <Download aria-hidden className="size-3.5" />
                {t("actions.exportCsv")}
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5"
                onClick={() => void copyLink()}
              >
                <Link2 aria-hidden className="size-3.5" />
                {t("actions.copyLink")}
              </Button>
            </>
          )}
          <Button variant="outline" size="sm" className="gap-1.5" onClick={() => window.print()}>
            <Printer aria-hidden className="size-3.5" />
            {t("actions.print")}
          </Button>
          {!shared && (
            <Button
              variant="ghost"
              size="sm"
              className="ml-auto gap-1.5 text-[var(--destructive)] hover:bg-transparent hover:text-[var(--destructive)] hover:underline"
              onClick={() => {
                if (window.confirm(t("confirmClear", { count: entries.length })))
                  clearShortlist(inst);
              }}
            >
              <Trash2 aria-hidden className="size-3.5" />
              {t("actions.clear")}
            </Button>
          )}
        </div>
        {shared && toAdd === 0 && (
          <p role="status" className={NOTICE}>
            {justSaved
              ? t("shared.savedStatus")
              : t("shared.allSaved", { count: sharedIssnLs.length })}
          </p>
        )}
        {copyResult && (
          <div role="status" className={`${NOTICE} shortlist-screen`}>
            <p>{copyResult.copied ? t("actions.linkCopied") : t("actions.linkCopyFailed")}</p>
            {!copyResult.copied && (
              <input
                readOnly
                value={copyResult.url}
                onFocus={(event) => event.currentTarget.select()}
                aria-label={t("actions.copyLink")}
                className="mt-1 w-full rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] px-2 py-1 font-mono text-xs"
              />
            )}
          </div>
        )}
        {query.isError && (
          <p
            role="alert"
            className="mb-3 flex flex-wrap items-center gap-2 text-sm text-[var(--destructive)]"
          >
            {errorMessage(tc, query.error)}
            <Button variant="outline" size="sm" onClick={() => void query.refetch()}>
              {t("states.retry")}
            </Button>
          </p>
        )}
        {unavailable > 0 && (
          <p className={`${NOTICE} text-[var(--muted-foreground)]`}>
            {t("unavailableNotice", { count: unavailable, institution: site.name })}
          </p>
        )}
        <ShortlistTable
          rows={rows}
          inst={inst}
          onRemove={shared ? undefined : (row) => removeJournal(inst, row.issnL)}
        />
      </>
    );
  }

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-6">
      <header className="mb-4">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">
          {shared ? t("shared.heading") : t("own.heading")}
        </h1>
        <p className="mt-1 max-w-3xl text-sm text-[var(--muted-foreground)]">
          {shared ? t("shared.intro") : t("own.intro", { institution: site.name })}
        </p>
        {listLength > 0 && (
          <p className="mt-2 text-sm font-medium">{t("count", { count: listLength })}</p>
        )}
      </header>
      {body}
    </div>
  );
}

function EmptyState({ shared, inst }: { shared: boolean; inst: string }) {
  const t = useTranslations("shortlist");
  return (
    <Card>
      <CardContent className="flex flex-col items-start gap-3 py-10 sm:items-center sm:text-center">
        <Bookmark aria-hidden className="size-8 text-[var(--muted-foreground)]" />
        <h2 className="text-lg font-semibold">{shared ? t("shared.empty") : t("empty.title")}</h2>
        {!shared && (
          <p className="max-w-md text-sm text-[var(--muted-foreground)]">{t("empty.body")}</p>
        )}
        <Link
          href={shared ? `/${inst}/shortlist` : `/${inst}`}
          className={buttonVariants({ size: "sm" })}
        >
          {shared ? t("shared.goToMine") : t("empty.browse")}
        </Link>
      </CardContent>
    </Card>
  );
}
