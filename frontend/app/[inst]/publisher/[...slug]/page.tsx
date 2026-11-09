"use client";

import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import { DealBadge, OaStatusChip, OaTypeBadge, QuartileBadge } from "@/components/badges";
import { CardPager } from "@/components/card-pager";
import { CollapsibleCard } from "@/components/collapsible-card";
import { GapCsvButton } from "@/components/gap-csv-button";
import { OaCompositionBar, OaCompositionLegend } from "@/components/oa-composition";
import { OaTrend } from "@/components/oa-trend";
import { UtAuthorLine } from "@/components/ut-author-line";
import { BackLink } from "@/components/back-link";
import { DetailSkeleton, ErrorPanel } from "@/components/states";
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
  encodeNamePath,
  type DealOut,
  type PublisherDetailResponse,
  type PublisherListItem,
} from "@/lib/api";
import { formatEur, journalApcText } from "@/lib/format";
import { dealLinkLabel, displayPublisherName, orderedDealLinks } from "@/lib/deal-links";

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
        <span className="font-medium">
          {displayPublisherName(deal.publisher_name) || "Open access deal"}
        </span>
        {deal.covers_in_group != null && (
          <span className="text-xs text-[var(--muted-foreground)]">
            covers {deal.covers_in_group} {deal.covers_in_group === 1 ? "journal" : "journals"} in
            this group
          </span>
        )}
        {deal.duration_text && (
          <span className="text-xs text-[var(--muted-foreground)]">{deal.duration_text}</span>
        )}
        {deal.corresponding_authors_only && (
          <span className="text-xs text-[var(--muted-foreground)]">corresponding authors only</span>
        )}
        {conditionsUrl && (
          <a
            href={conditionsUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-[var(--primary-text)] underline-offset-2 hover:underline"
          >
            {deal.links?.length ? dealLinkLabel(orderedDealLinks(deal.links)[0]) : "Contract"}{" "}
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
                ? `€${formatEur(min)}–${formatEur(max)}`
                : `€${formatEur(max ?? (min as number))}`}
            </p>
            <p className="mt-1 text-xs text-[var(--muted-foreground)]">
              APC known for {n_journals} {n_journals === 1 ? "journal" : "journals"}; publisher list
              prices and OpenAPC ranges combined.
            </p>
          </>
        )}
      </div>
    </div>
  );
}

type UtAuthorship = PublisherDetailResponse["ut_authorship"];
type UtAuthorRow = UtAuthorship["top_authors"][number];
type OpenalexOnly = PublisherDetailResponse["openalex_only"];

/** Who at this institution authors the publisher's journals' works:
 * distinct works per faculty and research group, plus the most prolific
 * UT authors. */
function UtAuthorshipCard({ authorship, inst }: { authorship: UtAuthorship; inst: string }) {
  const empty =
    authorship.faculties.length === 0 &&
    authorship.research_groups.length === 0 &&
    authorship.top_authors.length === 0;
  return (
    <CollapsibleCard
      id="ut-authorship"
      title="UT authorship"
      description={
        <p className="text-sm text-[var(--muted-foreground)]">
          Distinct works with UT authors: {authorship.n_ut_works.toLocaleString("en")} of the works
          counted across this publisher&apos;s journals.
        </p>
      }
      contentClassName="space-y-5 text-sm"
    >
      {empty ? (
        <p className="text-[var(--muted-foreground)]">
          No UT-authorship records for this publisher.
        </p>
      ) : (
        <>
          {(
            [
              { heading: "Faculties", rows: authorship.faculties },
              { heading: "Research groups", rows: authorship.research_groups },
            ] as const
          ).map(
            (t) =>
              t.rows.length > 0 && (
                <div key={t.heading}>
                  <h3 className="mb-1 text-sm font-semibold">{t.heading}</h3>
                  <Table>
                    <caption className="sr-only">
                      Distinct works with UT authors per{" "}
                      {t.heading === "Faculties" ? "faculty" : "research group"}
                    </caption>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Name</TableHead>
                        <TableHead className="text-right">Works</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {t.rows.map((row) => (
                        <TableRow key={row.name}>
                          <TableCell className="font-medium">{row.name}</TableCell>
                          <TableCell className="text-right tabular-nums">
                            {row.works.toLocaleString("en")}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ),
          )}
          {authorship.top_authors.length > 0 && (
            <div>
              <h3 className="mb-1 text-sm font-semibold">Top authors</h3>
              <Table>
                <caption className="sr-only">
                  Most prolific UT authors across this publisher&apos;s journals
                </caption>
                <TableHeader>
                  <TableRow>
                    <TableHead>Author</TableHead>
                    <TableHead className="text-right">Works</TableHead>
                    <TableHead>Affiliation</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {authorship.top_authors.map((a: UtAuthorRow) => (
                    <TableRow key={a.pure_uuid}>
                      <TableCell className="font-medium">
                        <Link
                          href={`/${inst}/author/${a.pure_uuid}`}
                          className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                        >
                          {a.name}
                        </Link>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {a.works.toLocaleString("en")}
                      </TableCell>
                      <TableCell>
                        <span className="text-[var(--muted-foreground)]">
                          {a.research_group ?? a.faculty ?? "—"}
                        </span>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </>
      )}
    </CollapsibleCard>
  );
}

/** OpenAlex works attributed to this publisher's journals that match no
 * Pure record: candidates missing from the research information system. */
function CrisGapsCard({
  openalexOnly,
  inst,
  name,
}: {
  openalexOnly: OpenalexOnly;
  inst: string;
  name: string;
}) {
  const { total, items } = openalexOnly;
  return (
    <CollapsibleCard
      id="cris-gaps"
      title="Not registered in Pure"
      description={
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <p className="text-sm text-[var(--muted-foreground)]">
            OpenAlex attributes {total.toLocaleString("en")} work(s) to this publisher&apos;s
            journals that match no Pure record — likely missing from the research information
            system. Each item lists the UT authors OpenAlex matched to the university roster.
            {total > items.length && ` Showing ${items.length.toLocaleString("en")} most recent.`}
          </p>
          {total > 0 && (
            <GapCsvButton
              href={`/api/v1/${inst}/publishers/${encodeNamePath(name)}/openalex-only.csv`}
            />
          )}
        </div>
      }
      contentClassName="text-sm"
    >
      {total === 0 ? (
        <p className="text-[var(--muted-foreground)]">
          None found — every OpenAlex work here has a Pure record.
        </p>
      ) : (
        <ul className="divide-y divide-[var(--border)]">
          {items.map((w, i) => {
            const href = w.doi ? `https://doi.org/${w.doi}` : null;
            return (
              <li
                key={i}
                className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1 py-2 first:pt-0 last:pb-0"
              >
                {href ? (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex min-w-0 w-full min-[480px]:w-auto min-[480px]:flex-1 items-center gap-1 font-medium text-[var(--primary-text)] underline-offset-2 hover:underline"
                  >
                    {w.title ?? w.doi} <ExternalLink aria-hidden className="size-3.5 shrink-0" />
                  </a>
                ) : (
                  <span className="min-w-0 w-full min-[480px]:w-auto min-[480px]:flex-1 font-medium">
                    {w.title ?? "Untitled"}
                  </span>
                )}
                {w.year != null && (
                  <span className="tabular-nums text-[var(--muted-foreground)]">{w.year}</span>
                )}
                {w.venue && (
                  <span className="min-w-0 text-xs text-[var(--muted-foreground)]">{w.venue}</span>
                )}
                {w.journal_issn_l && (
                  <Link
                    href={`/${inst}/journals/${w.journal_issn_l}`}
                    className="text-xs underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                  >
                    {w.journal_title ?? w.journal_issn_l}
                  </Link>
                )}
                {w.work_type && <span className="text-xs">{w.work_type}</span>}
                <OaStatusChip status={w.oa_status} />
                <UtAuthorLine authors={w.ut_authors} />
              </li>
            );
          })}
        </ul>
      )}
    </CollapsibleCard>
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

  if (isPending) return <DetailSkeleton />;
  if (isError || !data)
    return (
      <ErrorPanel
        message={errorMessage(error)}
        backHref={backHref}
        backLabel="Back to publishers"
      />
    );

  const { publisher, journals, deals, deal_discrepancies, n_discrepancies, works_by_year } = data;
  const journalPages = Math.max(1, Math.ceil(journals.length / PAGE_SIZE));
  const journalRows = journals.slice((journalPage - 1) * PAGE_SIZE, journalPage * PAGE_SIZE);

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <BackLink href={backHref} label="Back to publishers" />
      <header className="mb-6 mt-4">
        <h1 className="text-3xl font-bold text-balance">{displayPublisherName(publisher.name)}</h1>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-[var(--muted-foreground)]">
          <span>
            {publisher.n_journals.toLocaleString("en")}{" "}
            {publisher.n_journals === 1 ? "journal" : "journals"}
          </span>
          <span aria-hidden>·</span>
          <span>
            {publisher.n_works.toLocaleString("en")} {publisher.n_works === 1 ? "work" : "works"}
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
          {publisher.external_ids?.openaccess_nl_slug && (
            <>
              <span aria-hidden>·</span>
              <a
                href={`https://openaccess.nl/en/publisher/${publisher.external_ids.openaccess_nl_slug}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-[var(--primary-text)] underline-offset-2 hover:underline"
                title="Publisher profile on Open Access NL, the Dutch deals registry"
              >
                Open Access NL <ExternalLink aria-hidden className="size-3.5 shrink-0" />
              </a>
            </>
          )}
          {publisher.external_ids?.ror && (
            <>
              <span aria-hidden>·</span>
              <a
                href={publisher.external_ids.ror}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-[var(--primary-text)] underline-offset-2 hover:underline"
                title="Research Organization Registry record for this publisher"
              >
                ROR <ExternalLink aria-hidden className="size-3.5 shrink-0" />
              </a>
            </>
          )}
        </div>
      </header>

      <AggregateCards publisher={publisher} />

      <div className="mt-6 space-y-6">
        {(deals.length > 0 || n_discrepancies > 0) && (
          <CollapsibleCard id="deals" title="Open access deals" contentClassName="text-sm">
            {deals.length > 0 && (
              <ul className="divide-y divide-[var(--border)]">
                {deals.map((deal) => (
                  <DealRow key={deal.id} deal={deal} />
                ))}
              </ul>
            )}
            {n_discrepancies > 0 && (
              <p className="mt-3 border-t border-[var(--border)] pt-3 text-xs text-[var(--muted-foreground)]">
                {n_discrepancies} {n_discrepancies === 1 ? "journal" : "journals"} in this group{" "}
                {n_discrepancies === 1 ? "is" : "are"} covered by another publisher&apos;s deal —
                likely a publisher flip since the contract was signed:
                <ul className="mt-1.5 list-disc space-y-0.5 pl-4">
                  {deal_discrepancies.map((d) => (
                    <li key={d.title ?? d.publisher_name}>
                      {d.title}
                      {d.publisher_name && (
                        <span className="text-[var(--muted-foreground)]">
                          {" "}
                          ({d.publisher_name})
                        </span>
                      )}{" "}
                      — covered by {d.deal_publisher ?? "another publisher"}
                    </li>
                  ))}
                  {n_discrepancies > deal_discrepancies.length && (
                    <li>and {n_discrepancies - deal_discrepancies.length} more</li>
                  )}
                </ul>
              </p>
            )}
          </CollapsibleCard>
        )}

        {publisher.topics.length > 0 && (
          <CollapsibleCard id="topics" title="Topics" contentClassName="flex flex-wrap gap-1.5">
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
          <CollapsibleCard id="journals" title="Journals" contentClassName="text-sm">
            <Table>
              <caption className="sr-only">Journals of this publisher</caption>
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
                        {apc ?? <span className="text-[var(--muted-foreground)]">—</span>}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
            {publisher.n_journals > journals.length && (
              <p className="mt-3 text-xs text-[var(--muted-foreground)]">
                Showing the {journals.length} most publishing of{" "}
                {publisher.n_journals.toLocaleString("en")} journals.{" "}
                <Link
                  href={`/${inst}/journals?publisher=${encodeURIComponent(publisher.name)}`}
                  className="text-[var(--primary-text)] hover:underline"
                >
                  Search all journals of this publisher
                </Link>
              </p>
            )}
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

        <UtAuthorshipCard authorship={data.ut_authorship} inst={inst} />

        {data.openalex_only.available && (
          <CrisGapsCard openalexOnly={data.openalex_only} inst={inst} name={name} />
        )}
      </div>
    </div>
  );
}
