"use client";

import { ArrowLeft, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import {
  DealBadge,
  OaFlag,
  QuartileBadge,
  QualityBarBadge,
} from "@/components/badges";
import { SourceNote } from "@/components/source-note";
import { OaSplit, StatBars } from "@/components/stat-bars";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useJournal } from "@/hooks/use-api";
import type { Attribution, DealOut } from "@/lib/api";

type NamedTopic = { display_name?: string };
type CountByYear = { year?: number; works_count?: number };

const OA_LABELS: Record<string, string> = {
  gold: "Gold OA",
  hybrid: "Hybrid OA",
  diamond: "Diamond OA",
  green: "Green OA",
  bronze: "Bronze OA",
  closed: "Closed",
};

function External({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1 text-[var(--primary)] underline-offset-2 hover:underline"
    >
      {children} <ExternalLink aria-hidden className="size-3.5" />
    </a>
  );
}

function Metric({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div>
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
      <div className="text-xs font-medium">{label}</div>
      {note && <div className="text-[11px] text-[var(--muted-foreground)]">{note}</div>}
    </div>
  );
}

function DealPanel({
  deal,
  attribution,
}: {
  deal: DealOut;
  attribution: Partial<Attribution>;
}) {
  const capNumbers = Object.entries(deal.cap_numbers ?? {}).sort((a, b) =>
    (parseInt(a[0], 10) || 0) - (parseInt(b[0], 10) || 0),
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          Open access deal
          <DealBadge covered />
          {deal.corresponding_authors_only && (
            <Badge variant="muted">Corresponding authors only</Badge>
          )}
          {deal.needs_curation && (
            <Badge
              variant="outline"
              className="border-[var(--primary)] text-[var(--primary-hover)] normal-case"
              title={deal.needs_curation_reason ?? undefined}
            >
              curation pending
            </Badge>
          )}
        </CardTitle>
        <p className="text-sm text-[var(--muted-foreground)]">
          {deal.publisher_name} · {deal.duration_text ?? deal.esac_id}
        </p>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        {deal.summary && <p>{deal.summary}</p>}
        {deal.conditions_text && (
          <div>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
              Cost implication & conditions
            </h4>
            <p className="whitespace-pre-line">{deal.conditions_text}</p>
          </div>
        )}
        {(deal.cap_text || capNumbers.length > 0) && (
          <div>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
              Article caps
            </h4>
            {deal.cap_text && <p className="whitespace-pre-line">{deal.cap_text}</p>}
            {capNumbers.length > 0 && (
              <ul className="mt-1.5 flex flex-wrap gap-1.5">
                {capNumbers.map(([year, count]) => (
                  <li
                    key={year}
                    className="rounded-full bg-[var(--muted)] px-2.5 py-0.5 text-xs tabular-nums"
                  >
                    {year}: {String(count)}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        {deal.article_types_text && (
          <div>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
              Included article types
            </h4>
            <p>{deal.article_types_text}</p>
          </div>
        )}
        {deal.workflow_text && (
          <div>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
              Workflow
            </h4>
            <p>{deal.workflow_text}</p>
          </div>
        )}
        <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-[var(--border)] pt-3">
          {deal.openaccess_nl_url && (
            <External href={deal.openaccess_nl_url}>openaccess.nl deal page</External>
          )}
          {deal.contract_url && <External href={deal.contract_url}>Contract</External>}
          {deal.jct_data_url && <External href={deal.jct_data_url}>JCT data</External>}
          <SourceNote {...attribution} />
        </div>
      </CardContent>
    </Card>
  );
}

export default function JournalPage() {
  const params = useParams<{ issn_l: string }>();
  const issnL = params?.issn_l ? decodeURIComponent(params.issn_l) : undefined;
  const { data, isPending, isError, error } = useJournal(issnL);

  if (isPending)
    return (
      <div className="mx-auto max-w-6xl px-4 py-10">
        <div className="h-8 w-2/3 animate-pulse rounded bg-[var(--muted)]" />
        <div className="mt-4 h-40 animate-pulse rounded bg-[var(--muted)]" />
      </div>
    );
  if (isError || !data)
    return (
      <div className="mx-auto max-w-6xl px-4 py-10">
        <p className="text-[var(--destructive)]">
          {(error as Error)?.message ?? "Failed to load journal."}
        </p>
        <Link
          href="/"
          className="mt-2 inline-flex items-center gap-1 text-sm text-[var(--primary)] underline-offset-4 hover:underline"
        >
          <ArrowLeft aria-hidden className="size-4" /> Back to search
        </Link>
      </div>
    );

  const { journal, stats, deals, attribution, summary_stats } = data;
  const recent = stats.filter((s) => s.year >= 2020);
  // Pure-canonical counts are the primary series (phase 10); years without
  // a pure_canon row fall back to the OpenAlex institution-filter cut.
  const worksSource = recent.some((s) => s.works_count_source === "pure_canon")
    ? "Pure registrations"
    : "OpenAlex institution filter";
  const barsSource =
    recent.length > 0
      ? {
          label: `University of Twente (${worksSource})`,
          note: attribution.stats,
          data: recent.map((s) => ({ year: s.year, value: s.works_count })),
        }
      : {
          label: "All affiliations",
          note: attribution.title,
          data: (data.counts_by_year as CountByYear[])
            .filter((c) => (c.year ?? 0) >= 2020)
            .sort((a, b) => (a.year ?? 0) - (b.year ?? 0))
            .map((c) => ({ year: c.year!, value: c.works_count ?? 0 })),
        };
  const sum = (key: "oa_gold" | "oa_hybrid" | "oa_green" | "oa_bronze" | "oa_diamond" | "oa_closed") =>
    recent.reduce((acc, s) => acc + (s[key] ?? 0), 0);
  const oaSegments = (
    ["gold", "hybrid", "diamond", "green", "bronze", "closed"] as const
  ).map((key) => ({
    key,
    label: OA_LABELS[key],
    count: sum(`oa_${key}` as const),
  }));
  const totalOa = oaSegments.reduce((acc, s) => acc + s.count, 0);

  const ss = (summary_stats ?? {}) as Record<string, unknown>;
  const num = (key: string) =>
    typeof ss[key] === "number" ? (ss[key] as number) : null;
  const latestSjr = data.scimagojr.at(-1);
  const topics = Array.from(
    new Set(
      (data.topics as NamedTopic[])
        .map((t) => t?.display_name)
        .filter((n): n is string => Boolean(n)),
    ),
  );

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <Link
        href="/"
        className="mb-4 inline-flex items-center gap-1 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
      >
        <ArrowLeft aria-hidden className="size-4" /> Back to search
      </Link>

      <header className="mb-8">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-3xl font-bold">{journal.title ?? journal.issn_l}</h1>
          <OaFlag isOa={journal.is_oa} />
          <QuartileBadge quartile={journal.quartile ?? null} />
          {!journal.in_quality_bar && <QualityBarBadge />}
        </div>
        <p className="mt-1.5 text-[var(--muted-foreground)]">
          {journal.publisher_name ?? "Unknown publisher"}
          {data.type ? ` · ${data.type}` : ""} · ISSN-L {journal.issn_l}
          {data.issns.length > 1 && ` (${data.issns.join(", ")})`}
        </p>
        <p className="mt-1 text-xs text-[var(--muted-foreground)]">
          <SourceNote
            source="Metadata: OpenAlex"
            url={attribution.title?.url ?? undefined}
          />
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-6">
          {deals.length > 0 ? (
            deals.map((deal) => (
              <DealPanel
                key={deal.id}
                deal={deal}
                attribution={attribution.deals ?? {}}
              />
            ))
          ) : (
            <Card>
              <CardHeader>
                <CardTitle>Open access deal</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-[var(--muted-foreground)]">
                No current open access deal covering this journal for
                University of Twente authors. Check{" "}
                <External href="https://www.openaccess.nl">openaccess.nl</External>{" "}
                and the{" "}
                <External href="https://journalcheckertool.org">
                  Journal Checker Tool
                </External>{" "}
                for green OA routes.
                <div className="mt-2">
                  <SourceNote {...(attribution.deals ?? {})} />
                </div>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle>Open access split (Twente, 2020+)</CardTitle>
            </CardHeader>
            <CardContent>
              {totalOa > 0 ? (
                <>
                  <OaSplit segments={oaSegments} />
                  <p className="mt-3 text-xs text-[var(--muted-foreground)]">
                    {totalOa.toLocaleString("en")} works with an OA status
                    recorded.
                  </p>
                </>
              ) : (
                <p className="text-sm text-[var(--muted-foreground)]">
                  No Twente works with OA status yet.
                </p>
              )}
              <div className="mt-3">
                <SourceNote {...(attribution.oa_status ?? {})} />
              </div>
            </CardContent>
          </Card>

          {topics.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Topics</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-1.5">
                {topics.map((topic) => (
                  <Badge key={topic} variant="muted" className="font-normal normal-case">
                    {topic}
                  </Badge>
                ))}
              </CardContent>
            </Card>
          )}
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>
                Publications by year{" "}
                <span className="text-sm font-normal text-[var(--muted-foreground)]">
                  ({barsSource.label})
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {barsSource.data.length > 0 ? (
                <StatBars data={barsSource.data} />
              ) : (
                <p className="text-sm text-[var(--muted-foreground)]">
                  No publication statistics yet.
                </p>
              )}
              <p className="mt-3 text-sm">
                {journal.twente_works.toLocaleString("en")} UT works total
                since 2020{" "}
                <span className="text-[var(--muted-foreground)]">
                  ({worksSource})
                </span>
                .
              </p>
              <div className="mt-2">
                <SourceNote {...(barsSource.note ?? {})} />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Metrics</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              <div className="grid grid-cols-3 gap-4">
                <Metric
                  label="2yr mean citedness"
                  value={
                    journal.twoyr_mean_citedness != null
                      ? journal.twoyr_mean_citedness.toFixed(1)
                      : "—"
                  }
                />
                <Metric
                  label="h-index"
                  value={num("h_index")?.toLocaleString("en") ?? "—"}
                />
                <Metric
                  label="i10 index"
                  value={num("i10_index")?.toLocaleString("en") ?? "—"}
                />
              </div>
              <SourceNote {...(attribution.metrics ?? {})} />
              {latestSjr && (
                <div className="border-t border-[var(--border)] pt-4">
                  <div className="grid grid-cols-3 gap-4">
                    <Metric
                      label="SJR"
                      value={latestSjr.sjr !== null ? latestSjr.sjr.toFixed(3) : "—"}
                      note={latestSjr.year ? String(latestSjr.year) : undefined}
                    />
                    <Metric
                      label="Best quartile"
                      value={latestSjr.best_quartile ?? "—"}
                    />
                    <Metric
                      label="SJR h-index"
                      value={latestSjr.h_index?.toLocaleString("en") ?? "—"}
                    />
                  </div>
                  <div className="mt-3">
                    <SourceNote {...(attribution.scimagojr ?? {})} />
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {(data.apc_aggregates.length > 0 || data.apc_evidence.length > 0) && (
            <Card>
              <CardHeader>
                <CardTitle>APC cost evidence</CardTitle>
              </CardHeader>
              <CardContent className="text-sm">
                {data.apc_aggregates.length > 0 && (
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-left text-[var(--muted-foreground)]">
                        <th className="py-1 pr-2 font-medium">Year</th>
                        <th className="py-1 pr-2 font-medium">APCs</th>
                        <th className="py-1 pr-2 font-medium">Mean €</th>
                        <th className="py-1 font-medium">Range €</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.apc_aggregates.map((a) => (
                        <tr key={a.period} className="border-t border-[var(--border)]">
                          <td className="py-1 pr-2 tabular-nums">{a.period}</td>
                          <td className="py-1 pr-2 tabular-nums">{a.article_count}</td>
                          <td className="py-1 pr-2 tabular-nums">
                            {a.euro_mean !== null ? Math.round(a.euro_mean).toLocaleString("en") : "—"}
                          </td>
                          <td className="py-1 tabular-nums">
                            {a.euro_min !== null && a.euro_max !== null
                              ? `${Math.round(a.euro_min)}–${Math.round(a.euro_max)}`
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                {data.apc_evidence.length > 0 && (
                  <p className="mt-3 text-xs text-[var(--muted-foreground)]">
                    {data.apc_evidence.length} Twente APC records (latest{" "}
                    {data.apc_evidence[0].period ?? "—"}:{" "}
                    {data.apc_evidence[0].euro !== null
                      ? `€${Math.round(data.apc_evidence[0].euro!)}`
                      : "amount unknown"}
                    ).
                  </p>
                )}
                <div className="mt-3">
                  <SourceNote {...(attribution.apc_evidence ?? {})} />
                </div>
              </CardContent>
            </Card>
          )}

          {data.homepage_url && (
            <p className="text-sm">
              <External href={data.homepage_url}>Journal homepage</External>
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
