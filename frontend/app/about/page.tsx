"use client";

import { ExternalLink } from "lucide-react";

import { SourceNote } from "@/components/source-note";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useFreshness, useLimitations } from "@/hooks/use-api";

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
    url: "https://research.utwente.nl",
    role: "UT publication counts per journal. Pure is the primary figure, and the OpenAlex count below is its cross-check.",
    table: "institution_works_stats",
  },
  {
    name: "OpenAlex",
    url: "https://openalex.org",
    role: "Journal records, open access status, citation metrics, and the cross-check on UT publication counts.",
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
    table: "deals",
  },
  {
    name: "JCT",
    url: "https://journalcheckertool.org/transformative-agreements/",
    role: "Transformative agreement journal lists, one input used to build the register.",
    table: "deals",
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
  const { data: freshness } = useFreshness();
  const { data: limitations } = useLimitations();

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
    <div className="mx-auto max-w-6xl space-y-10 px-4 py-10">
      <header>
        <h1 className="mb-2 text-3xl font-bold">About this browser</h1>
        <p className="max-w-2xl text-[var(--muted-foreground)]">
          A journal browser for{" "}
          <strong>{freshness?.institution ?? "University of Twente"}</strong>
          {freshness?.ror && (
            <>
              {" "}
              (
              <a
                href={`https://ror.org/${freshness.ror}`}
                target="_blank"
                rel="noreferrer"
                className="text-[var(--primary)] hover:underline"
              >
                ROR {freshness.ror}
              </a>
              )
            </>
          )}
          : find where to publish, what a deal covers, and how much it costs.
        </p>
      </header>

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
                      href={info.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-0.5 font-semibold capitalize text-[var(--primary)] hover:underline"
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
            <p className="mt-4 text-xs text-[var(--muted-foreground)]">
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
                        <td className="py-1.5 pr-3 capitalize">
                          {url ? (
                            <a
                              href={url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-[var(--primary)] hover:underline"
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
                    rel="noreferrer"
                    className="ml-2 inline-flex items-center gap-0.5 text-[var(--primary)] hover:underline"
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
    </div>
  );
}
