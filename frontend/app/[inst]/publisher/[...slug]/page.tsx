"use client";

import { ArrowLeft, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import { DealBadge, OaTypeBadge, QuartileBadge } from "@/components/badges";
import { CardPager } from "@/components/card-pager";
import { CollapsibleCard } from "@/components/collapsible-card";
import { OaCompositionBar, OaCompositionLegend } from "@/components/oa-composition";
import { OaTrend } from "@/components/oa-trend";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { usePublisher } from "@/hooks/use-api";
import { useInstitution } from "@/hooks/use-institution";
import {
  errorMessage,
  type DealOut,
  type JournalListItem,
  type PublisherListItem,
} from "@/lib/api";
import { formatEur } from "@/lib/format";
import { dealLinkLabel, orderedDealLinks } from "@/lib/deal-links";

/** APC display for one journal: OpenAlex list price, else OpenAPC range. */
function journalApcText(j: JournalListItem): string | null {
  if (j.apc_source === "openalex" && j.apc_price != null)
    return `${formatEur(j.apc_price)} €`;
  if (j.apc_source === "openapc" && j.apc_low != null)
    return j.apc_high != null && j.apc_high !== j.apc_low
      ? `${formatEur(j.apc_low)}–${formatEur(j.apc_high)} €`
      : `${formatEur(j.apc_low)} €`;
  return null;
}

/** First curated link for a deal ("conditions" / contract document). */
function dealConditionsUrl(deal: DealOut): string | null {
  const links = deal.links ? orderedDealLinks(deal.links) : [];
  return links[0]?.url ?? deal.contract_url ?? null;
}

function DealRow({ deal }: { deal: DealOut }) {
  const conditionsUrl = dealConditionsUrl(deal);
  return (
    <li className="py-2.5 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <DealBadge covered />
        <span className="font-medium">{deal.publisher_name ?? "Open access deal"}</span>
        {deal.duration_text && (
          <span className="text-xs text-[var(--muted-foreground)]">
            {deal.duration_text}
          </span>
        )}
        {deal.corresponding_authors_only && (
          <span className="text-xs text-[var(--muted-foreground)]">
            corresponding authors only
          </span>
        )}
        {conditionsUrl && (
          <a
            href={conditionsUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-[var(--primary-text)] underline-offset-2 hover:underline"
          >
            {deal.links?.length
              ? dealLinkLabel(orderedDealLinks(deal.links)[0])
              : "Contract"}{" "}
            <ExternalLink aria-hidden className="size-3.5 shrink-0" />
          </a>
        )}
      </div>
      {deal.conditions_text && (
        <p className="mt-1 max-w-prose whitespace-pre-line text-pretty text-xs text-[var(--muted-foreground)]">
          {deal.conditions_text}
        </p>
      )}
    </li>
  );
}

/** The three headline aggregates: access mix, quartile spread, APC. */
function AggregateCards({ publisher }: { publisher: PublisherListItem }) {
  const { n_journals, eur_min: min, eur_max: max } = publisher.apc;
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4">
        <h2 className="mb-3 text-sm font-semibold">Open access composition</h2>
        <div className="mb-3">
          <OaCompositionBar
            counts={publisher.oa_types}
            total={publisher.n_journals}
            className="h-3"
          />
        </div>
        <OaCompositionLegend counts={publisher.oa_types} />
      </div>
      <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4">
        <h2 className="mb-3 text-sm font-semibold">Quartiles</h2>
        <ul className="space-y-1 text-sm tabular-nums">
          {(["q1", "q2", "q3", "q4", "none"] as const).map((q) => {
            const n = publisher.quartiles[q] ?? 0;
            return (
              <li
                key={q}
                className={
                  n
                    ? "flex items-center justify-between gap-4"
                    : "flex items-center justify-between gap-4 text-[var(--muted-foreground)]"
                }
              >
                <span>{q === "none" ? "Not ranked" : q.toUpperCase()}</span>
                <span>{n.toLocaleString("en")}</span>
              </li>
            );
          })}
        </ul>
      </div>
      <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4">
        <h2 className="mb-3 text-sm font-semibold">Article processing costs</h2>
        {n_journals === 0 || (min == null && max == null) ? (
          <p className="text-sm text-[var(--muted-foreground)]">
            No APC price known for this publisher&apos;s journals.
          </p>
        ) : (
          <>
            <p className="text-2xl font-semibold tabular-nums">
              {min != null && max != null && min !== max
                ? `${formatEur(min)}–${formatEur(max)} €`
                : `${formatEur(max ?? (min as number))} €`}
            </p>
            <p className="mt-1 text-xs text-[var(--muted-foreground)]">
              APC known for {n_journals}{" "}
              {n_journals === 1 ? "journal" : "journals"}; publisher list prices
              and OpenAPC ranges combined.
            </p>
          </>
        )}
      </div>
    </div>
  );
}

export default function PublisherPage() {
  const params = useParams<{ slug: string[] }>();
  const inst = useInstitution();
  const backHref = `/${inst}/publisher`;
  const name = params?.slug?.map(decodeURIComponent).join("/") ?? "";
  const { data, isPending, isError, error } = usePublisher(name || undefined);

  // Per-card pagination, author-detail style (the list is capped at 200).
  const PAGE_SIZE = 20;
  const [journalPage, setJournalPage] = React.useState(1);
  React.useEffect(() => {
    setJournalPage(1);
  }, [name]);

  if (isPending)
    return (
      <div className="mx-auto max-w-screen-2xl px-4 py-10">
        <div className="h-8 w-2/3 animate-pulse rounded bg-[var(--muted)]" />
        <div className="mt-4 h-40 animate-pulse rounded bg-[var(--muted)]" />
      </div>
    );
  if (isError || !data)
    return (
      <div className="mx-auto max-w-screen-2xl px-4 py-10">
        <p className="text-[var(--destructive)]">{errorMessage(error)}</p>
        <Link
          href={backHref}
          className="mt-2 inline-flex items-center gap-1 text-sm text-[var(--primary-text)] underline-offset-4 hover:underline"
        >
          <ArrowLeft aria-hidden className="size-4" /> Back to publishers
        </Link>
      </div>
    );

  const { publisher, journals, deals, works_by_year } = data;
  const journalPages = Math.max(1, Math.ceil(journals.length / PAGE_SIZE));
  const journalRows = journals.slice(
    (journalPage - 1) * PAGE_SIZE,
    journalPage * PAGE_SIZE,
  );

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <Link
        href={backHref}
        className="inline-flex items-center gap-1 text-sm text-[var(--primary-text)] underline-offset-4 hover:underline"
      >
        <ArrowLeft aria-hidden className="size-4" /> Back to publishers
      </Link>
      <header className="mb-6 mt-4">
        <h1 className="text-3xl font-bold text-balance">{publisher.name}</h1>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-[var(--muted-foreground)]">
          <span>
            {publisher.n_journals.toLocaleString("en")}{" "}
            {publisher.n_journals === 1 ? "journal" : "journals"}
          </span>
          <span aria-hidden>·</span>
          <span>
            {publisher.n_works.toLocaleString("en")}{" "}
            {publisher.n_works === 1 ? "work" : "works"}
          </span>
          {publisher.deal_journals > 0 && (
            <>
              <span aria-hidden>·</span>
              <span>
                {publisher.deal_journals} deal-covered{" "}
                {publisher.deal_journals === 1 ? "journal" : "journals"}
              </span>
            </>
          )}
        </div>
      </header>

      <AggregateCards publisher={publisher} />

      <div className="mt-6 space-y-6">
        {deals.length > 0 && (
          <CollapsibleCard
            id="deals"
            title="Open access deals"
            contentClassName="text-sm"
          >
            <ul className="divide-y divide-[var(--border)]">
              {deals.map((deal) => (
                <DealRow key={deal.id} deal={deal} />
              ))}
            </ul>
          </CollapsibleCard>
        )}

        {publisher.topics.length > 0 && (
          <CollapsibleCard
            id="topics"
            title="Topics"
            contentClassName="flex flex-wrap gap-1.5"
          >
            {publisher.topics.map((t) => (
              <Badge
                key={t.name}
                variant="muted"
                className="font-normal normal-case"
                title={`${Math.round(t.n)} works in this topic area`}
              >
                {t.name}
              </Badge>
            ))}
          </CollapsibleCard>
        )}

        {works_by_year.length > 0 && (
          <CollapsibleCard id="oa-over-time" title="Open access over time">
            <OaTrend stats={works_by_year} />
          </CollapsibleCard>
        )}

        {journals.length > 0 && (
          <CollapsibleCard
            id="journals"
            title="Journals"
            contentClassName="text-sm"
          >
            <Table>
              <caption className="sr-only">
                Journals of this publisher
              </caption>
              <TableHeader>
                <TableRow>
                  <TableHead>Journal</TableHead>
                  <TableHead className="text-right">Works</TableHead>
                  <TableHead>Access</TableHead>
                  <TableHead>Q</TableHead>
                  <TableHead>APC</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {journalRows.map((j) => {
                  const apc = journalApcText(j);
                  return (
                    <TableRow key={j.issn_l}>
                      <TableCell className="font-medium">
                        <Link
                          href={`/${inst}/journals/${j.issn_l}`}
                          className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                        >
                          {j.title || j.issn_l}
                        </Link>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {j.works.toLocaleString("en")}
                      </TableCell>
                      <TableCell>
                        <OaTypeBadge oaType={j.oa_type} isOa={j.is_oa} />
                      </TableCell>
                      <TableCell>
                        <QuartileBadge quartile={j.quartile ?? null} />
                      </TableCell>
                      <TableCell className="whitespace-nowrap tabular-nums">
                        {apc ?? (
                          <span className="text-[var(--muted-foreground)]">—</span>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
            {journalPages > 1 && (
              <CardPager
                page={journalPage}
                pages={journalPages}
                total={journals.length}
                onPage={setJournalPage}
                label="journals"
              />
            )}
          </CollapsibleCard>
        )}
      </div>
    </div>
  );
}
