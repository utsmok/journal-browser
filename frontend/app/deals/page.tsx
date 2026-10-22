"use client";

import { ExternalLink } from "lucide-react";
import type { UseQueryResult } from "@tanstack/react-query";

import { SourceNote } from "@/components/source-note";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useDeals } from "@/hooks/use-api";
import type { DealOut } from "@/lib/api";

function DealCard({ deal, archived }: { deal: DealOut; archived?: boolean }) {
  const capNumbers = Object.entries(deal.cap_numbers ?? {}).sort(
    (a, b) => (parseInt(a[0], 10) || 0) - (parseInt(b[0], 10) || 0),
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          {deal.publisher_name ?? `Deal ${deal.id}`}
          {archived ? (
            <Badge variant="muted">Archive</Badge>
          ) : (
            <Badge variant="secondary">Current</Badge>
          )}
          {deal.twente_relevant && <Badge variant="muted">UT relevant</Badge>}
          {deal.needs_curation && (
            <Badge
              variant="outline"
              className="border-[var(--destructive)] text-[var(--destructive)] normal-case"
              title={deal.needs_curation_reason ?? undefined}
            >
              needs curation
            </Badge>
          )}
        </CardTitle>
        <p className="text-sm text-[var(--muted-foreground)]">
          {deal.duration_text ?? `${deal.start_year ?? "?"}–${deal.end_year ?? "?"}`}{" "}
          · {deal.journal_count.toLocaleString("en")} journals
          {deal.corresponding_authors_only && " · corresponding authors only"}
        </p>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {deal.summary && <p>{deal.summary}</p>}
        {deal.cap_text && (
          <p>
            <span className="font-medium">Caps: </span>
            {deal.cap_text}
          </p>
        )}
        {capNumbers.length > 0 && (
          <ul className="flex flex-wrap gap-1.5">
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
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {deal.openaccess_nl_url && (
            <a
              href={deal.openaccess_nl_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-[var(--primary)] hover:underline"
            >
              openaccess.nl <ExternalLink aria-hidden className="size-3" />
            </a>
          )}
          {deal.contract_url && (
            <a
              href={deal.contract_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-[var(--primary)] hover:underline"
            >
              Contract <ExternalLink aria-hidden className="size-3" />
            </a>
          )}
          {deal.jct_data_url && (
            <a
              href={deal.jct_data_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-[var(--primary)] hover:underline"
            >
              JCT data <ExternalLink aria-hidden className="size-3" />
            </a>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export default function DealsPage() {
  const current = useDeals("current");
  const archive = useDeals("archive");

  const section = (
    label: string,
    query: UseQueryResult<DealOut[], Error>,
    archived?: boolean,
  ) => (
    <section className="mb-10">
      <h2 className="mb-1 text-xl font-bold">{label}</h2>
      <p className="mb-4 text-sm text-[var(--muted-foreground)]">
        {query.data
          ? `${query.data.length} deals covering University of Twente`
          : "Loading…"}
      </p>
      {query.isError ? (
        <p className="text-[var(--destructive)]">
          {(query.error as Error)?.message}
        </p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {(query.data ?? []).map((deal) => (
            <DealCard key={deal.id} deal={deal} archived={archived} />
          ))}
        </div>
      )}
    </section>
  );

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <h1 className="mb-2 text-3xl font-bold">Open access deals</h1>
      <p className="mb-8 max-w-2xl text-[var(--muted-foreground)]">
        Transformative and read-and-publish agreements relevant to University of
        Twente authors, with caps, conditions, and workflow summaries.
      </p>
      {section("Current deals", current)}
      {section("Archive", archive, true)}
      <SourceNote
        source="JCT · openaccess.nl"
        url="https://journalcheckertool.org/transformative-agreements/"
        codes={["jct-coverage", "openaccess-nl-prose", "issn-mapping"]}
      />
    </div>
  );
}
