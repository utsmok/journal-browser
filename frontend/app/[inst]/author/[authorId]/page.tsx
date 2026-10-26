"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import { DealBadge, OaStatusChip, OaTypeBadge } from "@/components/badges";
import { CollapsibleCard } from "@/components/collapsible-card";
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
import { useInstitution } from "@/hooks/use-institution";
import {
  errorMessage,
  fetchAuthor,
  type AuthorProfile,
  type AuthorSimilarJournal,
  type StatsYear,
} from "@/lib/api";
import { cn } from "@/lib/utils";

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
        <ul className="flex min-w-0 items-center gap-1">
          {sections.map((s) => (
            <li key={s.id}>
              <a
                href={`#${s.id}`}
                aria-current={active === s.id ? "true" : undefined}
                onClick={(e) => {
                  e.preventDefault();
                  document
                    .getElementById(s.id)
                    ?.scrollIntoView({ behavior: "smooth" });
                }}
                className={cn(
                  "inline-block whitespace-nowrap rounded px-2 py-1 text-sm underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white",
                  active === s.id
                    ? "font-medium text-white underline"
                    : "text-white/80",
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
      works_count_source: "pure",
      oa_gold: y.gold,
      oa_hybrid: y.hybrid,
      oa_green: y.green,
      oa_bronze: y.bronze,
      oa_diamond: 0,
      oa_closed: y.closed,
    }));
}

export default function AuthorPage() {
  const params = useParams<{ authorId: string }>();
  const inst = useInstitution();
  const authorId = params?.authorId
    ? decodeURIComponent(params.authorId)
    : undefined;
  const backHref = useLastSearchHref();
  const { data, isPending, isError, error } = useQuery({
    queryKey: ["author", inst, authorId ?? ""],
    queryFn: () => fetchAuthor(inst, authorId ?? ""),
    enabled: Boolean(authorId),
  });

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
          <ArrowLeft aria-hidden className="size-4" /> Back to search
        </Link>
      </div>
    );

  const { author, oa_by_year, journals, topics, similar, alternatives, works } =
    data;
  const trendStats = toStatsYear(oa_by_year);
  const hasSimilar =
    similar.all.length > 0 ||
    similar.deals.length > 0 ||
    similar.diamond.length > 0;

  // One nav entry per rendered section, in DOM order.
  const sections = [
    ...(trendStats.length > 0
      ? [{ id: "oa-over-time", label: "Open access over time" }]
      : []),
    ...(journals.length > 0 ? [{ id: "journals", label: "Where they publish" }] : []),
    ...(topics.length > 0 ? [{ id: "topics", label: "Topics" }] : []),
    ...(hasSimilar ? [{ id: "next", label: "Where to publish next" }] : []),
    ...(alternatives.length > 0
      ? [{ id: "alternatives", label: "Alternatives" }]
      : []),
    ...(works.length > 0 ? [{ id: "publications", label: "Publications" }] : []),
  ];

  return (
    <>
      <SectionNav sections={sections} />
      <div className="mx-auto max-w-screen-2xl px-4 py-10">
        <header className="mb-8">
          <h1 className="text-3xl font-bold">{author.name}</h1>
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
            <span className="text-sm text-[var(--muted-foreground)]">
              {author.n_works.toLocaleString("en")}{" "}
              {author.n_works === 1 ? "work" : "works"}
            </span>
          </div>
          {(author.orcid || author.openalex_author_id || author.openaire_person_id) && (
            <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
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
            <CollapsibleCard
              id="journals"
              title="Where they publish"
              contentClassName="text-sm"
            >
              <Table>
                <caption className="sr-only">
                  Journals this author publishes in
                </caption>
                <TableHeader>
                  <TableRow>
                    <TableHead>Journal</TableHead>
                    <TableHead className="text-right">Works</TableHead>
                    <TableHead>Access</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {journals.map((j) => (
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
            </CollapsibleCard>
          )}

          {topics.length > 0 && (
            <CollapsibleCard
              id="topics"
              title="Topics"
              contentClassName="flex flex-wrap gap-1.5"
            >
              {topics.map((t) => (
                <Badge
                  key={t.name}
                  variant="muted"
                  className="font-normal normal-case"
                  title={`${t.n.toLocaleString("en")} ${
                    t.n === 1 ? "work" : "works"
                  }`}
                >
                  {t.name}
                </Badge>
              ))}
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
                  { key: "all", heading: "Most similar to their journals" },
                  { key: "deals", heading: "Similar with a deal" },
                  { key: "diamond", heading: "Diamond options" },
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
                  Journals where this author publishes paywalled, with open
                  access venues covering the same territory.
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
                      {alt.n_works.toLocaleString("en")}{" "}
                      {alt.n_works === 1 ? "work" : "works"}
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
            >
              <Table>
                <caption className="sr-only">
                  This author&apos;s publications
                </caption>
                <TableHeader>
                  <TableRow>
                    <TableHead>Year</TableHead>
                    <TableHead>Title</TableHead>
                    <TableHead>Journal</TableHead>
                    <TableHead>Access</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {works.map((w) => {
                    const href = doiHref(w.doi);
                    return (
                      <TableRow key={w.pure_uuid}>
                        <TableCell className="whitespace-nowrap tabular-nums">
                          {w.year}
                        </TableCell>
                        <TableCell className="min-w-0 font-medium">
                          {href ? (
                            <External href={href}>{w.title}</External>
                          ) : (
                            w.title
                          )}
                        </TableCell>
                        <TableCell>
                          {w.journal_issn_l ? (
                            <Link
                              href={`/${inst}/journals/${w.journal_issn_l}`}
                              className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                            >
                              {w.journal_title || w.journal_issn_l}
                            </Link>
                          ) : (
                            <span className="text-[var(--muted-foreground)]">—</span>
                          )}
                        </TableCell>
                        <TableCell>
                          <OaStatusChip status={w.oa_status} />
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
              {works.length >= 200 && (
                <p className="mt-3 text-xs text-[var(--muted-foreground)]">
                  Showing the 200 most recent publications.
                </p>
              )}
            </CollapsibleCard>
          )}
        </div>
      </div>
    </>
  );
}
