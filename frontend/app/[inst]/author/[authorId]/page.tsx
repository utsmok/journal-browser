"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import { DealBadge, OaStatusChip, OaTypeBadge, PureMatchBadge } from "@/components/badges";
import { CardPager } from "@/components/card-pager";
import { CollapsibleCard } from "@/components/collapsible-card";
import { GapCsvButton } from "@/components/gap-csv-button";
import { OaTrend } from "@/components/oa-trend";
import { UtAuthorLine } from "@/components/ut-author-line";
import { Badge } from "@/components/ui/badge";
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
  errorMessage,
  encodeNamePath,
  fetchAuthor,
  type AuthorProfile,
  type AuthorSimilarJournal,
  type StatsYear,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { workTypeLabel } from "@/lib/work-type";

function External({
  href,
  children,
  className,
}: {
  href: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={cn(
        "inline-flex items-center gap-1 text-[var(--primary-text)] underline-offset-2 hover:underline",
        className,
      )}
    >
      {children} <ExternalLink aria-hidden className="size-3.5 shrink-0" />
    </a>
  );
}

function doiHref(doi: string | null): string | null {
  if (!doi) return null;
  return /^https?:\/\//.test(doi) ? doi : `https://doi.org/${doi}`;
}

/** Small per-row verification links: DOI, OpenAlex, Pure — whichever
 * exist; an empty row (no DOI, no portal record) shows a dash. */
function WorkLinks({
  doi,
  openalexUrl,
  pureUrl,
}: {
  doi: string | null;
  openalexUrl?: string | null;
  pureUrl?: string | null;
}) {
  const links = [
    doi ? { label: "DOI", href: doiHref(doi) ?? "" } : null,
    openalexUrl ? { label: "OpenAlex", href: openalexUrl } : null,
    pureUrl ? { label: "Pure", href: pureUrl } : null,
  ].filter((l): l is { label: string; href: string } => l !== null);
  if (links.length === 0) return <span className="text-[var(--muted-foreground)]">—</span>;
  return (
    <span className="flex flex-wrap gap-x-2 gap-y-0.5 text-xs">
      {links.map((l) => (
        <a
          key={l.label}
          href={l.href}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[var(--primary-text)] underline-offset-2 hover:underline"
        >
          {l.label}
        </a>
      ))}
    </span>
  );
}

/** Neutral small type badge; null renders a dash so columns stay aligned. */
function WorkTypeCell({ workType }: { workType?: string | null }) {
  if (!workType) return <span className="text-[var(--muted-foreground)]">—</span>;
  return (
    <Badge variant="outline" className="font-normal text-[11px] text-[var(--muted-foreground)]">
      {workTypeLabel(workType)}
    </Badge>
  );
}

/** href for "Back to search": the last search this tab ran, else this
 * university's search home (never the global landing). */
function useLastSearchHref(): string {
  const inst = useInstitution();
  const fallback = `/${inst}/`;
  const [href, setHref] = React.useState(fallback);
  React.useEffect(() => {
    setHref(sessionStorage.getItem("jb-last-search") ?? fallback);
  }, [fallback]);
  return href;
}

/** Highlight the id of the topmost section currently in view. */
function useSectionSpy(ids: string[]) {
  const [active, setActive] = React.useState<string | null>(null);
  const key = ids.join(",");
  React.useEffect(() => {
    const els = key
      .split(",")
      .map((id) => document.getElementById(id))
      .filter((el): el is HTMLElement => el !== null);
    if (els.length === 0) return;
    const visible = new Set<Element>();
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) visible.add(entry.target);
          else visible.delete(entry.target);
        }
        // Topmost visible section wins; keep the last one across gaps.
        const top = [...visible].sort(
          (a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top,
        )[0];
        if (top) setActive(top.id);
      },
      // Only the band just below the sticky bar counts as "in view".
      { rootMargin: "-56px 0px -55% 0px" },
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [key]);
  return active;
}

function SectionNav({ sections }: { sections: { id: string; label: string }[] }) {
  const active = useSectionSpy(sections.map((s) => s.id));
  // Muted-foreground/primary-text both fail 4.5:1 on the navy bar, so this
  // nav speaks in white and separates the active item with weight+underline.
  const backHref = useLastSearchHref();
  return (
    <nav
      aria-label="Page sections"
      className="sticky top-0 z-40 border-b border-[var(--border)] bg-[var(--secondary)] text-[var(--secondary-foreground)]"
    >
      <div className="mx-auto flex max-w-screen-2xl items-center gap-3 overflow-x-auto px-4 py-2">
        <Link
          href={backHref}
          className="inline-flex shrink-0 items-center gap-1 text-sm text-white/80 hover:text-white"
        >
          <ArrowLeft aria-hidden className="size-4" /> Back to search
        </Link>
        <span aria-hidden className="h-4 w-px shrink-0 bg-[var(--border)]" />
        {/* Wrap instead of a single clipped line: long section lists stay
            fully reachable on narrow screens. */}
        <ul className="flex min-w-0 flex-wrap items-center gap-1">
          {sections.map((s) => (
            <li key={s.id}>
              <a
                href={`#${s.id}`}
                aria-current={active === s.id ? "true" : undefined}
                onClick={(e) => {
                  e.preventDefault();
                  document.getElementById(s.id)?.scrollIntoView({ behavior: "smooth" });
                }}
                className={cn(
                  "inline-block whitespace-nowrap rounded px-2 py-1 text-sm underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white",
                  active === s.id ? "font-medium text-white underline" : "text-white/80",
                )}
              >
                {s.label}
              </a>
            </li>
          ))}
        </ul>
      </div>
    </nav>
  );
}

/** Chip cloud cap before the "+N more" expander. */
const TOPICS_LIMIT = 8;

/** One candidate venue: journal link, access + deal badges, similarity %. */
function SimilarRow({ inst, s }: { inst: string; s: AuthorSimilarJournal }) {
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
        title="Similarity to this author's publishing profile"
      >
        {(s.score * 100).toFixed(1)}% match
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
  const params = useParams<{ authorId: string }>();
  const inst = useInstitution();
  const authorId = params?.authorId ? decodeURIComponent(params.authorId) : undefined;
  const backHref = useLastSearchHref();
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

  if (isPending) return <DetailSkeleton />;
  if (isError || !data) return <ErrorPanel message={errorMessage(error)} backHref={backHref} />;

  const { author, oa_by_year, journals, topics, similar, alternatives, works } = data;
  const journalPages = Math.max(1, Math.ceil(journals.length / PAGE_SIZE));
  const workPages = Math.max(1, Math.ceil(works.length / PAGE_SIZE));
  const journalRows = journals.slice((journalPage - 1) * PAGE_SIZE, journalPage * PAGE_SIZE);
  const workRows = works.slice((workPage - 1) * PAGE_SIZE, workPage * PAGE_SIZE);
  const trendStats = toStatsYear(oa_by_year).filter(
    (s) =>
      (year_from === undefined || s.year >= year_from) &&
      (year_to === undefined || s.year <= year_to),
  );
  const hasSimilar =
    similar.all.length > 0 || similar.deals.length > 0 || similar.diamond.length > 0;

  // One nav entry per rendered section, in DOM order.
  const sections = [
    ...(trendStats.length > 0 ? [{ id: "oa-over-time", label: "Open access over time" }] : []),
    ...(journals.length > 0 ? [{ id: "journals", label: "Where they publish" }] : []),
    ...(topics.length > 0 ? [{ id: "topics", label: "Topics" }] : []),
    ...(hasSimilar ? [{ id: "next", label: "Where to publish next" }] : []),
    ...(alternatives.length > 0 ? [{ id: "alternatives", label: "Alternatives" }] : []),
    ...(works.length > 0 ? [{ id: "publications", label: "Publications" }] : []),
    ...(data.openalex_only.available ? [{ id: "openalex-only", label: "Not linked in Pure" }] : []),
  ];

  return (
    <>
      <SectionNav sections={sections} />
      <div className="mx-auto max-w-screen-2xl px-4 py-10">
        <header className="mb-8">
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
              <Badge variant="muted" className="font-normal">
                {author.faculty}
              </Badge>
            )}
            {author.research_group && (
              <Badge variant="muted" className="font-normal">
                {author.research_group}
              </Badge>
            )}
            {author.institute && (
              <Badge variant="muted" className="font-normal">
                {author.institute}
              </Badge>
            )}
            <span className="text-sm text-[var(--muted-foreground)]">
              {author.n_works.toLocaleString("en")} {author.n_works === 1 ? "work" : "works"}
            </span>
          </div>
          {(author.orcid ||
            author.openalex_author_id ||
            author.openaire_person_id ||
            author.people ||
            author.research_portal_url) && (
            <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
              {author.people && <External href={author.people.url}>People page</External>}
              {author.research_portal_url && (
                <External href={author.research_portal_url}>Research portal</External>
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

        <div className="space-y-6">
          {trendStats.length > 0 && (
            <CollapsibleCard id="oa-over-time" title="Open access over time">
              <OaTrend stats={trendStats} />
            </CollapsibleCard>
          )}

          {journals.length > 0 && (
            <CollapsibleCard id="journals" title="Where they publish" contentClassName="text-sm">
              <Table>
                <caption className="sr-only">Journals this author publishes in</caption>
                <TableHeader>
                  <TableRow>
                    <TableHead>Journal</TableHead>
                    <TableHead className="text-right">Works</TableHead>
                    <TableHead>Access</TableHead>
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
                  label="journals"
                />
              )}
            </CollapsibleCard>
          )}

          {topics.length > 0 && (
            <CollapsibleCard
              id="topics"
              title="Topics"
              contentClassName="flex flex-wrap items-center gap-1.5"
            >
              {(allTopics ? topics : topics.slice(0, TOPICS_LIMIT)).map((t) => (
                <Badge
                  key={t.name}
                  variant="muted"
                  className="font-normal normal-case"
                  title={`${t.n.toLocaleString("en")} ${t.n === 1 ? "work" : "works"}`}
                >
                  {t.name}
                </Badge>
              ))}
              {topics.length > TOPICS_LIMIT && (
                <button
                  type="button"
                  className="text-sm text-[var(--muted-foreground)] underline-offset-2 hover:underline"
                  aria-expanded={allTopics}
                  onClick={() => setAllTopics((v) => !v)}
                >
                  {allTopics ? "Show less" : `+${topics.length - TOPICS_LIMIT} more`}
                </button>
              )}
            </CollapsibleCard>
          )}

          {hasSimilar && (
            <CollapsibleCard
              id="next"
              title="Where to publish next"
              contentClassName="space-y-5 text-sm"
            >
              {(
                [
                  { key: "all", heading: "Most similar" },
                  { key: "deals", heading: "Covered by a deal" },
                  { key: "diamond", heading: "Diamond open access" },
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
              title="Alternatives for paywalled venues"
              contentClassName="space-y-5 text-sm"
              description={
                <p className="text-sm text-[var(--muted-foreground)]">
                  Each entry is a paywalled journal this author published in, with its most similar
                  open access journals below it.
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
                      {alt.n_works.toLocaleString("en")} {alt.n_works === 1 ? "work" : "works"}
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
              title="Publications"
              contentClassName="text-sm"
              description={
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                  {data.openalex_only_count != null && (
                    <p className="text-sm text-[var(--muted-foreground)]">
                      {data.openalex_only_count.toLocaleString("en")} more work(s) found in OpenAlex
                      but not linked to this author in Pure are listed under &ldquo;Not linked in
                      Pure&rdquo; below.
                    </p>
                  )}
                  <GapCsvButton
                    href={`/api/v1/${inst}/authors/${encodeURIComponent(author.pure_uuid)}/works.csv?scope=canon${yearQuery("&", year_from, year_to)}`}
                  />
                </div>
              }
            >
              <Table>
                <caption className="sr-only">This author&apos;s publications</caption>
                <TableHeader>
                  <TableRow>
                    <TableHead>Year</TableHead>
                    <TableHead>Title</TableHead>
                    <TableHead>Published in</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Access</TableHead>
                    <TableHead>Links</TableHead>
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
                  label="publications"
                />
              )}
              {works.length >= 200 && (
                <p className="mt-3 text-xs text-[var(--muted-foreground)]">
                  Showing the 200 most recent publications.
                </p>
              )}
            </CollapsibleCard>
          )}

          {data.openalex_only.available && (
            <CollapsibleCard
              id="openalex-only"
              title="Not linked in Pure (found in OpenAlex)"
              description={
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                  <p className="text-sm text-[var(--muted-foreground)]">
                    {data.openalex_only.total.toLocaleString("en")} found in OpenAlex but not linked
                    in Pure; {data.openalex_only.likely_missing.toLocaleString("en")} likely
                    missing.
                    {data.openalex_only.total > data.openalex_only.items.length &&
                      ` Showing ${data.openalex_only.items.length.toLocaleString("en")} most recent.`}
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
                <p className="text-[var(--muted-foreground)]">
                  None found — every OpenAlex work attributed to this author has a Pure record.
                </p>
              ) : (
                <Table>
                  <caption className="sr-only">Works missing from Pure</caption>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Year</TableHead>
                      <TableHead>Title</TableHead>
                      <TableHead>Published in</TableHead>
                      <TableHead>Publisher</TableHead>
                      <TableHead>Type</TableHead>
                      <TableHead>Access</TableHead>
                      <TableHead>Links</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.openalex_only.items.map((w, idx) => {
                      const href = doiHref(w.doi ?? null) ?? w.openalex_url ?? null;
                      return (
                        <TableRow key={`${w.openalex_id ?? w.title ?? "work"}-${idx}`}>
                          <TableCell className="whitespace-nowrap tabular-nums">{w.year}</TableCell>
                          <TableCell className="min-w-0 font-medium">
                            {href ? (
                              <External href={href}>{w.title ?? w.doi ?? w.openalex_id}</External>
                            ) : (
                              (w.title ?? "Untitled")
                            )}
                            <Badge
                              variant="outline"
                              className="ml-2 font-normal text-[11px] text-[var(--muted-foreground)]"
                              title="Attributed by OpenAlex only; not in the university's Pure research information system"
                            >
                              OpenAlex only
                            </Badge>
                            <PureMatchBadge match={w.pure_match} url={w.pure_match_url} />
                            <UtAuthorLine authors={w.ut_authors} />
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
                            {w.publisher_name ? (
                              <Link
                                href={`/${inst}/publisher/${encodeNamePath(w.publisher_name)}`}
                                className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                              >
                                {w.publisher_name}
                              </Link>
                            ) : (
                              <span className="text-[var(--muted-foreground)]">—</span>
                            )}
                          </TableCell>
                          <TableCell>
                            <WorkTypeCell workType={w.work_type} />
                          </TableCell>
                          <TableCell>
                            <OaStatusChip status={w.oa_status} />
                          </TableCell>
                          <TableCell>
                            <WorkLinks doi={w.doi ?? null} openalexUrl={w.openalex_url} />
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              )}
            </CollapsibleCard>
          )}
        </div>
      </div>
    </>
  );
}
