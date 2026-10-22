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

const SOURCE_ROLES: Record<string, string> = {
  openalex: "Journal metadata, OA status, citation metrics, UT publication statistics",
  jct: "Transformative agreement journal lists, caps, and per-year counts",
  "openaccess.nl": "Deal narratives, conditions, workflow summaries",
  openapc: "APC price aggregates and per-article cost evidence",
  scimagojr: "SJR indicator, best quartile, SJR h-index",
};

function fmt(value: unknown) {
  if (value === null || value === undefined) return "—";
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
        <h2 className="mb-3 text-xl font-bold">Data sources & cadence</h2>
        <Card>
          <CardContent className="pt-6">
            <ul className="space-y-3 text-sm">
              {Object.entries(SOURCE_ROLES).map(([source, role]) => {
                const tables = (freshness?.tables ?? {}) as Record<string, unknown>;
                const stampKey =
                  source === "openalex"
                    ? "journals"
                    : source === "openapc"
                      ? "apc_evidence"
                      : source === "scimagojr"
                        ? "scimagojr_metrics"
                        : source === "jct"
                          ? "deals"
                          : "deals";
                return (
                  <li key={source} className="flex flex-wrap items-baseline justify-between gap-2 border-b border-[var(--border)] pb-3 last:border-0 last:pb-0">
                    <span>
                      <span className="font-semibold capitalize">{source}</span>
                      <span className="block text-xs text-[var(--muted-foreground)]">
                        {role}
                      </span>
                    </span>
                    <span className="text-xs tabular-nums text-[var(--muted-foreground)]">
                      Latest data: {fmt(tables[stampKey])}
                    </span>
                  </li>
                );
              })}
            </ul>
            <p className="mt-4 text-xs text-[var(--muted-foreground)]">
              Harvest runs re-ingest each source on a schedule; per-run status
              is shown below. Publication statistics cover works from 2020
              onwards.
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
                  {freshness.harvests.map((h, i) => (
                    <tr
                      key={`${h.source}-${h.entity_type}-${i}`}
                      className="border-t border-[var(--border)]"
                    >
                      <td className="py-1.5 pr-3 capitalize">{h.source}</td>
                      <td className="py-1.5 pr-3">{h.entity_type}</td>
                      <td className="py-1.5 pr-3">{h.filter_set}</td>
                      <td className="py-1.5 pr-3">
                        <Badge variant={h.status === "ok" ? "muted" : "outline"}>
                          {h.status ?? "—"}
                        </Badge>
                      </td>
                      <td className="py-1.5 tabular-nums">{fmt(h.finished_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </section>
      )}

      <section>
        <h2 className="mb-1 text-xl font-bold">Data limitations</h2>
        <p className="mb-3 text-sm text-[var(--muted-foreground)]">
          Every statistic in this browser carries its source label; these are
          the registered caveats behind them.
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
                  {l.source} · {l.scope}
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
            codes={["window-2020", "openalex-metrics", "jct-coverage"]}
          />
        </div>
      </section>
    </div>
  );
}
