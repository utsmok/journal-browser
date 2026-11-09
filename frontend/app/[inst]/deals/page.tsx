"use client";

import { ChevronDown, CircleCheck, CircleX, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import type { UseQueryResult } from "@tanstack/react-query";

import { SourceNote } from "@/components/source-note";
import { Badge } from "@/components/ui/badge";
import { CollapsibleCard } from "@/components/collapsible-card";
import { Button } from "@/components/ui/button";
import { useDeals } from "@/hooks/use-api";
import { useInstitution } from "@/hooks/use-institution";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { errorMessage, type DealLink, type DealOut } from "@/lib/api";
import { dealLinkLabel, displayPublisherName, orderedDealLinks } from "@/lib/deal-links";
import { formatApc, formatEur } from "@/lib/format";
import { cleanProse } from "@/lib/utils";

/** One card line for a condition the deal either has or not. */
function ConditionLine({ ok, label }: { ok: boolean; label: string }) {
  const Icon = ok ? CircleCheck : CircleX;
  return (
    <span
      className={`inline-flex items-center gap-1 ${ok ? "" : "text-[var(--muted-foreground)]"}`}
      title={ok ? "Applies to this deal" : "Does not apply to this deal"}
    >
      <Icon aria-hidden className="size-3.5" />
      {label}
    </span>
  );
}

/** First sentence or two of the scraped summary, for the card description. */
function summaryPreview(text: string): string {
  const sentences = text.match(/[^.!?]+[.!?]+(\s|$)/g) ?? [text];
  const preview = sentences.slice(0, 2).join(" ").trim();
  return preview.length > 0 ? preview : text.trim();
}

function DealCard({ deal, archived }: { deal: DealOut; archived?: boolean }) {
  const site = useSiteMeta();
  const inst = useInstitution();
  const capNumbers = Object.entries(deal.cap_numbers ?? {}).sort(
    (a, b) => (parseInt(a[0], 10) || 0) - (parseInt(b[0], 10) || 0),
  );
  const oaPerYear = Object.entries(deal.per_year_oa_counts ?? {}).sort(
    (a, b) => (parseInt(a[0], 10) || 0) - (parseInt(b[0], 10) || 0),
  );
  const summary = deal.summary ? cleanProse(deal.summary) : null;
  const preview = summary ? summaryPreview(summary) : null;
  const duration = deal.duration_text ?? `${deal.start_year ?? "?"}–${deal.end_year ?? "?"}`;
  const latestOa = oaPerYear.at(-1);
  const latestCap = capNumbers.at(-1);
  const prose = (
    <>
      {deal.conditions_text && (
        <div>
          <p className="font-medium">Conditions</p>
          <p className="mt-0.5 max-w-prose text-pretty">{cleanProse(deal.conditions_text)}</p>
        </div>
      )}
      {deal.workflow_text && (
        <div>
          <p className="font-medium">Workflow</p>
          <p className="mt-0.5 max-w-prose text-pretty">{cleanProse(deal.workflow_text)}</p>
        </div>
      )}
      {deal.article_types_text && (
        <div>
          <p className="font-medium">Article types</p>
          <p className="mt-0.5 max-w-prose text-pretty">{cleanProse(deal.article_types_text)}</p>
        </div>
      )}
    </>
  );
  const hasProse = deal.conditions_text || deal.workflow_text || deal.article_types_text;
  // Collapsible like the detail page's deal panels: the scraped prose runs
  // long, and a 16-card page should not force all of it on the reader.
  return (
    <CollapsibleCard
      id={`deal-${deal.id}`}
      title={
        <>
          {displayPublisherName(deal.publisher_name) || `Deal ${deal.id}`}
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
        <p className="line-clamp-2 text-sm text-[var(--muted-foreground)]">
          {preview ?? `${duration} · ${deal.journal_count.toLocaleString("en")} journals`}
        </p>
      }
      contentClassName="space-y-3 text-sm"
    >
      {/* Key figures at a glance; full per-year breakdowns follow below. */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums text-[var(--muted-foreground)]">
        <span>{duration}</span>
        <span>{deal.journal_count.toLocaleString("en")} journals</span>
        {latestOa && (
          <span>
            {Number(latestOa[1]).toLocaleString("en")} OA articles in {latestOa[0]}
          </span>
        )}
        {latestCap && (
          <span>
            cap usage {latestCap[0]}: {Number(latestCap[1]).toLocaleString("en")}
          </span>
        )}
        {deal.apc_n > 0 && <span>{formatEur(deal.apc_euro_total)} in APC fees</span>}
        {deal.apc_n > 1 && <span>mean {formatApc(deal.apc_euro_total / deal.apc_n)}</span>}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
        <ConditionLine
          ok={deal.corresponding_authors_only === true}
          label="Corresponding authors only"
        />
        <ConditionLine
          ok={Boolean(deal.cap_text || capNumbers.length > 0)}
          label="Discounted articles capped"
        />
      </div>
      {summary && summary !== preview && <p className="max-w-prose text-pretty">{summary}</p>}
      {deal.cap_text && (
        <p className="max-w-prose text-pretty">
          <span className="font-medium">Caps: </span>
          {cleanProse(deal.cap_text)}
        </p>
      )}
      {capNumbers.length > 0 && (
        <div>
          <p className="mb-1 text-xs text-[var(--muted-foreground)]">Cap usage per year</p>
          <ul className="flex flex-wrap gap-1.5">
            {capNumbers.map(([year, count]) => (
              <li
                key={year}
                className="rounded-full bg-[var(--muted)] px-2.5 py-0.5 text-xs tabular-nums"
              >
                {year}: {Number(count).toLocaleString("en")}
              </li>
            ))}
          </ul>
        </div>
      )}
      {oaPerYear.length > 0 && (
        <div>
          <p className="mb-1 text-xs text-[var(--muted-foreground)]">
            OA articles per year (JCT output)
          </p>
          <ul className="flex flex-wrap gap-1.5">
            {oaPerYear.map(([year, count]) => (
              <li
                key={year}
                className="rounded-full bg-[var(--muted)] px-2.5 py-0.5 text-xs tabular-nums"
              >
                {year}: {Number(count).toLocaleString("en")}
              </li>
            ))}
          </ul>
        </div>
      )}
      {hasProse && (
        <details className="text-sm">
          <summary className="cursor-pointer text-[var(--primary-text)] hover:underline">
            Conditions, workflow, and article types
          </summary>
          <div className="mt-2 space-y-2">{prose}</div>
        </details>
      )}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {!archived && (
          <Link
            href={`/${inst}/journals?deal=covered`}
            className="inline-flex items-center gap-1 text-[var(--primary-text)] hover:underline"
          >
            Covered journals (search)
          </Link>
        )}
        {deal.links?.length ? (
          orderedDealLinks(deal.links)
            .filter((link): link is DealLink & { url: string } => !!link.url)
            .map((link) => (
              <a
                key={`${link.category}-${link.url}`}
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-[var(--primary-text)] hover:underline"
              >
                {dealLinkLabel(link)} <ExternalLink aria-hidden className="size-3" />
              </a>
            ))
        ) : (
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
  const [archiveOpen, setArchiveOpen] = useState(false);
  const section = (label: string, query: UseQueryResult<DealOut[], Error>, archived?: boolean) => (
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
          <Button variant="outline" size="sm" className="mt-2" onClick={() => query.refetch()}>
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

  // Archived deals are rarely consulted, so they load behind a toggle; the
  // count rides in the heading so readers know what is folded away.
  const archiveCount = archive.data?.length ?? 0;
  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <h1 className="mb-2 text-3xl font-bold">Open access deals</h1>
      <p className="mb-8 max-w-2xl text-[var(--muted-foreground)]">
        Transformative and read-and-publish agreements covering {site.short} authors — the caps,
        conditions, and workflow for each deal.
      </p>
      {section("Current deals", current)}
      {archive.data ? (
        archiveCount > 0 ? (
          <section className="mb-10">
            <h2 className="text-xl font-bold">
              <button
                type="button"
                aria-expanded={archiveOpen}
                aria-controls="archive-deals"
                onClick={() => setArchiveOpen((open) => !open)}
                className="inline-flex items-center gap-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--primary)]"
              >
                Archive ({archiveCount})
                <ChevronDown
                  aria-hidden
                  className={`size-4 text-[var(--muted-foreground)] transition-transform ${archiveOpen ? "" : "-rotate-90"}`}
                />
              </button>
            </h2>
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">
              Signed deals that no longer apply to {site.short} authors.
            </p>
            {archiveOpen && (
              <div id="archive-deals" className="mt-4 grid gap-4 lg:grid-cols-2">
                {archive.data.map((deal) => (
                  <DealCard key={deal.id} deal={deal} archived />
                ))}
              </div>
            )}
          </section>
        ) : (
          <section className="mb-10">
            <h2 className="mb-1 text-xl font-bold">Archive</h2>
            <p className="text-sm text-[var(--muted-foreground)]">No archived deals.</p>
          </section>
        )
      ) : archive.isError ? (
        <section className="mb-10">
          <h2 className="mb-1 text-xl font-bold">Archive</h2>
          <p className="text-[var(--destructive)]">{errorMessage(archive.error)}</p>
          <Button variant="outline" size="sm" className="mt-2" onClick={() => archive.refetch()}>
            Retry
          </Button>
        </section>
      ) : null}
      <SourceNote
        source="JCT · openaccess.nl"
        url="https://journalcheckertool.org/transformative-agreements/"
        codes={["jct-coverage", "openaccess-nl-prose", "issn-mapping"]}
      />
    </div>
  );
}
