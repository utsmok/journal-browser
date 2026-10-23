"use client";

import { ArrowLeft, Check, Copy, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import {
  DealBadge,
  OaStatusChip,
  OaTypeBadge,
  QuartileBadge,
} from "@/components/badges";
import { CollapsibleCard } from "@/components/collapsible-card";
import { OaTrend } from "@/components/oa-trend";
import { SourceNote } from "@/components/source-note";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useJournal, useJournalWorks, useSimilar } from "@/hooks/use-api";
import {
  errorMessage,
  type Attribution,
  type DealOut,
  type JournalDetailResponse,
  type OpenalexSource,
  type OpenalexTopic,
} from "@/lib/api";
import { dealLinkLabel, orderedDealLinks } from "@/lib/deal-links";
import { cleanProse, cn } from "@/lib/utils";

type NamedTopic = { display_name?: string };

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

function Metric({ label, value, note }: { label: string; value: string; note?: React.ReactNode }) {
  return (
    <div>
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
      <div className="text-xs font-medium">{label}</div>
      {note && <div className="text-[11px] text-[var(--muted-foreground)]">{note}</div>}
    </div>
  );
}

/** Clipboard write with a brief "Copied" affordance; no alerts. */
function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = React.useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (err) {
      console.error("Clipboard write failed", err);
    }
  };
  return (
    <button
      type="button"
      onClick={copy}
      aria-label={`${copied ? "Copied" : "Copy"} ${label}`}
      title={copied ? "Copied" : "Copy"}
      className="inline-flex size-6 shrink-0 items-center justify-center rounded border border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
    >
      {copied ? (
        <Check aria-hidden className="size-3.5 text-emerald-600" />
      ) : (
        <Copy aria-hidden className="size-3.5" />
      )}
    </button>
  );
}

function CitationCard({ data }: { data: JournalDetailResponse }) {
  const today = new Date().toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
  const title = data.journal.title ?? data.journal.issn_l;
  const citation = `${title}. ${data.journal.publisher_name ?? "Unknown publisher"}. ISSN-L ${data.journal.issn_l}. Available at: ${process.env.NEXT_PUBLIC_SITE_URL ?? "https://journalbrowser.samuelmok.cc"}/journals/${data.journal.issn_l} (accessed ${today})`;
  const issns = Array.from(new Set([`ISSN-L ${data.journal.issn_l}`, ...data.issns.map((i) => `ISSN ${i}`)]));

  return (
    <CollapsibleCard
      id="cite"
      title="Cite this journal"
      contentClassName="space-y-2 text-sm"
    >
        <div className="flex items-start gap-2">
          {/* anywhere (not break-words): only `anywhere` lets the long canonical URL
              count as breakable for the grid column's min-content, so mobile stays 390px. */}
          <p className="min-w-0 flex-1 [overflow-wrap:anywhere]">{citation}</p>
          <CopyButton text={citation} label="citation" />
        </div>
        <ul className="space-y-1 border-t border-[var(--border)] pt-2">
          {issns.map((issn) => (
            <li key={issn} className="flex items-center justify-between gap-2">
              <span className="tabular-nums text-[var(--muted-foreground)]">{issn}</span>
              <CopyButton text={issn.replace(/^ISSN(-L)? /, "")} label={issn} />
            </li>
          ))}
        </ul>
    </CollapsibleCard>
  );
}

function DealPanel({
  id,
  deal,
  attribution,
}: {
  id: string;
  deal: DealOut;
  attribution: Partial<Attribution>;
}) {
  const capNumbers = Object.entries(deal.cap_numbers ?? {}).sort((a, b) =>
    (parseInt(a[0], 10) || 0) - (parseInt(b[0], 10) || 0),
  );
  return (
    <CollapsibleCard
      id={id}
      title={
        <>
          Open access deal
          <DealBadge covered />
          {deal.corresponding_authors_only && (
            <Badge variant="muted">Corresponding authors only</Badge>
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
          {deal.publisher_name} · {deal.duration_text ?? deal.esac_id}
        </p>
      }
      contentClassName="space-y-4 text-sm"
    >
        {deal.summary && <p>{cleanProse(deal.summary)}</p>}
        {deal.conditions_text && (
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
              Cost implication & conditions
            </h3>
            <p className="whitespace-pre-line">{cleanProse(deal.conditions_text)}</p>
          </div>
        )}
        {(deal.cap_text || capNumbers.length > 0) && (
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
              Article caps
            </h3>
            {deal.cap_text && <p className="whitespace-pre-line">{cleanProse(deal.cap_text)}</p>}
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
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
              Included article types
            </h3>
            <p>{cleanProse(deal.article_types_text)}</p>
          </div>
        )}
        {deal.workflow_text && (
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
              Workflow
            </h3>
            <p>{cleanProse(deal.workflow_text)}</p>
          </div>
        )}
        <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-[var(--border)] pt-3">
          {deal.links?.length
            ? orderedDealLinks(deal.links).map((link) => (
                <External key={`${link.category}-${link.url}`} href={link.url}>
                  {dealLinkLabel(link)}
                </External>
              ))
            : (
              // Old backend: no links[] yet; fall back to the flat URL fields.
              <>
                {deal.openaccess_nl_url && (
                  <External href={deal.openaccess_nl_url}>
                    openaccess.nl deal page
                  </External>
                )}
                {deal.contract_url && (
                  <External href={deal.contract_url}>Contract</External>
                )}
                {deal.jct_data_url && (
                  <External href={deal.jct_data_url}>JCT data</External>
                )}
              </>
            )}
          <SourceNote {...attribution} codes={attribution.caveat_codes} />
        </div>
    </CollapsibleCard>
  );
}

const WORKS_PAGE_SIZE = 20;

function doiHref(doi: string | null): string | null {
  if (!doi) return null;
  return /^https?:\/\//.test(doi) ? doi : `https://doi.org/${doi}`;
}

/** Compact numbered pagination window: first, last and current ± 1 with gaps. */
function pageWindow(current: number, pages: number): (number | "…")[] {
  const wanted = [...new Set([1, pages, current - 1, current, current + 1])]
    .filter((p) => p >= 1 && p <= pages)
    .sort((a, b) => a - b);
  const out: (number | "…")[] = [];
  for (const p of wanted) {
    if (out.length && p - (out.at(-1) as number) > 1) out.push("…");
    out.push(p);
  }
  return out;
}

/** Twente works in this journal, paginated from the /works endpoint. */
function PublicationsCard({
  issnL,
  title,
  openalex,
  worksNote,
}: {
  issnL: string;
  title: string;
  openalex: OpenalexSource | null;
  worksNote: Partial<Attribution>;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const pParam = parseInt(searchParams.get("page") ?? "", 10);
  const requested = Number.isFinite(pParam) && pParam > 0 ? pParam : 1;
  const { data, isPending, isFetching } = useJournalWorks(issnL, requested);
  const works = data?.items ?? [];
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / WORKS_PAGE_SIZE));
  const page = Math.min(requested, pages);

  const setPage = (p: number) => {
    const next = new URLSearchParams(searchParams.toString());
    if (p > 1) next.set("page", String(p));
    else next.delete("page");
    router.replace(`${pathname}?${next}`, { scroll: false });
  };

  // A shared link can point past the last page; fall back to the last one.
  React.useEffect(() => {
    if (data && requested > pages) {
      const next = new URLSearchParams(searchParams.toString());
      next.set("page", String(pages));
      router.replace(`${pathname}?${next}`, { scroll: false });
    }
  }, [data, requested, pages, pathname, router, searchParams]);

  return (
    <CollapsibleCard
      id="publications"
      title="Publications (Twente)"
      description={
        <p className="text-sm text-[var(--muted-foreground)]">
          University corpus (Pure), all years; citations and FWCI from OpenAlex
          where the title is matched there.
        </p>
      }
      contentClassName="space-y-3 text-sm"
    >
        {isPending && !data ? (
          <p className="text-[var(--muted-foreground)]">Loading publications…</p>
        ) : works.length === 0 ? (
          // Also the pre-integration state: old backends 404 on /works.
          <p className="text-[var(--muted-foreground)]">
            No Twente publications in the university corpus for this journal.
          </p>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {works.map((w) => {
              const href = doiHref(w.doi) ?? w.url;
              return (
              <li
                key={w.id}
                className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1 py-2 first:pt-0 last:pb-0"
              >
                {href ? (
                  <External href={href} className="min-w-0 flex-1 font-medium">
                    {w.title ?? w.doi ?? w.url}
                  </External>
                ) : (
                  <span className="min-w-0 flex-1 font-medium">
                    {w.title ?? "Untitled"}
                  </span>
                )}
                {w.year != null && (
                  <span className="tabular-nums text-[var(--muted-foreground)]">
                    {w.year}
                  </span>
                )}
                <OaStatusChip status={w.oa_status} />
                <span
                  className="text-xs tabular-nums text-[var(--muted-foreground)]"
                  title="Citations (OpenAlex)"
                >
                  {w.cited_by_count.toLocaleString("en")}{" "}
                  {w.cited_by_count === 1 ? "citation" : "citations"}
                </span>
                <span
                  className="text-xs tabular-nums text-[var(--muted-foreground)]"
                  title="Field-weighted citation impact"
                >
                  FWCI {w.fwci != null ? w.fwci.toFixed(2) : "—"}
                </span>
                {w.is_retracted && (
                  <Badge
                    variant="outline"
                    className="border-red-300 bg-red-100 text-red-700 dark:border-red-400/40 dark:bg-red-400/15 dark:text-red-300"
                  >
                    Retracted
                  </Badge>
                )}
              </li>
              );
            })}
          </ul>
        )}
        {pages > 1 && (
          <nav
            className="flex flex-wrap items-center gap-1 text-xs"
            aria-label="Publications pages"
          >
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1 || isFetching}
              onClick={() => setPage(Math.max(1, page - 1))}
            >
              ‹ Prev
            </Button>
            {pageWindow(page, pages).map((p, i) =>
              p === "…" ? (
                <span key={`gap-${i}`} className="px-1 text-[var(--muted-foreground)]">
                  …
                </span>
              ) : (
                <Button
                  key={p}
                  variant={p === page ? "secondary" : "outline"}
                  size="sm"
                  disabled={isFetching}
                  onClick={() => setPage(p)}
                  aria-current={p === page ? "page" : undefined}
                >
                  {p}
                </Button>
              ),
            )}
            <Button
              variant="outline"
              size="sm"
              disabled={page >= pages || isFetching}
              onClick={() => setPage(Math.min(pages, page + 1))}
            >
              Next ›
            </Button>
            <span className="ml-2 text-[var(--muted-foreground)]">
              {total.toLocaleString("en")} publications
            </span>
          </nav>
        )}
        <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-[var(--border)] pt-3">
          {openalex?.id && (
            <External
              href={`https://openalex.org/works?filter=primary_location.source.id:${openalex.id}`}
            >
              All works on OpenAlex
            </External>
          )}
          <External
            href={`https://explore.openaire.eu/search/find?keyword=%22${encodeURIComponent(title)}%22`}
          >
            Search on OpenAIRE
          </External>
          <SourceNote {...worksNote} codes={worksNote.caveat_codes} />
        </div>
    </CollapsibleCard>
  );
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
  return (
    <nav
      aria-label="Page sections"
      className="sticky top-0 z-40 border-b border-[var(--border)] bg-[var(--secondary)] text-[var(--secondary-foreground)]"
    >
      <div className="mx-auto flex max-w-6xl items-center gap-3 overflow-x-auto px-4 py-2">
        <Link
          href="/"
          className="inline-flex shrink-0 items-center gap-1 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
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
                  "inline-block whitespace-nowrap rounded px-2 py-1 text-sm underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--primary)]",
                  active === s.id
                    ? "font-medium text-[var(--primary-text)] underline"
                    : "text-[var(--muted-foreground)]",
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

function JournalPageInner() {
  const params = useParams<{ issn_l: string }>();
  const issnL = params?.issn_l ? decodeURIComponent(params.issn_l) : undefined;
  const { data, isPending, isError, error } = useJournal(issnL);
  // Old backends lack /similar; the section simply stays hidden then.
  const similarQuery = useSimilar(issnL);
  const similar = similarQuery.data ?? [];

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
        <p className="text-[var(--destructive)]">{errorMessage(error)}</p>
        <Link
          href="/"
          className="mt-2 inline-flex items-center gap-1 text-sm text-[var(--primary-text)] underline-offset-4 hover:underline"
        >
          <ArrowLeft aria-hidden className="size-4" /> Back to search
        </Link>
      </div>
    );

  const { journal, stats, deals, attribution, summary_stats, stats_totals: totals } = data;
  const recent = stats.filter((s) => s.year >= 2020);
  const openalex = data.openalex ?? null;
  const openaire = data.openaire ?? null;
  const twente = data.twente_metrics ?? null;

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
  const oaTopics = (openalex?.topics ?? []).filter(
    (t): t is OpenalexTopic => Boolean(t?.display_name),
  );
  const maxTopicCount = oaTopics[0]?.count ?? 1;
  const hasApc =
    data.apc_aggregates.length > 0 || data.apc_evidence.length > 0;
  // One nav entry per rendered section, in DOM order.
  const sections = [
    ...(deals.length > 0
      ? deals.map((deal) => ({
          id: `deal-${deal.id}`,
          label: "Open access deal",
        }))
      : [{ id: "deal", label: "Open access deal" }]),
    ...(topics.length > 0 || oaTopics.length > 0
      ? [{ id: "topics", label: "Topics" }]
      : []),
    { id: "publications", label: "Publications" },
    { id: "cite", label: "Cite this journal" },
    { id: "oa-per-year", label: "Open access per year" },
    { id: "metrics", label: "Metrics" },
    ...(hasApc ? [{ id: "apc", label: "APC cost evidence" }] : []),
    ...(similar.length > 0
      ? [{ id: "similar", label: "Similar journals" }]
      : []),
  ];

  return (
    <>
      <SectionNav sections={sections} />
      <div className="mx-auto max-w-6xl px-4 py-10">
      <header className="mb-8">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-3xl font-bold">
            {data.homepage_url ? (
              <a
                href={data.homepage_url}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={`${journal.title ?? journal.issn_l} — opens the journal website in a new tab`}
                className="inline-flex items-center gap-1.5 underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
              >
                {journal.title ?? journal.issn_l}
                <ExternalLink
                  aria-hidden
                  className="size-5 text-[var(--muted-foreground)]"
                />
              </a>
            ) : (
              journal.title ?? journal.issn_l
            )}
          </h1>
          <OaTypeBadge oaType={journal.oa_type} isOa={journal.is_oa} />
          <QuartileBadge quartile={journal.quartile ?? null} />
        </div>
        {data.alternate_titles.length > 0 && (
          <p className="mt-1 text-sm text-[var(--muted-foreground)]">
            Also published as {data.alternate_titles.join("; ")}
          </p>
        )}
        <p className="mt-1.5 text-[var(--muted-foreground)]">
          {journal.publisher_name ?? "Unknown publisher"}
          {data.type
            ? ` · ${data.type.charAt(0).toUpperCase()}${data.type.slice(1)}`
            : ""}{" "}
          · ISSN-L {journal.issn_l}
          {data.issns.length > 1 && ` (${data.issns.join(", ")})`}
        </p>
        {(data.homepage_url || openalex?.url) && (
          <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            {data.homepage_url && (
              <External href={data.homepage_url}>Homepage</External>
            )}
            {openalex?.url && <External href={openalex.url}>OpenAlex</External>}
          </p>
        )}
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
                id={`deal-${deal.id}`}
                deal={deal}
                attribution={attribution.deals ?? {}}
              />
            ))
          ) : (
            <CollapsibleCard
              id="deal"
              title="Open access deal"
              contentClassName="text-sm text-[var(--muted-foreground)]"
            >
                No current open access deal covering this journal for
                University of Twente authors. Check{" "}
                <External href="https://www.openaccess.nl">openaccess.nl</External>{" "}
                and the{" "}
                <External href="https://journalcheckertool.org">
                  Journal Checker Tool
                </External>{" "}
                for green OA routes.
                <div className="mt-2">
                  <SourceNote
                    {...(attribution.deals ?? {})}
                    codes={attribution.deals?.caveat_codes}
                  />
                </div>
            </CollapsibleCard>
          )}

          {oaTopics.length > 0 ? (
            <CollapsibleCard id="topics" title="Topics" contentClassName="space-y-4">
                <p className="text-xs text-[var(--muted-foreground)]">
                  Topics assigned by OpenAlex; N = works in this journal
                  classified under the topic.
                </p>
                <ul className="space-y-3.5">
                  {oaTopics.map((topic) => (
                    <li key={topic.id}>
                      <div className="flex flex-wrap items-center gap-2">
                        <Link
                          href={`/?topic=${encodeURIComponent(topic.display_name)}&search_in=topic`}
                          className="font-semibold underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                        >
                          {topic.display_name}
                        </Link>
                        <Badge variant="muted" className="tabular-nums">
                          {(topic.count ?? 0).toLocaleString("en")}
                        </Badge>
                      </div>
                      <div
                        className="mt-1 h-1 w-full rounded-full bg-[var(--muted)]"
                        title={`${(topic.count ?? 0).toLocaleString("en")} works`}
                      >
                        <div
                          className="h-1 rounded-full bg-[var(--primary)]"
                          style={{
                            width: `${Math.max(((topic.count ?? 0) / maxTopicCount) * 100, 1.5)}%`,
                          }}
                        />
                      </div>
                      <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                        {[
                          topic.subfield?.display_name,
                          topic.field?.display_name,
                          topic.domain?.display_name,
                        ]
                          .filter(Boolean)
                          .join(" → ")}
                      </p>
                    </li>
                  ))}
                </ul>
                <SourceNote
                  {...(attribution.openalex ?? {})}
                  codes={attribution.openalex?.caveat_codes}
                />
            </CollapsibleCard>
          ) : topics.length > 0 ? (
            <CollapsibleCard
              id="topics"
              title="Topics"
              contentClassName="flex flex-wrap gap-1.5"
            >
                {topics.map((topic) => (
                  <Badge key={topic} variant="muted" className="font-normal normal-case">
                    {topic}
                  </Badge>
                ))}
            </CollapsibleCard>
          ) : null}

          <PublicationsCard
            key={journal.issn_l}
            issnL={journal.issn_l}
            title={journal.title ?? journal.issn_l}
            openalex={openalex}
            worksNote={attribution.works ?? {}}
          />
          <CitationCard data={data} />
        </div>

        <div className="space-y-6">
          <CollapsibleCard
            id="oa-per-year"
            title={
              <>
                Open access per year{" "}
                <span className="text-sm font-normal text-[var(--muted-foreground)]">
                  (Twente, 2020+)
                </span>
              </>
            }
          >
              {recent.length > 0 ? (
                <OaTrend stats={recent} />
              ) : (
                <p className="text-sm text-[var(--muted-foreground)]">
                  No publication statistics yet.
                </p>
              )}
              <p className="mt-3 text-sm">
                {totals.pure_canon.toLocaleString("en")} UT works total since
                2020 <span className="text-[var(--muted-foreground)]">(Pure)</span>{" "}
                · OpenAlex institution filter:{" "}
                <span className="whitespace-nowrap">
                  {totals.openalex_institution_filter.toLocaleString("en")}{" "}
                  <span className="text-[var(--muted-foreground)]">
                    (cross-check)
                  </span>
                </span>
                .
              </p>
              <div className="mt-2 flex flex-wrap gap-x-4">
                <SourceNote
                  {...(attribution.stats ?? {})}
                  codes={attribution.stats?.caveat_codes}
                />
                <SourceNote
                  {...(attribution.oa_status ?? {})}
                  codes={attribution.oa_status?.caveat_codes}
                />
              </div>
          </CollapsibleCard>

          <CollapsibleCard
            id="metrics"
            title="Metrics"
            contentClassName="space-y-4 text-sm"
          >
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <Metric
                  label="2-year mean citedness"
                  value={
                    journal.twoyr_mean_citedness != null
                      ? journal.twoyr_mean_citedness.toFixed(1)
                      : "—"
                  }
                />
                <Metric
                  label="h-index"
                  value={num("h_index")?.toLocaleString("en") ?? "—"}
                  note="OpenAlex"
                />
                <Metric
                  label="i10 index"
                  value={num("i10_index")?.toLocaleString("en") ?? "—"}
                  note="OpenAlex"
                />
              </div>
              <SourceNote
                {...(attribution.metrics ?? {})}
                codes={attribution.metrics?.caveat_codes}
              />
              {(openalex || twente || openaire) && (
                <div className="border-t border-[var(--border)] pt-4">
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                    {openalex?.cited_by_count != null && (
                      <Metric
                        label="Total citations"
                        value={openalex.cited_by_count.toLocaleString("en")}
                        note={
                          <SourceNote
                            {...(attribution.openalex ?? {})}
                            codes={attribution.openalex?.caveat_codes}
                          />
                        }
                      />
                    )}
                    {openalex?.works_count != null && (
                      <Metric
                        label="Works count"
                        value={openalex.works_count.toLocaleString("en")}
                        note={
                          <SourceNote
                            {...(attribution.openalex ?? {})}
                            codes={attribution.openalex?.caveat_codes}
                          />
                        }
                      />
                    )}
                    {twente && (
                      <Metric
                        label="FWCI (Twente works)"
                        value={
                          twente.fwci_avg != null && twente.fwci_n > 0
                            ? twente.fwci_avg.toFixed(2)
                            : "—"
                        }
                        note={
                          <>
                            n = {twente.fwci_n} works{" "}
                            <SourceNote
                              {...(attribution.openalex ?? {})}
                              codes={attribution.openalex?.caveat_codes}
                            />
                          </>
                        }
                      />
                    )}
                    {twente && twente.retracted > 0 && (
                      <Metric
                        label="Retracted Twente works"
                        value={twente.retracted.toLocaleString("en")}
                        note={
                          <SourceNote
                            {...(attribution.openalex ?? {})}
                            codes={attribution.openalex?.caveat_codes}
                          />
                        }
                      />
                    )}
                    {openaire && (
                      <Metric
                        label="Matched publications"
                        value={openaire.matched_works.toLocaleString("en")}
                        note={
                          <SourceNote
                            {...(attribution.openaire ?? {})}
                            codes={attribution.openaire?.caveat_codes}
                          />
                        }
                      />
                    )}
                  </div>
                </div>
              )}
              {latestSjr && (
                <div className="border-t border-[var(--border)] pt-4">
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
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
                    <SourceNote
                      {...(attribution.scimagojr ?? {})}
                      codes={attribution.scimagojr?.caveat_codes}
                    />
                  </div>
                </div>
              )}
          </CollapsibleCard>

          {hasApc && (
            <CollapsibleCard
              id="apc"
              title="APC cost evidence"
              contentClassName="text-sm"
            >
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
                    {data.apc_evidence.length} Twente APC{" "}
                    {data.apc_evidence.length === 1 ? "record" : "records"}{" "}
                    (latest{" "}
                    {data.apc_evidence[0].period ?? "—"}:{" "}
                    {data.apc_evidence[0].euro !== null
                      ? `€${Math.round(data.apc_evidence[0].euro!)}`
                      : "amount unknown"}
                    ).
                  </p>
                )}
                <div className="mt-3">
                  <SourceNote
                    {...(attribution.apc_evidence ?? {})}
                    codes={attribution.apc_evidence?.caveat_codes}
                  />
                </div>
            </CollapsibleCard>
          )}

        </div>
      </div>

      {similar.length > 0 && (
        <CollapsibleCard id="similar" title="Similar journals" className="mt-6">
            <ul className="divide-y divide-[var(--border)]">
              {similar.map((s) => (
                <li key={s.issn_l} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-2 text-sm first:pt-0 last:pb-0">
                  <Link
                    href={`/journals/${s.issn_l}`}
                    className="font-medium underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                  >
                    {s.title ?? s.issn_l}
                  </Link>
                  <span className="text-xs text-[var(--muted-foreground)]">
                    {s.publisher_name ?? "Unknown publisher"}
                  </span>
                  <span className="ml-auto flex items-center gap-2">
                    <QuartileBadge quartile={s.quartile ?? null} />
                    <span className="text-xs text-[var(--muted-foreground)]">
                      {s.shared_topics} shared{" "}
                      {s.shared_topics === 1 ? "topic" : "topics"}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
        </CollapsibleCard>
      )}
      </div>
    </>
  );
}

export default function JournalPage() {
  // PublicationsCard reads the page param via useSearchParams, which needs a
  // Suspense boundary during prerender.
  return (
    <React.Suspense fallback={null}>
      <JournalPageInner />
    </React.Suspense>
  );
}
