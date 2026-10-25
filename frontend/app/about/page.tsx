"use client";

import { ExternalLink, Github } from "lucide-react";

import { SourceNote } from "@/components/source-note";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
    role: "Institution publication counts per journal. Pure is the primary figure, and the OpenAlex count below is its cross-check.",
    table: "institution_works_stats",
  },
  {
    name: "OpenAlex",
    url: "https://openalex.org",
    role: "Journal records, open access status, citation metrics, and the cross-check on institution publication counts.",
    table: "journals",
  },
  {
    name: "OpenAIRE",
    url: "https://openaire.eu",
    role: "Alternative records and open access links for individual UT works.",
    harvest: "openaire",
  },
  {
    name: "Crossref",
    url: "https://www.crossref.org",
    role: "DOI metadata used to match UT works to their journal.",
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
    role: "Transformative agreement journal lists, one input used to build the register.",
    harvest: "jct",
  },
  {
    name: "OpenAPC",
    url: "https://github.com/OpenAPC/openapc-de",
    role: "APC price aggregates and per-article cost evidence.",
    table: "apc_evidence",
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

export default function AboutPage() {
  const site = useSiteMeta();
  const freshnessQuery = useFreshness();
  const limitationsQuery = useLimitations();
  const freshness = freshnessQuery.data;
  const limitations = limitationsQuery.data;

  const tables = (freshness?.tables ?? {}) as Record<string, unknown>;

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
        <p className="max-w-2xl text-[var(--muted-foreground)]">
          A journal browser for{" "}
          <strong>{freshness?.institution ?? site.name}</strong>
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
      </header>

      {(freshnessQuery.isError || limitationsQuery.isError) && (
        <p aria-live="polite" className="text-sm text-[var(--destructive)]">
          {errorMessage(
            freshnessQuery.isError ? freshnessQuery.error : limitationsQuery.error,
          )}{" "}
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
        <Card>
          <CardContent className="space-y-3 pt-6 text-sm">
            <p>
              This browser is a modernisation of the{" "}
              <a
                href="https://library.wur.nl/WebQuery/utbrowser?q=*"
                target="_blank"
                rel="noopener noreferrer"
                className="text-[var(--primary-text)] underline-offset-2 hover:underline"
              >
                WUR journal browser
              </a>
              , rebuilt on fully open data, released as open source, and easy to
              self-host.
            </p>
            <p>
              The code is open source under the Apache-2.0 license and available
              on{" "}
              <a
                href="https://github.com/utsmok/journal-browser"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-[var(--primary-text)] underline-offset-2 hover:underline"
              >
                <Github aria-hidden className="size-4" />
                GitHub
              </a>
              {site.adminContact && (
                <>
                  . Technical questions? Contact the admin,{" "}
                  <a
                    href={`mailto:${site.adminContact}`}
                    className="text-[var(--primary-text)] underline-offset-2 hover:underline"
                  >
                    {site.adminContact}
                  </a>
                </>
              )}{" "}
              . For open access policy questions, see the library links in the
              footer.
            </p>
          </CardContent>
        </Card>
      </section>

      <section>
        <h2 className="mb-3 text-xl font-bold">Data sources</h2>
        <Card>
          <CardContent className="pt-6">
            <ul className="space-y-3 text-sm">
              {SOURCES.map((info) => (
                <li
                  key={info.name}
                  className="flex flex-wrap items-baseline justify-between gap-2 border-b border-[var(--border)] pb-3 last:border-0 last:pb-0"
                >
                  <span>
                    <a
                      href={info.url || site.researchPortalUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-0.5 font-semibold text-[var(--primary-text)] hover:underline"
                    >
                      {info.name} <ExternalLink aria-hidden className="size-3" />
                    </a>
                    <span className="block text-xs text-[var(--muted-foreground)]">
                      {info.role}
                    </span>
                  </span>
                  <span className="text-xs tabular-nums text-[var(--muted-foreground)]">
                    Latest data: {fmt(stamp(info))}
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-4 max-w-prose text-xs text-[var(--muted-foreground)]">
              Harvest jobs run when the library refreshes the data, and per-run
              status is listed below. The deal register is maintained by hand,
              so a re-ingest can never overwrite reviewed deal information.
              Publication statistics cover works published in 2020 or later,
              and the search lists journals with more than 3 publications in
              that window.
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
                  Most recent harvest runs per source, entity, and filter set, with status and finish time
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
                  {freshness.harvests.map((h, i) => {
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
                        <td className="py-1.5 pr-3">{h.filter_set}</td>
                        <td className="py-1.5 pr-3">
                          <Badge variant={h.status === "ok" ? "muted" : "outline"}>
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
                Rows for deal sources are historical. The deal register has been
                maintained by hand since October 2026.
              </p>
            </CardContent>
          </Card>
        </section>
      )}

      <section>
        <h2 className="mb-1 text-xl font-bold">Data limitations</h2>
        <p className="mb-3 text-sm text-[var(--muted-foreground)]">
          Every number in this browser shows its source. This registry lists the
          caveats behind the sources, and each entry links to the data provider.
        </p>
        <div className="grid gap-4 md:grid-cols-2">
          {(limitations ?? []).length === 0 && !limitationsQuery.isPending ? (
            <p className="text-sm text-[var(--muted-foreground)]">
              No limitations registered.
            </p>
          ) : null}
          {(limitations ?? []).map((l) => (
            <Card key={l.code}>
              <CardHeader className="pb-3">
                <CardTitle className="flex flex-wrap items-center gap-2 text-base">
                  {l.code}
                  <Badge
                    variant={l.severity === "warning" ? "default" : "muted"}
                    className="uppercase"
                  >
                    {l.severity}
                  </Badge>
                </CardTitle>
                <p className="text-xs text-[var(--muted-foreground)]">
                  {l.source}, {l.scope}
                </p>
              </CardHeader>
              <CardContent className="text-sm">
                {l.hint}
                {l.url && (
                  <a
                    href={l.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="ml-2 inline-flex items-center gap-0.5 text-[var(--primary-text)] hover:underline"
                  >
                    More info <ExternalLink aria-hidden className="size-3" />
                  </a>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
        <div className="mt-4">
          <SourceNote
            source="Limitation registry"
            codes={["window-2020", "corpus-cutoff", "pure-canon-primary"]}
          />
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-xl font-bold">Contact</h2>
        <Card>
          <CardContent className="pt-6 text-sm">
            <p className="mb-2 text-[var(--muted-foreground)]">
              Questions about open access publishing at {site.name}? The
              library can help.
            </p>
            <ul className="flex flex-wrap gap-x-6 gap-y-1">
              <li>
                <a
                  href={site.libraryUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-0.5 text-[var(--primary-text)] hover:underline"
                >
                  {site.name} Library{" "}
                  <ExternalLink aria-hidden className="size-3" />
                </a>
              </li>
              <li>
                <a
                  href={site.oaGuideUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-0.5 text-[var(--primary-text)] hover:underline"
                >
                  Open Access publishing guide{" "}
                  <ExternalLink aria-hidden className="size-3" />
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
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
