"use client";

import { ExternalLink, Github } from "lucide-react";
import { useState } from "react";

import { SourceNote } from "@/components/source-note";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { useFreshness, useLimitations } from "@/hooks/use-api";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { errorMessage } from "@/lib/api";

type SourceInfo = {
  name: string;
  url: string;
  role: string;
  table?: string;
  harvest?: string;
};

const SOURCES: SourceInfo[] = [
  {
    name: "Pure",
    // Real portal URL comes from settings at render time (site.researchPortalUrl).
    url: "",
    role: "Institution publication counts per journal — the primary figure; OpenAlex is its cross-check.",
    table: "institution_works_stats",
  },
  {
    name: "OpenAlex",
    url: "https://openalex.org",
    role: "Journal records, open access status, and citation metrics; cross-checks Pure's publication counts.",
    table: "journals",
  },
  {
    name: "DOAJ",
    url: "https://doaj.org",
    role: "Authoritative registry for gold and diamond open access: whether a journal charges an APC decides gold vs diamond, and its journal URL is the canon homepage. Harvested from DOAJ's full journal CSV.",
    table: "doaj",
  },
  {
    name: "OpenAIRE",
    url: "https://openaire.eu",
    role: "Alternative records and open access links for individual institutional works.",
    harvest: "openaire",
  },
  {
    name: "Crossref",
    url: "https://www.crossref.org",
    role: "DOI metadata used to match institutional works to their journal.",
    harvest: "crossref",
  },
  {
    name: "openaccess.nl",
    url: "https://www.openaccess.nl/en/publishing/publisher-deals",
    role: "Deal terms, conditions, and workflow descriptions.",
    harvest: "openaccess.nl",
  },
  {
    name: "JCT",
    url: "https://journalcheckertool.org/transformative-agreements/",
    role: "Transformative agreement journal lists — one input to the deal register.",
    harvest: "jct",
  },
  {
    name: "OpenAPC",
    url: "https://github.com/OpenAPC/openapc-de",
    role: "APC price aggregates and per-article cost evidence.",
    table: "apc_evidence",
  },
  {
    name: "Jisc Open Policy Finder",
    url: "https://openpolicyfinder.jisc.ac.uk",
    role: "Green open access (self-archiving) policies: which version of an article the publisher allows archived where, under which licence and embargo.",
    harvest: "jisc_opf",
  },
  {
    name: "Scimago",
    url: "https://www.scimagojr.com",
    role: "SJR indicator, best quartile, and SJR h-index.",
    table: "scimagojr_metrics",
  },
];

function fmt(value: unknown) {
  if (value === null || value === undefined) return "unknown";
  if (typeof value === "string" && /^\d{4}/.test(value))
    return new Date(value).toLocaleDateString("en", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  return String(value);
}

function ExternalIcon() {
  return <ExternalLink aria-hidden className="size-3" />;
}

export default function AboutPage() {
  const site = useSiteMeta();
  const freshnessQuery = useFreshness();
  const limitationsQuery = useLimitations();
  const freshness = freshnessQuery.data;
  const limitations = limitationsQuery.data;

  const tables = (freshness?.tables ?? {}) as Record<string, unknown>;
  // Latest first; collapsed to the recent tail so the public page stays a
  // summary, not a pipeline log.
  const [showAllRuns, setShowAllRuns] = useState(false);
  const harvestRows = [...(freshness?.harvests ?? [])].sort((a, b) =>
    (b.finished_at ?? "").localeCompare(a.finished_at ?? ""),
  );
  const shownHarvests = showAllRuns ? harvestRows : harvestRows.slice(0, 10);

  function stamp(info: SourceInfo) {
    if (info.table) return tables[info.table];
    const runs = (freshness?.harvests ?? [])
      .filter((h) => h.source === info.harvest && h.finished_at)
      .map((h) => h.finished_at)
      .sort();
    return runs.at(-1) ?? null;
  }

  return (
    <div className="mx-auto max-w-screen-2xl space-y-10 px-4 py-10">
      <header>
        <h1 className="mb-2 text-3xl font-bold">About this browser</h1>
        <div className="max-w-prose space-y-3">
          <p>
            A journal browser for <strong>{freshness?.institution ?? site.name}</strong>
            {freshness?.ror && (
              <>
                {" "}
                (
                <a
                  href={
                    /^https?:\/\//.test(freshness.ror)
                      ? freshness.ror
                      : `https://ror.org/${freshness.ror}`
                  }
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[var(--primary-text)] hover:underline"
                >
                  ROR {freshness.ror.replace(/^https?:\/\/ror\.org\//, "")}
                </a>
                )
              </>
            )}
            : find where to publish, what a deal covers, and how much it costs.
          </p>
          <p className="text-[var(--muted-foreground)]">
            It is a modernisation of the{" "}
            <a
              href="https://library.wur.nl/WebQuery/utbrowser?q=*"
              target="_blank"
              rel="noopener noreferrer"
              className="text-[var(--primary-text)] underline-offset-2 hover:underline"
            >
              WUR journal browser
            </a>
            , rebuilt on fully open data and released as open source — you can self-host it. For
            open access policy questions, use the library links under Contact below.
          </p>
        </div>
      </header>
      {(freshness?.degraded?.length ?? 0) > 0 && (
        <div
          role="alert"
          className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm"
        >
          <p className="font-semibold text-amber-600 dark:text-amber-400">
            Some data sources are currently degraded
          </p>
          <ul className="mt-2 space-y-1 text-[var(--muted-foreground)]">
            {(freshness?.degraded ?? []).map((d) => (
              <li key={d.source}>
                <strong>{d.source}</strong>: {d.detail} (since{" "}
                {new Date(d.since).toLocaleString("en", {
                  dateStyle: "medium",
                  timeStyle: "short",
                })}
                )
              </li>
            ))}
          </ul>
        </div>
      )}

      {(freshnessQuery.isError || limitationsQuery.isError) && (
        <p aria-live="polite" className="text-sm text-[var(--destructive)]">
          {errorMessage(freshnessQuery.isError ? freshnessQuery.error : limitationsQuery.error)}{" "}
          <button
            type="button"
            onClick={() => {
              freshnessQuery.refetch();
              limitationsQuery.refetch();
            }}
            className="underline underline-offset-2 hover:no-underline"
          >
            Retry
          </button>
        </p>
      )}

      <section>
        <h2 className="mb-3 text-xl font-bold">Data sources</h2>
        <Card>
          <CardContent className="pt-6">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <caption className="sr-only">
                  Data sources, what each provides, and when its data was last refreshed
                </caption>
                <thead>
                  <tr className="text-left text-xs text-[var(--muted-foreground)]">
                    <th scope="col" className="py-1 pr-4 font-medium">
                      Source
                    </th>
                    <th scope="col" className="py-1 pr-4 font-medium">
                      Provides
                    </th>
                    <th scope="col" className="py-1 font-medium">
                      Latest data
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {SOURCES.map((info) => (
                    <tr key={info.name} className="border-t border-[var(--border)] align-top">
                      <td className="py-2 pr-4 whitespace-nowrap">
                        <a
                          href={info.url || site.researchPortalUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-0.5 font-semibold text-[var(--primary-text)] hover:underline"
                        >
                          {info.name} <ExternalIcon />
                        </a>
                      </td>
                      <td className="py-2 pr-4 text-[var(--muted-foreground)]">{info.role}</td>
                      <td className="py-2 text-xs whitespace-nowrap tabular-nums text-[var(--muted-foreground)]">
                        {freshnessQuery.isPending ? "…" : fmt(stamp(info))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-4 max-w-prose text-xs text-[var(--muted-foreground)]">
              Harvest jobs run when the library refreshes the data; per-run status is listed below.
              The deal register is maintained by hand, so a re-ingest can never overwrite reviewed
              deal information. Publication statistics cover works published in{" "}
              {site.windowStart === undefined ? "the institution's data window" : site.windowStart}{" "}
              or later, and the search lists journals with more than 3 publications in that window.
            </p>
          </CardContent>
        </Card>
      </section>

      {freshness && freshness.harvests.length > 0 && (
        <section>
          <h2 className="mb-3 text-xl font-bold">Harvest runs</h2>
          <Card>
            <CardContent className="overflow-x-auto pt-6">
              <table className="w-full text-xs">
                <caption className="sr-only">
                  Most recent harvest runs per source, entity, and filter set, with status and
                  finish time
                </caption>
                <thead>
                  <tr className="text-left text-[var(--muted-foreground)]">
                    <th className="py-1 pr-3 font-medium">Source</th>
                    <th className="py-1 pr-3 font-medium">Entity</th>
                    <th className="py-1 pr-3 font-medium">Filter set</th>
                    <th className="py-1 pr-3 font-medium">Status</th>
                    <th className="py-1 font-medium">Finished</th>
                  </tr>
                </thead>
                <tbody>
                  {shownHarvests.map((h, i) => {
                    const url = SOURCES.find(
                      (s) => s.name.toLowerCase() === h.source.toLowerCase(),
                    )?.url;
                    return (
                      <tr
                        key={`${h.source}-${h.entity_type}-${i}`}
                        className="border-t border-[var(--border)]"
                      >
                        <td className="py-1.5 pr-3">
                          {url ? (
                            <a
                              href={url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-[var(--primary-text)] hover:underline"
                            >
                              {h.source}
                            </a>
                          ) : (
                            h.source
                          )}
                        </td>
                        <td className="py-1.5 pr-3">{h.entity_type}</td>
                        <td className="py-1.5 pr-3">
                          <Badge variant={h.status === "completed" ? "muted" : "outline"}>
                            {h.status ?? "—"}
                          </Badge>
                        </td>
                        <td className="py-1.5 tabular-nums">{fmt(h.finished_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="mt-3 text-xs text-[var(--muted-foreground)]">
                Rows for deal sources are historical. The deal register has been maintained by hand
                since October 2026.
                {harvestRows.length > shownHarvests.length && (
                  <>
                    {" "}
                    <button
                      type="button"
                      onClick={() => setShowAllRuns(true)}
                      className="font-medium text-[var(--primary-text)] underline underline-offset-2 hover:no-underline"
                    >
                      Show all {harvestRows.length} runs
                    </button>
                  </>
                )}
              </p>
            </CardContent>
          </Card>
        </section>
      )}

      <section>
        <h2 className="mb-3 text-xl font-bold">Licences</h2>
        <ul className="grid max-w-prose gap-x-10 gap-y-2 text-sm sm:grid-cols-2">
          <li>
            The code is open source under the Apache-2.0 licence and available on{" "}
            <a
              href="https://github.com/utsmok/journal-browser"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-[var(--primary-text)] underline-offset-2 hover:underline"
            >
              <Github aria-hidden className="size-4" />
              GitHub
            </a>
            .
          </li>
          <li>
            <a
              href="https://openpolicyfinder.jisc.ac.uk"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-0.5 text-[var(--primary-text)] underline-offset-2 hover:underline"
            >
              Jisc Open Policy Finder <ExternalIcon />
            </a>{" "}
            policy text is shown verbatim; it is Jisc content under CC BY-NC-ND 4.0.
          </li>
        </ul>
      </section>

      <section>
        <h2 className="mb-1 text-xl font-bold">Data limitations</h2>
        <p className="mb-4 max-w-prose text-sm text-[var(--muted-foreground)]">
          Every number shows its source. These are the caveats behind the data, and each entry links
          to the data provider.
        </p>
        {(limitations ?? []).length === 0 && !limitationsQuery.isPending ? (
          <p className="text-sm text-[var(--muted-foreground)]">No limitations registered.</p>
        ) : (
          <ul className="grid gap-x-10 gap-y-5 md:grid-cols-2">
            {(limitations ?? []).map((l) => (
              <li key={l.code} className="text-sm">
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                  <span className="font-mono text-xs font-semibold">{l.code}</span>
                  <Badge
                    variant={l.severity === "warning" ? "default" : "muted"}
                    className="uppercase"
                  >
                    {l.severity}
                  </Badge>
                  <span className="text-xs text-[var(--muted-foreground)]">
                    {l.source} · {l.scope}
                  </span>
                </div>
                <p className="mt-1">
                  {l.hint}
                  {l.url && (
                    <a
                      href={l.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="ml-2 inline-flex items-center gap-0.5 text-[var(--primary-text)] hover:underline"
                    >
                      More info <ExternalIcon />
                    </a>
                  )}
                </p>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-4">
          <SourceNote
            source="Limitation registry"
            codes={["stats-window", "corpus-cutoff", "pure-canon-primary"]}
          />
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-xl font-bold">Contact</h2>
        <div className="max-w-prose space-y-2 text-sm">
          <p className="text-[var(--muted-foreground)]">
            Questions about open access publishing at {site.name}? The library can help.
          </p>
          <ul className="flex flex-wrap gap-x-6 gap-y-1">
            <li>
              <a
                href={site.libraryUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-0.5 text-[var(--primary-text)] hover:underline"
              >
                {site.name} Library <ExternalIcon />
              </a>
            </li>
            <li>
              <a
                href={site.oaGuideUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-0.5 text-[var(--primary-text)] hover:underline"
              >
                Open Access publishing guide <ExternalIcon />
              </a>
            </li>
            <li>
              <a
                href={`mailto:${site.supportEmail}`}
                className="text-[var(--primary-text)] hover:underline"
              >
                {site.supportEmail}
              </a>
            </li>
          </ul>
          {site.adminContact && (
            <p className="text-[var(--muted-foreground)]">
              Technical questions about this browser? Contact the admin,{" "}
              <a
                href={`mailto:${site.adminContact}`}
                className="text-[var(--primary-text)] underline-offset-2 hover:underline"
              >
                {site.adminContact}
              </a>
              .
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
