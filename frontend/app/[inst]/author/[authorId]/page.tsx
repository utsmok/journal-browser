"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import { DealBadge, OaStatusChip, OaTypeBadge } from "@/components/badges";
import { CardPager } from "@/components/card-pager";
import { orgTypeCssVar } from "@/components/collaborations/labels";
import { CollapsibleCard } from "@/components/collapsible-card";
import { DetailKpiStrip } from "@/components/detail-kpi-strip";
import {
  doiHref,
  External,
  GapEntryTableRows,
  WorkLinks,
  WorkTypeCell,
} from "@/components/gap-entries";
import { GapCsvButton } from "@/components/gap-csv-button";
import { SectionNav, useLastDirectoryHref } from "@/components/journal/section-nav";
import { OaTrend } from "@/components/oa-trend";
import { SourceNote } from "@/components/source-note";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DetailSkeleton, ErrorPanel } from "@/components/states";
import { useInstitution } from "@/hooks/use-institution";
import { useYearRange, yearQuery } from "@/hooks/use-year-filter";
import {
  encodeNamePath,
  errorMessage,
  fetchAuthor,
  type AuthorProfile,
  type AuthorSimilarJournal,
  type StatsYear,
} from "@/lib/api";
import { countryName } from "@/lib/format";
import { entriesTotal, toGapEntries } from "@/lib/gap-entries";

/** Chip cloud cap before the "+N more" expander. */
const TOPICS_LIMIT = 8;

/** One candidate venue: journal link, access + deal badges, similarity %. */
function SimilarRow({ inst, s }: { inst: string; s: AuthorSimilarJournal }) {
  const t = useTranslations("authors");
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-sm first:pt-0 last:pb-0">
      <Link
        href={`/${inst}/journals/${s.issn_l}`}
        className="font-medium underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
      >
        {s.title || s.issn_l}
      </Link>
      <OaTypeBadge oaType={s.oa_type} />
      {s.deal_covered && <DealBadge covered />}
      <span
        className="ml-auto text-xs tabular-nums text-[var(--muted-foreground)]"
        title={t("detail.matchScoreTitle")}
      >
        {t("detail.matchScore", { score: (s.score * 100).toFixed(1) })}
      </span>
    </li>
  );
}

/** Map the author's per-year OA counts onto the shared trend chart shape. */
function toStatsYear(oa_by_year: AuthorProfile["oa_by_year"]): StatsYear[] {
  return [...oa_by_year]
    .sort((a, b) => a.year - b.year)
    .map((y) => ({
      year: y.year,
      works_count: y.total,
      works_count_source: "pure_canon",
      oa_gold: y.gold,
      oa_hybrid: y.hybrid,
      oa_green: y.green,
      oa_bronze: y.bronze,
      oa_diamond: y.diamond ?? 0,
      oa_closed: y.closed,
    }));
}

export default function AuthorPage() {
  const t = useTranslations("authors");
  const tc = useTranslations("common");
  const params = useParams<{ authorId: string }>();
  const inst = useInstitution();
  const authorId = params?.authorId ? decodeURIComponent(params.authorId) : undefined;
  const backHref = useLastDirectoryHref("jb-last-authors", `/${inst}/author`);
  const { year_from, year_to } = useYearRange();
  const { data, isPending, isError, error } = useQuery({
    queryKey: ["author", inst, authorId ?? "", year_from ?? null, year_to ?? null],
    queryFn: () => fetchAuthor(inst, authorId ?? "", { year_from, year_to }),
    enabled: Boolean(authorId),
  });

  // Per-card pagination; back to page 1 when another author is opened.
  const PAGE_SIZE = 20;
  const [journalPage, setJournalPage] = React.useState(1);
  const [workPage, setWorkPage] = React.useState(1);
  const [allTopics, setAllTopics] = React.useState(false);
  React.useEffect(() => {
    setJournalPage(1);
    setWorkPage(1);
    setAllTopics(false);
  }, [authorId]);

  if (isPending)
    return (
      <DetailSkeleton
        sections={[t("sections.oaOverTime"), t("sections.journals"), t("sections.publications")]}
      />
    );
  if (isError || !data) return <ErrorPanel message={errorMessage(tc, error)} backHref={backHref} />;

  const { author, oa_by_year, journals, topics, similar, alternatives, works, top_partners } = data;
  const partners = top_partners ?? [];
  const journalPages = Math.max(1, Math.ceil(journals.length / PAGE_SIZE));
  const workPages = Math.max(1, Math.ceil(works.length / PAGE_SIZE));
  const journalRows = journals.slice((journalPage - 1) * PAGE_SIZE, journalPage * PAGE_SIZE);
  const workRows = works.slice((workPage - 1) * PAGE_SIZE, workPage * PAGE_SIZE);
  const trendStats = toStatsYear(oa_by_year).filter(
    (s) =>
      (year_from === undefined || s.year >= year_from) &&
      (year_to === undefined || s.year <= year_to),
  );
  const gapEntries = toGapEntries(data.openalex_only.items);
  const gapShownTotal = entriesTotal(data.openalex_only);
  const hasSimilar =
    similar.all.length > 0 || similar.deals.length > 0 || similar.diamond.length > 0;

  // One nav entry per rendered section, in DOM order.
  const sections = [
    ...(trendStats.length > 0 ? [{ id: "oa-over-time", label: t("sections.oaOverTime") }] : []),
    ...(journals.length > 0 ? [{ id: "journals", label: t("sections.journals") }] : []),
    ...(topics.length > 0 ? [{ id: "topics", label: t("sections.topics") }] : []),
    ...(partners.length > 0 ? [{ id: "partners", label: t("sections.partners") }] : []),
    ...(hasSimilar ? [{ id: "next", label: t("sections.publishNext") }] : []),
    ...(alternatives.length > 0 ? [{ id: "alternatives", label: t("sections.alternatives") }] : []),
    ...(works.length > 0 ? [{ id: "publications", label: t("sections.publications") }] : []),
    ...(data.openalex_only.available
      ? [{ id: "openalex-only", label: t("sections.notInPure") }]
      : []),
  ];

  return (
    <>
      <SectionNav
        sections={sections}
        backFallback={`/${inst}/author`}
        backStorageKey="jb-last-authors"
        backLabel={t("detail.backToSearch")}
      />
      <div className="mx-auto max-w-screen-2xl px-4 py-10">
        <header className="mb-6">
          <div className="flex items-center gap-4">
            {author.people?.has_photo && (
              // eslint-disable-next-line @next/next/no-img-element -- same-origin API bytes, no optimization pipeline wanted
              <img
                src={`/api/v1/${inst}/authors/${encodeURIComponent(authorId ?? "")}/avatar`}
                alt={author.name}
                width={72}
                height={72}
                className="size-[72px] shrink-0 rounded-full object-cover"
              />
            )}
            <div>
              <h1 className="text-3xl font-bold">{author.name}</h1>
              {author.people?.canonical_name &&
                author.people.canonical_name.toLowerCase() !== author.name.toLowerCase() && (
                  <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                    {author.people.canonical_name}
                  </p>
                )}
            </div>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {author.faculty && (
              <Link
                href={`/${inst}/orgunit/faculty/${encodeNamePath(author.faculty)}`}
                className="inline-flex items-center rounded-md border border-[var(--border)] bg-[var(--muted)] px-2.5 py-0.5 text-xs text-[var(--foreground)] underline-offset-2 hover:border-[var(--primary)] hover:text-[var(--primary-text)] hover:underline"
              >
                {author.faculty}
              </Link>
            )}
            {author.research_group && (
              <Link
                href={`/${inst}/orgunit/group/${encodeNamePath(author.research_group)}`}
                className="inline-flex items-center rounded-md border border-[var(--border)] bg-[var(--muted)] px-2.5 py-0.5 text-xs text-[var(--foreground)] underline-offset-2 hover:border-[var(--primary)] hover:text-[var(--primary-text)] hover:underline"
              >
                {author.research_group}
              </Link>
            )}
            {author.institute && (
              <Link
                href={`/${inst}/orgunit/institute/${encodeNamePath(author.institute)}`}
                className="inline-flex items-center rounded-md border border-[var(--border)] bg-[var(--muted)] px-2.5 py-0.5 text-xs text-[var(--foreground)] underline-offset-2 hover:border-[var(--primary)] hover:text-[var(--primary-text)] hover:underline"
              >
                {author.institute}
              </Link>
            )}
          </div>
          {(author.orcid ||
            author.openalex_author_id ||
            author.openaire_person_id ||
            author.people ||
            author.research_portal_url) && (
            <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
              {author.people && (
                <External href={author.people.url}>{t("detail.peoplePage")}</External>
              )}
              {author.research_portal_url && (
                <External href={author.research_portal_url}>{t("detail.researchPortal")}</External>
              )}
              {author.orcid && (
                <External href={`https://orcid.org/${author.orcid}`}>ORCID</External>
              )}
              {author.openalex_author_id && (
                <External href={`https://openalex.org/${author.openalex_author_id}`}>
                  OpenAlex
                </External>
              )}
              {author.openaire_person_id && (
                <External
                  href={`https://explore.openaire.eu/search/person?personId=${author.openaire_person_id}`}
                >
                  OpenAIRE
                </External>
              )}
            </p>
          )}
        </header>

        <DetailKpiStrip
          items={[
            { label: t("results.colWorks"), value: author.n_works.toLocaleString("en") },
            { label: t("sections.journals"), value: journals.length.toLocaleString("en") },
            { label: t("sections.topics"), value: topics.length.toLocaleString("en") },
            { label: t("sections.partners"), value: partners.length.toLocaleString("en") },
          ]}
        />

        <div className="space-y-6">
          {trendStats.length > 0 && (
            <CollapsibleCard id="oa-over-time" title={t("sections.oaOverTime")}>
              <OaTrend stats={trendStats} />
            </CollapsibleCard>
          )}

          {journals.length > 0 && (
            <CollapsibleCard
              id="journals"
              title={t("sections.journals")}
              contentClassName="text-sm"
            >
              <Table>
                <caption className="sr-only">{t("tables.journalsCaption")}</caption>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("tables.colJournal")}</TableHead>
                    <TableHead className="text-right">{t("tables.colWorks")}</TableHead>
                    <TableHead>{t("tables.colAccess")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {journalRows.map((j) => (
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
                        {j.n_works.toLocaleString("en")}
                      </TableCell>
                      <TableCell>
                        <OaTypeBadge oaType={j.oa_type} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {journalPages > 1 && (
                <CardPager
                  page={journalPage}
                  pages={journalPages}
                  total={journals.length}
                  onPage={setJournalPage}
                  label={t("detail.pagerJournals")}
                />
              )}
            </CollapsibleCard>
          )}

          {topics.length > 0 && (
            <CollapsibleCard
              id="topics"
              title={t("sections.topics")}
              contentClassName="flex flex-wrap items-center gap-1.5"
            >
              {(allTopics ? topics : topics.slice(0, TOPICS_LIMIT)).map((topic) => (
                <Link
                  key={topic.name}
                  href={`/${inst}/author?topic=${encodeURIComponent(topic.name)}`}
                  className="inline-flex items-center rounded-md border border-[var(--border)] bg-[var(--muted)] px-2.5 py-1 text-xs text-[var(--foreground)] underline-offset-2 hover:border-[var(--primary)] hover:text-[var(--primary-text)] hover:underline"
                  title={t("worksCount", { count: topic.n })}
                >
                  {topic.name}
                </Link>
              ))}
              {topics.length > TOPICS_LIMIT && (
                <button
                  type="button"
                  className="text-sm text-[var(--muted-foreground)] underline-offset-2 hover:underline"
                  aria-expanded={allTopics}
                  onClick={() => setAllTopics((v) => !v)}
                >
                  {allTopics
                    ? t("detail.showLess")
                    : t("detail.showMore", { count: topics.length - TOPICS_LIMIT })}
                </button>
              )}
            </CollapsibleCard>
          )}

          {partners.length > 0 && (
            <CollapsibleCard
              id="partners"
              title={t("sections.partners")}
              contentClassName="text-sm"
            >
              <Table>
                <caption className="sr-only">{t("tables.partnersCaption")}</caption>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("tables.colPartner")}</TableHead>
                    <TableHead>{t("tables.colCountry")}</TableHead>
                    <TableHead className="text-right">{t("tables.colWorks")}</TableHead>
                    <TableHead className="text-right">{t("tables.colOa")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {partners.map((p) => (
                    <TableRow key={p.ror}>
                      <TableCell className="font-medium">
                        <span className="inline-flex items-center gap-2">
                          <span
                            aria-hidden
                            className="inline-block size-2.5 shrink-0 rounded-full"
                            style={{ backgroundColor: orgTypeCssVar(p.org_type) }}
                          />
                          <Link
                            href={`/${inst}/collaborations/${encodeURIComponent(p.ror)}`}
                            className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                          >
                            {p.name}
                          </Link>
                        </span>
                      </TableCell>
                      <TableCell className="text-[var(--muted-foreground)]">
                        {countryName(p.country_code)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {p.works.toLocaleString("en")}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {p.oa_share != null ? `${Math.round(p.oa_share * 100)}%` : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CollapsibleCard>
          )}

          {hasSimilar && (
            <CollapsibleCard
              id="next"
              title={t("sections.publishNext")}
              contentClassName="space-y-5 text-sm"
            >
              {(
                [
                  { key: "all", heading: t("similar.mostSimilar") },
                  { key: "deals", heading: t("similar.dealCovered") },
                  { key: "diamond", heading: t("similar.diamond") },
                ] as const
              ).map(
                (g) =>
                  similar[g.key].length > 0 && (
                    <div key={g.key}>
                      <h3 className="text-sm font-semibold">{g.heading}</h3>
                      <ul className="divide-y divide-[var(--border)]">
                        {similar[g.key].map((s) => (
                          <SimilarRow key={s.issn_l} inst={inst} s={s} />
                        ))}
                      </ul>
                    </div>
                  ),
              )}
            </CollapsibleCard>
          )}

          {alternatives.length > 0 && (
            <CollapsibleCard
              id="alternatives"
              title={t("cards.alternatives")}
              contentClassName="space-y-5 text-sm"
              description={
                <p className="text-sm text-[var(--muted-foreground)]">
                  {t("cards.alternativesIntro")}
                </p>
              }
            >
              {alternatives.map((alt) => (
                <div key={alt.issn_l}>
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <Link
                      href={`/${inst}/journals/${alt.issn_l}`}
                      className="font-semibold underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                    >
                      {alt.title || alt.issn_l}
                    </Link>
                    <span className="text-xs tabular-nums text-[var(--muted-foreground)]">
                      {t("worksCount", { count: alt.n_works })}
                    </span>
                  </div>
                  <ul className="mt-1 divide-y divide-[var(--border)]">
                    {alt.options.map((o) => (
                      <SimilarRow key={o.issn_l} inst={inst} s={o} />
                    ))}
                  </ul>
                </div>
              ))}
            </CollapsibleCard>
          )}

          {works.length > 0 && (
            <CollapsibleCard
              id="publications"
              title={t("sections.publications")}
              contentClassName="text-sm"
              description={
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                  {data.openalex_only_count != null && (
                    <p className="text-sm text-[var(--muted-foreground)]">
                      {t("cards.publicationsIntro", {
                        count: data.openalex_only_count,
                        section: t("sections.notInPure"),
                      })}
                    </p>
                  )}
                  <GapCsvButton
                    href={`/api/v1/${inst}/authors/${encodeURIComponent(author.pure_uuid)}/works.csv?scope=canon${yearQuery("&", year_from, year_to)}`}
                  />
                </div>
              }
            >
              <Table>
                <caption className="sr-only">{t("tables.worksCaption")}</caption>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("tables.colYear")}</TableHead>
                    <TableHead>{t("tables.colTitle")}</TableHead>
                    <TableHead>{t("tables.colVenue")}</TableHead>
                    <TableHead>{t("tables.colType")}</TableHead>
                    <TableHead>{t("tables.colAccess")}</TableHead>
                    <TableHead>{t("tables.colLinks")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {workRows.map((w, idx) => {
                    const href = doiHref(w.doi) ?? w.pure_url ?? w.openalex_url;
                    return (
                      <TableRow key={w.pure_uuid ?? w.doi ?? `oa-${idx}`}>
                        <TableCell className="whitespace-nowrap tabular-nums">{w.year}</TableCell>
                        <TableCell className="min-w-0 font-medium">
                          {href ? <External href={href}>{w.title}</External> : w.title}
                        </TableCell>
                        <TableCell>
                          {w.journal_issn_l ? (
                            <Link
                              href={`/${inst}/journals/${w.journal_issn_l}`}
                              className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                            >
                              {w.journal_title || w.journal_issn_l}
                            </Link>
                          ) : w.journal_title ? (
                            <span>{w.journal_title}</span>
                          ) : (
                            <span className="text-[var(--muted-foreground)]">—</span>
                          )}
                        </TableCell>
                        <TableCell>
                          <WorkTypeCell workType={w.work_type} />
                        </TableCell>
                        <TableCell>
                          <OaStatusChip status={w.oa_status} source={w.oa_status_source} />
                        </TableCell>
                        <TableCell>
                          <WorkLinks
                            doi={w.doi}
                            openalexUrl={w.openalex_url}
                            pureUrl={w.pure_url}
                          />
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
              {workPages > 1 && (
                <CardPager
                  page={workPage}
                  pages={workPages}
                  total={works.length}
                  onPage={setWorkPage}
                  label={t("detail.pagerPublications")}
                />
              )}
              {works.length >= 200 && (
                <p className="mt-3 text-xs text-[var(--muted-foreground)]">
                  {t("cards.publicationsCapped", { count: 200 })}
                </p>
              )}
              <div className="mt-3 border-t border-[var(--border)] pt-3">
                <SourceNote
                  source={tc("sourceNote.howListLabel")}
                  howBuilt={tc("sourceNote.explain.authorWorks")}
                />
              </div>
            </CollapsibleCard>
          )}

          {data.openalex_only.available && (
            <CollapsibleCard
              id="openalex-only"
              title={t("cards.notInPure")}
              description={
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                  <p className="text-sm text-[var(--muted-foreground)]">
                    {t("gap.found", {
                      count: data.openalex_only.total,
                      missing: data.openalex_only.likely_missing,
                    })}{" "}
                    {gapShownTotal > gapEntries.length &&
                      ` ${t("gap.showing", { count: gapEntries.length })}`}
                  </p>
                  {data.openalex_only.total > 0 && (
                    <GapCsvButton
                      href={`/api/v1/${inst}/authors/${encodeURIComponent(author.pure_uuid)}/works.csv?scope=missed${yearQuery("&", year_from, year_to)}`}
                    />
                  )}
                </div>
              }
              contentClassName="text-sm"
            >
              {data.openalex_only.total === 0 ? (
                <p className="text-[var(--muted-foreground)]">{t("gap.none")}</p>
              ) : (
                <Table>
                  <caption className="sr-only">{t("tables.gapCaption")}</caption>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("tables.colYear")}</TableHead>
                      <TableHead>{t("tables.colTitle")}</TableHead>
                      <TableHead>{t("tables.colVenue")}</TableHead>
                      <TableHead>{t("tables.colPublisher")}</TableHead>
                      <TableHead>{t("tables.colType")}</TableHead>
                      <TableHead>{t("tables.colAccess")}</TableHead>
                      <TableHead>{t("tables.colLinks")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    <GapEntryTableRows entries={gapEntries} inst={inst} />
                  </TableBody>
                </Table>
              )}
              <div className="mt-3 border-t border-[var(--border)] pt-3">
                <SourceNote
                  source={tc("sourceNote.howListLabel")}
                  howBuilt={tc("sourceNote.explain.crisGaps")}
                />
              </div>
            </CollapsibleCard>
          )}
        </div>
      </div>
    </>
  );
}
