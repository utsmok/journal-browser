"use client";

import { ExternalLink } from "lucide-react";
import type { UseQueryResult } from "@tanstack/react-query";

import { SourceNote } from "@/components/source-note";
import { Badge } from "@/components/ui/badge";
import { CollapsibleCard } from "@/components/collapsible-card";
import { Button } from "@/components/ui/button";
import { useDeals } from "@/hooks/use-api";
import { useSiteMeta } from "@/hooks/use-site-meta";
import {
  errorMessage,
  type DealLink,
  type DealOut,
} from "@/lib/api";
import { dealLinkLabel, orderedDealLinks } from "@/lib/deal-links";
import { cleanProse } from "@/lib/utils";

function DealCard({ deal, archived }: { deal: DealOut; archived?: boolean }) {
  const site = useSiteMeta();
  const capNumbers = Object.entries(deal.cap_numbers ?? {}).sort(
    (a, b) => (parseInt(a[0], 10) || 0) - (parseInt(b[0], 10) || 0),
  );
  // Collapsible like the detail page's deal panels: the scraped prose runs
  // long, and a 16-card page should not force all of it on the reader.
  return (
    <CollapsibleCard
      id={`deal-${deal.id}`}
      title={
        <>
          {deal.publisher_name ?? `Deal ${deal.id}`}
          {archived ? (
            <Badge variant="muted" title="Archived deal: no longer in effect.">
              Archive
            </Badge>
          ) : (
            <Badge variant="secondary" title={`Current deal: in effect for ${site.name} authors.`}>
              Current
            </Badge>
          )}
          {deal.needs_curation && (
            <Badge
              variant="outline"
              className="border-[var(--primary)] text-[var(--primary-text)] normal-case"
              title={deal.needs_curation_reason ?? undefined}
            >
              curation pending
            </Badge>
          )}
        </>
      }
      description={
        <p className="text-sm text-[var(--muted-foreground)]">
          {deal.duration_text ?? `${deal.start_year ?? "?"}–${deal.end_year ?? "?"}`}{" "}
          · {deal.journal_count.toLocaleString("en")} journals
          {deal.corresponding_authors_only && " · corresponding authors only"}
        </p>
      }
      contentClassName="space-y-3 text-sm"
    >
        {deal.summary && (
          <p className="max-w-prose text-pretty">{cleanProse(deal.summary)}</p>
        )}
        {deal.cap_text && (
          <p className="max-w-prose text-pretty">
            <span className="font-medium">Caps: </span>
            {cleanProse(deal.cap_text)}
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
          {deal.links?.length
            ? orderedDealLinks(deal.links)
                .filter((link): link is DealLink & { url: string } => !!link.url)
                .map((link) => (
                  <a
                    key={`${link.category}-${link.url}`}
                    href={link.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-[var(--primary-text)] hover:underline"
                  >
                  {dealLinkLabel(link)}{" "}
                  <ExternalLink aria-hidden className="size-3" />
                </a>
              ))
            : (
              // Old backend: no links[] yet; fall back to the flat URL fields.
              <>
                {deal.openaccess_nl_url && (
                  <a
                    href={deal.openaccess_nl_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-[var(--primary-text)] hover:underline"
                  >
                    openaccess.nl <ExternalLink aria-hidden className="size-3" />
                  </a>
                )}
                {deal.contract_url && (
                  <a
                    href={deal.contract_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-[var(--primary-text)] hover:underline"
                  >
                    Contract <ExternalLink aria-hidden className="size-3" />
                  </a>
                )}
                {deal.jct_data_url && (
                  <a
                    href={deal.jct_data_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-[var(--primary-text)] hover:underline"
                  >
                    JCT data <ExternalLink aria-hidden className="size-3" />
                  </a>
                )}
              </>
            )}
        </div>
    </CollapsibleCard>
  );
}

export default function DealsPage() {
  const site = useSiteMeta();
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
          ? `${query.data.length} deals relevant to ${site.short} authors`
          : query.isError
            ? "Could not load deals."
            : "Loading…"}
      </p>
      {query.isError ? (
        <div>
          <p className="text-[var(--destructive)]">{errorMessage(query.error)}</p>
          <Button
            variant="outline"
            size="sm"
            className="mt-2"
            onClick={() => query.refetch()}
          >
            Retry
          </Button>
        </div>
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
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <h1 className="mb-2 text-3xl font-bold">Open access deals</h1>
      <p className="mb-8 max-w-2xl text-[var(--muted-foreground)]">
        Transformative and read-and-publish agreements relevant to {site.name}{" "}
        authors, with caps, conditions, and workflow summaries.
      </p>
      {section("Current deals", current)}
      {archive.data?.length === 0 ? (
        // Loaded and empty: say so instead of a bare headed grid.
        <section className="mb-10">
          <h2 className="mb-1 text-xl font-bold">Archive</h2>
          <p className="text-sm text-[var(--muted-foreground)]">
            No archived deals.
          </p>
        </section>
      ) : (
        section("Archive", archive, true)
      )}
      <SourceNote
        source="JCT · openaccess.nl"
        url="https://journalcheckertool.org/transformative-agreements/"
        codes={["jct-coverage", "openaccess-nl-prose", "issn-mapping"]}
      />
    </div>
  );
}
