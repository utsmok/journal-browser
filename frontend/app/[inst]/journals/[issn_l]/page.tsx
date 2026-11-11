"use client";

import {
  ArrowLeft,
  Check,
  CircleCheck,
  CircleHelp,
  CircleX,
  Copy,
  ExternalLink,
  X,
} from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import {
  DealBadge,
  OaStatusChip,
  OaTypeBadge,
  PureMatchBadge,
  QuartileBadge,
} from "@/components/badges";
import { CollapsibleCard } from "@/components/collapsible-card";
import { CardPager } from "@/components/card-pager";
import { GapCsvButton } from "@/components/gap-csv-button";
import { OaTrend } from "@/components/oa-trend";
import { UtAuthorLine } from "@/components/ut-author-line";
import { SourceNote } from "@/components/source-note";
import { ErrorPanel, JournalDetailSkeleton } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useJournal, useJournalWorks, useSimilar } from "@/hooks/use-api";
import { useInstitution } from "@/hooks/use-institution";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { useYearRange, yearQuery } from "@/hooks/use-year-filter";
import {
  errorMessage,
  type Attribution,
  type DealLink,
  type DealOut,
  type FunderFitOut,
  type JournalDetailResponse,
  type OpenalexSource,
  type OpenalexTopic,
  type WorksPage,
  encodeNamePath,
} from "@/lib/api";
import { dealLinkLabel, orderedDealLinks } from "@/lib/deal-links";
import { useFunderPrefs, type FunderPrefs } from "@/lib/funder-prefs";
import { cleanProse, cn } from "@/lib/utils";
import { workTypeLabel } from "@/lib/work-type";

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

function Metric({
  label,
  value,
  note,
  hint,
}: {
  label: string;
  value: string;
  note?: React.ReactNode;
  hint?: string;
}) {
  return (
    // Focusable so keyboard users can raise the title-tooltip too.
    <div title={hint} tabIndex={hint ? 0 : undefined}>
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
      <div className="text-xs font-medium">{label}</div>
      {note && <div className="text-[11px] text-[var(--muted-foreground)]">{note}</div>}
    </div>
  );
}

/** Clipboard write with a brief "Copied" affordance; no alerts. */
function CopyButton({ text, label }: { text: string; label: string }) {
  const [state, setState] = React.useState<"idle" | "copied" | "failed">("idle");
  const timer = React.useRef<number | undefined>(undefined);
  React.useEffect(() => () => window.clearTimeout(timer.current), []);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
    timer.current = window.setTimeout(() => setState("idle"), 1500);
  };
  const title = state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : "Copy";
  return (
    <button
      type="button"
      onClick={copy}
      aria-label={`${title} ${label}`}
      aria-live="polite"
      title={title}
      className="inline-flex size-6 shrink-0 items-center justify-center rounded border border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
    >
      {state === "copied" ? (
        <Check aria-hidden className="size-3.5 text-emerald-600" />
      ) : state === "failed" ? (
        <X aria-hidden className="size-3.5 text-[var(--destructive)]" />
      ) : (
        <Copy aria-hidden className="size-3.5" />
      )}
    </button>
  );
}

function CitationCard({ data }: { data: JournalDetailResponse }) {
  const inst = useInstitution();
  const today = new Date().toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
  const title = data.journal.title ?? data.journal.issn_l;
  const citation = `${title}. ${data.journal.publisher_name ?? "Unknown publisher"}. ISSN-L ${data.journal.issn_l}. Available at: ${process.env.NEXT_PUBLIC_SITE_URL ?? "https://journalbrowser.samuelmok.cc"}/${inst}/journals/${data.journal.issn_l} (accessed ${today})`;
  return (
    <CollapsibleCard id="cite" title="Cite this journal" contentClassName="space-y-2 text-sm">
      <div className="flex items-start gap-2">
        {/* anywhere (not break-words): only `anywhere` lets the long canonical URL
              count as breakable for the grid column's min-content, so mobile stays 390px. */}
        <p className="min-w-0 flex-1 text-pretty [overflow-wrap:anywhere]">{citation}</p>
        <CopyButton text={citation} label="citation" />
      </div>
      <p className="border-t border-[var(--border)] pt-2 text-xs text-[var(--muted-foreground)]">
        ISSNs to cite are listed under Identifiers below.
      </p>
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
  const site = useSiteMeta();
  const capNumbers = Object.entries(deal.cap_numbers ?? {}).sort(
    (a, b) => (parseInt(a[0], 10) || 0) - (parseInt(b[0], 10) || 0),
  );
  return (
    <CollapsibleCard
      id={id}
      title={
        <>
          Open access deal
          <DealBadge covered />
          {deal.corresponding_authors_only && (
            <Badge
              variant="muted"
              title={`The deal only funds the APC when the corresponding author is from ${site.name}.`}
            >
              Corresponding authors only
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
          {deal.publisher_name} · {deal.duration_text ?? deal.esac_id}
        </p>
      }
      contentClassName="space-y-4 text-sm"
    >
      {deal.summary && <p className="max-w-prose text-pretty">{cleanProse(deal.summary)}</p>}
      {deal.conditions_text && (
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
            Cost implication & conditions
          </h3>
          <p className="max-w-prose whitespace-pre-line text-pretty">
            {cleanProse(deal.conditions_text)}
          </p>
        </div>
      )}
      {(deal.cap_text || capNumbers.length > 0) && (
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
            Article caps
          </h3>
          {deal.cap_text && (
            <p className="whitespace-pre-line text-pretty">{cleanProse(deal.cap_text)}</p>
          )}
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
          <p className="text-pretty">{cleanProse(deal.article_types_text)}</p>
        </div>
      )}
      {deal.workflow_text && (
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
            Workflow
          </h3>
          <p className="text-pretty">{cleanProse(deal.workflow_text)}</p>
        </div>
      )}
      <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-[var(--border)] pt-3">
        {deal.links?.length ? (
          orderedDealLinks(deal.links)
            .filter((link): link is DealLink & { url: string } => !!link.url)
            .map((link) => (
              <External key={`${link.category}-${link.url}`} href={link.url}>
                {dealLinkLabel(link)}
              </External>
            ))
        ) : (
          // Old backend: no links[] yet; fall back to the flat URL fields.
          <>
            {deal.openaccess_nl_url && (
              <External href={deal.openaccess_nl_url}>openaccess.nl deal page</External>
            )}
            {deal.contract_url && <External href={deal.contract_url}>Contract</External>}
            {deal.jct_data_url && <External href={deal.jct_data_url}>JCT data</External>}
          </>
        )}
        <SourceNote {...attribution} codes={attribution.caveat_codes} />
      </div>
    </CollapsibleCard>
  );
}

const WORKS_PAGE_SIZE = 20;

/** List caps: reference-data sections show the top slice and reveal the
 * rest on demand (limit, don't delete). */
const TOPICS_LIMIT = 8;
const NAMES_LIMIT = 12;
const SIMILAR_LIMIT = 12;

type GreenOaPolicy = NonNullable<JournalDetailResponse["green_oa"]>;
type UtAuthorship = JournalDetailResponse["ut_authorship"];
type OpenalexOnly = JournalDetailResponse["openalex_only"];

const GREEN_OA_VERSIONS: Record<string, string> = {
  submitted: "Submitted version",
  accepted: "Accepted version",
  published: "Published version",
};

/** Sherpa location slugs (verified against the live jisc_policy corpus). */
const GREEN_OA_LOCATIONS: Record<string, string> = {
  academic_social_network: "Academic social network",
  any_repository: "Any repository",
  any_website: "Any website",
  authors_homepage: "Author's homepage",
  funder_designated_location: "Funder-designated location",
  institutional_repository: "Institutional repository",
  institutional_website: "Institutional website",
  named_academic_social_network: "Named academic social networks",
  named_repository: "Named repositories",
  non_commercial_institutional_repository: "Non-commercial institutional repository",
  non_commercial_repository: "Non-commercial repository",
  non_commercial_social_network: "Non-commercial academic social network",
  non_commercial_subject_repository: "Non-commercial subject repository",
  non_commercial_website: "Non-commercial website",
  preprint_repository: "Preprint repository",
  subject_repository: "Subject repository",
  this_journal: "This journal",
};

function licenseLabel(license: string): string {
  if (license === "cc0") return "CC0";
  if (license.startsWith("cc_")) return `CC ${license.slice(3).replaceAll("_", "-").toUpperCase()}`;
  return license.charAt(0).toUpperCase() + license.slice(1).replaceAll("_", " ");
}

function locationPhrase(
  location: string,
  repositories: string[],
  links: Record<string, string>,
): React.ReactNode {
  const base =
    GREEN_OA_LOCATIONS[location] ??
    location.charAt(0).toUpperCase() + location.slice(1).replaceAll("_", " ");
  if (!(location.startsWith("named_") && repositories.length > 0)) return base;
  return (
    <>
      {base}:{" "}
      {repositories.map((name, i) => (
        <React.Fragment key={name}>
          {i > 0 && ", "}
          {/* Linked when the name matched a jisc_repositories row. */}
          {links[name] ? <External href={links[name]}>{name}</External> : name}
        </React.Fragment>
      ))}
    </>
  );
}

/** Small card in the green-OA area: how the selected funder's policy
 * judges this journal, with the engine's reasons. Text-only funder
 * policies (fit.status null) show the check-manually note. */
const FIT_TIER = {
  compliant: {
    Icon: CircleCheck,
    color: "text-emerald-700 dark:text-emerald-400",
    label: "Compliant",
  },
  check: { Icon: CircleHelp, color: "text-amber-600 dark:text-amber-400", label: "Check" },
  no: { Icon: CircleX, color: "text-red-700 dark:text-red-400", label: "Not compliant" },
} as const;

function FunderFitCard({
  fit,
  funder,
  inst,
}: {
  fit: FunderFitOut | null;
  funder: NonNullable<FunderPrefs>;
  inst: string;
}) {
  const tier = fit?.status ? FIT_TIER[fit.status] : null;
  return (
    <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        {tier && <tier.Icon aria-hidden className={`size-5 ${tier.color}`} />}
        <span className="font-medium">
          {tier
            ? `Funder fit for ${funder.name}: ${tier.label}`
            : `Funder policy for ${funder.name}`}
        </span>
        <Link
          href={`/${inst}/funders/${funder.id}`}
          className="text-xs underline decoration-dotted underline-offset-2"
        >
          view funder policy
        </Link>
      </div>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-[var(--muted-foreground)]">
        {(fit?.reasons ?? ["Funder policy is text-only; check manually"]).map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>
    </div>
  );
}

function GreenOaPanel({
  greenOa,
  attribution,
}: {
  greenOa: GreenOaPolicy;
  attribution: Partial<Attribution>;
}) {
  const routes = Object.entries(greenOa.routes);
  return (
    <CollapsibleCard
      id="green-oa"
      title="Green OA policy"
      description={
        <p className="text-sm text-[var(--muted-foreground)]">
          Which versions of your article the publisher lets you self-archive.
        </p>
      }
      contentClassName="space-y-4 text-sm"
    >
      {greenOa.oa_prohibited && (
        <p className="font-medium text-red-700 dark:text-red-300">
          The publisher prohibits open access for this journal.
        </p>
      )}
      {routes.map(([version, route]) => (
        <div key={version} className="space-y-1">
          <h3 className="flex flex-wrap items-center gap-2 font-semibold">
            {GREEN_OA_VERSIONS[version] ?? version}
            {route.additional_oa_fee === "yes" && (
              <Badge
                variant="muted"
                title="The policy states this route requires an additional open access fee."
              >
                OA fee required
              </Badge>
            )}
          </h3>
          {route.locations.length > 0 && (
            <p>
              Where:{" "}
              {route.locations.map((location, i) => (
                <React.Fragment key={location}>
                  {i > 0 && "; "}
                  {locationPhrase(location, route.repositories, greenOa.repository_links)}
                </React.Fragment>
              ))}
              .
            </p>
          )}
          {route.licenses.length > 0 && (
            <p>Licence: {route.licenses.map(licenseLabel).join(", ")}.</p>
          )}
          {route.embargo_months != null && (
            <p>
              Embargo: after {route.embargo_months}{" "}
              {route.embargo_months === 1 ? "month" : "months"}.
            </p>
          )}
          {route.conditions.length > 0 && (
            // Jisc policy text is CC BY-NC-ND: shown verbatim, never paraphrased.
            <div>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                Conditions
              </h4>
              <ul className="list-disc space-y-1 pl-4">
                {route.conditions.map((condition) => (
                  <li key={condition} className="text-pretty">
                    {condition}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ))}
      {routes.length === 0 && !greenOa.oa_prohibited && (
        <p>No self-archiving route is listed for this journal.</p>
      )}
      <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-[var(--border)] pt-3">
        {greenOa.policy_uri && (
          <External href={greenOa.policy_uri}>View on Jisc Open Policy Finder</External>
        )}
        {greenOa.urls.map((u) => (
          <External key={u.url} href={u.url}>
            {u.description || u.url}
          </External>
        ))}
        <SourceNote {...attribution} codes={attribution.caveat_codes} />
      </div>
    </CollapsibleCard>
  );
}

function doiHref(doi: string | null): string | null {
  if (!doi) return null;
  return /^https?:\/\//.test(doi) ? doi : `https://doi.org/${doi}`;
}

/** Who at this institution authors the journal's works: distinct works
 * per faculty and research group, plus the most prolific UT authors. */
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
          counted here.
        </p>
      }
      contentClassName="space-y-5 text-sm"
    >
      {empty ? (
        <p className="text-[var(--muted-foreground)]">No UT-authorship records for this journal.</p>
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
                <caption className="sr-only">Most prolific UT authors of this journal</caption>
                <TableHeader>
                  <TableRow>
                    <TableHead>Author</TableHead>
                    <TableHead className="text-right">Works</TableHead>
                    <TableHead>Affiliation</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {authorship.top_authors.map((a) => (
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

/** OpenAlex works attributed to this journal that match no Pure record:
 * candidates missing from the research information system. */
function CrisGapsCard({
  openalexOnly,
  inst,
  issnL,
}: {
  openalexOnly: OpenalexOnly;
  inst: string;
  issnL: string;
}) {
  const { year_from, year_to } = useYearRange();
  const { total, items } = openalexOnly;
  return (
    <CollapsibleCard
      id="cris-gaps"
      title="Not registered in Pure"
      description={
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <p className="text-sm text-[var(--muted-foreground)]">
            OpenAlex attributes {total.toLocaleString("en")} work(s) to this journal that match no
            Pure record — likely missing from the research information system. Each item lists the
            UT authors OpenAlex matched to the university roster.
            {total > items.length && ` Showing ${items.length.toLocaleString("en")} most recent.`}
          </p>
          {total > 0 && (
            <GapCsvButton
              href={`/api/v1/${inst}/journals/${issnL}/openalex-only.csv${yearQuery("?", year_from, year_to)}`}
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
                  <External
                    href={href}
                    className="min-w-0 w-full min-[480px]:w-auto min-[480px]:flex-1 font-medium"
                  >
                    {w.title ?? w.doi}
                  </External>
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
                {w.work_type && <span className="text-xs">{workTypeLabel(w.work_type)}</span>}
                <PureMatchBadge match={w.pure_match} url={w.pure_match_url} />
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

/** Twente works in this journal, paginated from the /works endpoint. The
 * query itself lives on the page (it races the detail request); this card
 * renders whatever has arrived, skeleton rows while it is still loading. */
function PublicationsCard({
  title,
  openalex,
  worksNote,
  requested,
  worksQuery,
}: {
  title: string;
  openalex: OpenalexSource | null;
  worksNote: Partial<Attribution>;
  requested: number;
  worksQuery: {
    data: WorksPage | undefined;
    isPending: boolean;
    isFetching: boolean;
  };
}) {
  const site = useSiteMeta();
  const inst = useInstitution();
  const { year_from, year_to } = useYearRange();
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { data, isPending, isFetching } = worksQuery;
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
      title={`Publications (${site.short})`}
      description={
        <p className="text-pretty text-sm text-[var(--muted-foreground)]">
          {site.short} works from Pure merged with OpenAlex venue works
          {year_from !== undefined
            ? `, ${year_from}–${year_to}`
            : site.windowStart === undefined
              ? ""
              : `, ${site.windowStart} onwards`}
          . Citations and FWCI come from OpenAlex; works not matched there are marked.
        </p>
      }
      contentClassName="space-y-3 text-sm"
    >
      {isPending && !data ? (
        <div className="space-y-2.5" aria-hidden>
          {[92, 75, 84, 60, 70].map((w, i) => (
            <div
              key={i}
              className="h-4 animate-pulse rounded bg-[var(--muted)]"
              style={{ width: `${w}%` }}
            />
          ))}
        </div>
      ) : works.length === 0 ? (
        // Also the pre-integration state: old backends 404 on /works.
        <p className="text-[var(--muted-foreground)]">
          No {site.name} publications in the university corpus for this journal.
        </p>
      ) : (
        <ul className="divide-y divide-[var(--border)]">
          {works.map((w) => {
            const href = doiHref(w.doi ?? null) ?? w.url;
            return (
              <li
                key={w.id}
                className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1 py-2 first:pt-0 last:pb-0"
              >
                {/* Full-basis line on phones: flex-1's 0% basis squeezed the
                    title into a ~63px column beside year/citations badges. */}
                {href ? (
                  <External
                    href={href}
                    className="min-w-0 w-full min-[480px]:w-auto min-[480px]:flex-1 font-medium"
                  >
                    {w.title ?? w.doi ?? w.url}
                  </External>
                ) : (
                  <span className="min-w-0 w-full min-[480px]:w-auto min-[480px]:flex-1 font-medium">
                    {w.title ?? "Untitled"}
                  </span>
                )}
                {!w.in_openalex && (
                  <Badge
                    variant="outline"
                    className="font-normal text-[11px] text-[var(--muted-foreground)]"
                    title="In the university's Pure research information system; not matched in OpenAlex, so citations and FWCI are unavailable"
                  >
                    Pure only
                  </Badge>
                )}
                {w.year != null && (
                  <span className="tabular-nums text-[var(--muted-foreground)]">{w.year}</span>
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
                    title="This publication was retracted, per OpenAlex."
                    className="border-red-300 bg-red-100 text-red-700 dark:border-red-400/40 dark:bg-red-400/15 dark:text-red-300"
                  >
                    Retracted
                  </Badge>
                )}
                {(w.ut_authors.length > 0 || w.ut_groups.length > 0) && (
                  <div className="w-full text-xs text-[var(--muted-foreground)]">
                    {w.ut_authors.length > 0 && (
                      <span>
                        {w.ut_authors.map((a, i) => (
                          <React.Fragment key={a.id}>
                            {i > 0 && ", "}
                            <Link
                              href={`/${inst}/author/${a.id}`}
                              className="underline decoration-dotted underline-offset-2 hover:text-[var(--foreground)]"
                            >
                              {a.name}
                            </Link>
                          </React.Fragment>
                        ))}
                      </span>
                    )}
                    {w.ut_groups.map((g, i) => (
                      <React.Fragment key={g.name}>
                        {(w.ut_authors.length > 0 || i > 0) && " · "}
                        <Link
                          href={`/${inst}/orgunit/group/${encodeNamePath(g.name)}`}
                          className="underline decoration-dotted underline-offset-2 hover:text-[var(--foreground)]"
                        >
                          {g.name}
                        </Link>
                      </React.Fragment>
                    ))}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {pages > 1 && (
        <CardPager
          page={page}
          pages={pages}
          total={total}
          onPage={setPage}
          isFetching={isFetching}
          label="publications"
        />
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

function SectionNav({ sections }: { sections: { id: string; label: string; hint?: string }[] }) {
  const active = useSectionSpy(sections.map((s) => s.id));
  // Muted-foreground/primary-text both fail 4.5:1 on the navy bar, so this
  // nav speaks in white and separates the active item with weight+underline.
  const backHref = useLastSearchHref();
  return (
    <nav
      aria-label="Page sections"
      className="sticky top-0 z-40 border-b border-[var(--border)] bg-[var(--secondary)] text-[var(--secondary-foreground)]"
    >
      <div className="mx-auto flex max-w-5xl items-center gap-3 overflow-x-auto px-4 py-2">
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
                title={s.hint}
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

/** Reveal control for capped lists; matches the author-page pattern. */
function MoreToggle({
  open,
  onToggle,
  moreLabel,
}: {
  open: boolean;
  onToggle: () => void;
  moreLabel: string;
}) {
  return (
    <button
      type="button"
      className="self-start text-sm text-[var(--muted-foreground)] underline-offset-2 hover:underline"
      aria-expanded={open}
      onClick={onToggle}
    >
      {open ? "Show less" : moreLabel}
    </button>
  );
}

/** Alternate titles from OpenAlex, capped like topics: chips plus a
 * reveal toggle once the list runs long. */
function OtherNamesCard({ names }: { names: string[] }) {
  const [open, setOpen] = React.useState(false);
  const shown = open ? names : names.slice(0, NAMES_LIMIT);
  return (
    <CollapsibleCard
      id="names"
      title="Other names"
      description={
        <p className="text-sm text-[var(--muted-foreground)]">
          Titles this journal is also published under.
        </p>
      }
      contentClassName="flex flex-wrap items-center gap-1.5"
    >
      {shown.map((name) => (
        <Badge key={name} variant="muted" className="font-normal normal-case">
          {name}
        </Badge>
      ))}
      {names.length > NAMES_LIMIT && (
        <MoreToggle
          open={open}
          onToggle={() => setOpen((o) => !o)}
          moreLabel={`Show all ${names.length} names`}
        />
      )}
    </CollapsibleCard>
  );
}

/** Ids and registry entries for this journal, gathered in one card:
 * ISSNs (copyable) plus DOAJ, OpenAlex, and Open Access NL records. */
function IdentifiersCard({
  issnL,
  issns,
  doajUrl,
  openalexUrl,
  oaNlSlug,
}: {
  issnL: string;
  issns: string[];
  doajUrl?: string | null;
  openalexUrl?: string | null;
  oaNlSlug?: string | null;
}) {
  const rows = [
    ...[`ISSN-L ${issnL}`, ...issns.map((i) => `ISSN ${i}`)]
      .filter((v, i, a) => a.indexOf(v) === i)
      .map((label) => ({ key: label, label })),
    ...(doajUrl ? [{ key: "doaj", label: "DOAJ record", href: doajUrl }] : []),
    ...(openalexUrl ? [{ key: "openalex", label: "OpenAlex source", href: openalexUrl }] : []),
    ...(oaNlSlug
      ? [
          {
            key: "oa-nl",
            label: "Open Access NL publisher",
            href: `https://openaccess.nl/en/publisher/${oaNlSlug}`,
          },
        ]
      : []),
  ];
  return (
    <CollapsibleCard
      id="identifiers"
      title="Identifiers"
      description={
        <p className="text-sm text-[var(--muted-foreground)]">
          Ids and registry entries for this journal.
        </p>
      }
      contentClassName="space-y-2 text-sm"
    >
      <ul className="divide-y divide-[var(--border)]">
        {rows.map((row) => (
          <li
            key={row.key}
            className="flex flex-wrap items-center justify-between gap-2 py-1.5 first:pt-0"
          >
            {"href" in row && row.href ? (
              <>
                <External href={row.href}>{row.label}</External>
                {row.key === "doaj" && (
                  <SourceNote source="via DOAJ" url="https://doaj.org" codes={["doaj-canon"]} />
                )}
              </>
            ) : (
              <>
                <span className="tabular-nums text-[var(--muted-foreground)]">{row.label}</span>
                <CopyButton text={row.label.replace(/^ISSN(-L)? /, "")} label={row.label} />
              </>
            )}
          </li>
        ))}
      </ul>
    </CollapsibleCard>
  );
}

function JournalPageInner() {
  const site = useSiteMeta();
  const params = useParams<{ issn_l: string }>();
  const inst = useInstitution();
  const issnL = params?.issn_l ? decodeURIComponent(params.issn_l) : undefined;
  const backHref = useLastSearchHref();
  const [funder] = useFunderPrefs();
  const { year_from, year_to } = useYearRange();
  // Expanded-list state: topics chips and similar-journal groups.
  const [allTopics, setAllTopics] = React.useState(false);
  const [openSimilar, setOpenSimilar] = React.useState<Record<string, boolean>>({});
  const { data, isPending, isError, error } = useJournal(issnL, funder?.id, {
    year_from,
    year_to,
  });
  // Old backends lack /similar; the section simply stays hidden then.
  const similarQuery = useSimilar(issnL);
  const similar = similarQuery.data;
  // Hoisted so the works request races the detail request instead of
  // waiting for it; the card below renders whatever has arrived.
  const searchParams = useSearchParams();
  const pParam = parseInt(searchParams.get("page") ?? "", 10);
  const requestedWorksPage = Number.isFinite(pParam) && pParam > 0 ? pParam : 1;
  const worksQuery = useJournalWorks(issnL, requestedWorksPage, { year_from, year_to });
  const similarEmpty =
    !similar ||
    (similar.all.length === 0 && similar.institution.length === 0 && similar.deals.length === 0);

  if (isPending) return <JournalDetailSkeleton />;
  if (isError || !data) return <ErrorPanel message={errorMessage(error)} backHref={backHref} />;

  const { journal, stats, deals, attribution, summary_stats, stats_totals: totals } = data;
  const greenOa = data.green_oa ?? null;
  const recent = stats.filter(
    (s) =>
      s.year >= (site.windowStart ?? 0) &&
      (year_from === undefined || s.year >= year_from) &&
      (year_to === undefined || s.year <= year_to),
  );
  // With the year lens on, the Pure total is the sum over the visible
  // years; the OpenAlex cross-check total stays a full-window figure and
  // is not shown then.
  const pureTotal =
    year_from === undefined ? totals.pure_canon : recent.reduce((acc, s) => acc + s.works_count, 0);
  const openalex = data.openalex ?? null;
  const openaire = data.openaire ?? null;
  const metrics = data.institution_metrics ?? null;

  const ss = (summary_stats ?? {}) as Record<string, unknown>;
  const num = (key: string) => (typeof ss[key] === "number" ? (ss[key] as number) : null);
  const latestSjr = data.scimagojr.at(-1);
  const topics = Array.from(
    new Set(
      (data.topics as NamedTopic[])
        .map((t) => t?.display_name)
        .filter((n): n is string => Boolean(n)),
    ),
  );
  const oaTopics = (openalex?.topics ?? []).filter(
    (t): t is OpenalexTopic & { display_name: string } => Boolean(t?.display_name),
  );
  const hasApc = data.apc_aggregates.length > 0 || data.apc_evidence.length > 0;
  // One nav entry per rendered section, in DOM order.
  const sections: { id: string; label: string; hint?: string }[] = [
    { id: "oa-per-year", label: "Open access per year" },
    ...(deals.length > 0
      ? deals.map((deal) => ({
          id: `deal-${deal.id}`,
          label: "Open access deal",
        }))
      : [{ id: "deal", label: "Open access deal" }]),
    ...(greenOa ? [{ id: "green-oa", label: "Green OA policy" }] : []),
    ...(hasApc
      ? [{ id: "apc", label: "APC cost evidence", hint: "APC = article processing charge" }]
      : []),
    ...(!similarEmpty ? [{ id: "similar", label: "Similar journals" }] : []),
    ...(topics.length > 0 || oaTopics.length > 0 ? [{ id: "topics", label: "Topics" }] : []),
    { id: "metrics", label: "Key stats" },
    { id: "ut-authorship", label: "UT authorship" },
    { id: "publications", label: "Publications" },
    ...(data.openalex_only.available ? [{ id: "cris-gaps", label: "Not registered in Pure" }] : []),
    ...(data.alternate_titles.length > 0 ? [{ id: "names", label: "Other names" }] : []),
    { id: "identifiers", label: "Identifiers" },
    { id: "cite", label: "Cite this journal" },
  ];

  return (
    <>
      <SectionNav sections={sections} />
      <div className="mx-auto max-w-5xl px-4 py-10">
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
                  <ExternalLink aria-hidden className="size-5 text-[var(--muted-foreground)]" />
                </a>
              ) : (
                (journal.title ?? journal.issn_l)
              )}
            </h1>
            <OaTypeBadge oaType={journal.oa_type} isOa={journal.is_oa} />
            <QuartileBadge quartile={journal.quartile ?? null} />
            <DealBadge covered={journal.deal_covered} />
            {journal.is_in_doaj && (
              <Badge
                variant="outline"
                title="Listed in DOAJ, the Directory of Open Access Journals"
              >
                DOAJ
              </Badge>
            )}
            <Badge
              variant="muted"
              className="font-normal tabular-nums"
              title="ISSN-L links the print and online ISSNs of one journal into a single identifier"
            >
              ISSN-L {journal.issn_l}
            </Badge>
          </div>
          <p className="mt-1.5 text-[var(--muted-foreground)]">
            {journal.publisher_canonical || journal.publisher_name ? (
              <Link
                href={`/${inst}/publisher/${encodeNamePath(
                  journal.publisher_canonical ?? journal.publisher_name ?? "",
                )}`}
                className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
              >
                {journal.publisher_canonical ?? journal.publisher_name}
              </Link>
            ) : (
              "Unknown publisher"
            )}
            {journal.publisher_canonical &&
              journal.publisher_name &&
              journal.publisher_canonical !== journal.publisher_name && (
                <span className="text-sm"> · imprint: {journal.publisher_name}</span>
              )}
            {data.type ? ` · ${data.type.charAt(0).toUpperCase()}${data.type.slice(1)}` : ""}
          </p>
          {data.homepage_url && (
            <p className="mt-1.5 text-xs">
              <External href={data.homepage_url}>Journal homepage</External>
            </p>
          )}
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">
            <SourceNote source="Metadata: OpenAlex" url={attribution.title?.url ?? undefined} />
          </p>
        </header>

        <div className="space-y-6">
          <CollapsibleCard
            id="oa-per-year"
            title={
              <>
                Open access per year{" "}
                <span className="text-sm font-normal text-[var(--muted-foreground)]">
                  ({site.short}
                  {year_from !== undefined
                    ? `, ${year_from}–${year_to}`
                    : site.windowStart === undefined
                      ? ""
                      : `, ${site.windowStart}+`}
                  )
                </span>
              </>
            }
          >
            {recent.length > 0 ? (
              <OaTrend stats={recent} />
            ) : (
              <p className="text-sm text-[var(--muted-foreground)]">
                No publication statistics for this period yet.
              </p>
            )}
            <p className="mt-3 text-sm">
              {year_from === undefined ? (
                <>
                  {totals.pure_canon.toLocaleString("en")} {site.short} works total
                  {site.windowStart === undefined ? "" : ` since ${site.windowStart}`}{" "}
                  <span className="text-[var(--muted-foreground)]">(Pure)</span> · OpenAlex
                  institution filter:{" "}
                  <span className="whitespace-nowrap">
                    {totals.openalex_institution_filter.toLocaleString("en")}{" "}
                    <span className="text-[var(--muted-foreground)]">(cross-check)</span>
                  </span>
                  .
                </>
              ) : (
                <>
                  {pureTotal.toLocaleString("en")} {site.short} works in {year_from}–{year_to}{" "}
                  <span className="text-[var(--muted-foreground)]">(Pure)</span>.
                </>
              )}
            </p>
            <div className="mt-2 flex flex-wrap gap-x-4">
              <SourceNote {...(attribution.stats ?? {})} codes={attribution.stats?.caveat_codes} />
              <SourceNote
                {...(attribution.oa_status ?? {})}
                codes={attribution.oa_status?.caveat_codes}
              />
            </div>
          </CollapsibleCard>

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
              No current open access deal covering this journal for {site.name} authors. Check{" "}
              <External href="https://www.openaccess.nl">openaccess.nl</External> and the{" "}
              <External href="https://journalcheckertool.org">Journal Checker Tool</External> to
              double-check; for green open access routes (self-archiving), see the library&apos;s
              open access guide linked in the footer.
              <div className="mt-2">
                <SourceNote
                  {...(attribution.deals ?? {})}
                  codes={attribution.deals?.caveat_codes}
                />
              </div>
            </CollapsibleCard>
          )}

          {greenOa && <GreenOaPanel greenOa={greenOa} attribution={attribution.green_oa ?? {}} />}

          {funder && <FunderFitCard fit={data.funder_fit ?? null} funder={funder} inst={inst} />}

          {hasApc && (
            <CollapsibleCard id="apc" title="APC cost evidence" contentClassName="text-sm">
              {data.apc_aggregates.length > 0 && (
                <table className="w-full text-xs">
                  <caption className="sr-only">
                    OpenAPC cost evidence per publishing year: number of recorded APCs, mean, and
                    observed range in euros
                  </caption>
                  <thead>
                    <tr className="text-left text-[var(--muted-foreground)]">
                      <th
                        className="py-1 pr-2 font-medium"
                        title="Publishing year of the articles with recorded APCs"
                      >
                        Year
                      </th>
                      <th
                        className="py-1 pr-2 font-medium"
                        title="Articles with an APC recorded in OpenAPC for this journal and year"
                      >
                        APCs
                      </th>
                      <th className="py-1 pr-2 font-medium" title="Average APC paid, in euros">
                        Mean €
                      </th>
                      <th
                        className="py-1 font-medium"
                        title="Lowest to highest APC recorded, in euros"
                      >
                        Range €
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.apc_aggregates.map((a) => (
                      <tr key={a.period} className="border-t border-[var(--border)]">
                        <td className="py-1 pr-2 tabular-nums">{a.period}</td>
                        <td className="py-1 pr-2 tabular-nums">{a.article_count}</td>
                        <td className="py-1 pr-2 tabular-nums">
                          {a.euro_mean !== null
                            ? Math.round(a.euro_mean).toLocaleString("en")
                            : "—"}
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
                  {data.apc_evidence.length} {site.short} APC{" "}
                  {data.apc_evidence.length === 1 ? "record" : "records"} (latest{" "}
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

          {similar && !similarEmpty && (
            <CollapsibleCard id="similar" title="Similar journals">
              <div className="space-y-5">
                {(
                  [
                    {
                      key: "institution",
                      heading: `${site.short} publishes here`,
                      note: `Nearest neighbors that carry at least one ${site.name} publication.`,
                    },
                    {
                      key: "deals",
                      heading: "Covered by a publication deal",
                      note: `Nearest neighbors with a current open access deal for ${site.short} authors.`,
                    },
                    {
                      key: "all",
                      heading: "Most similar overall",
                      note: `Nearest neighbors by research-profile similarity alone, regardless of deals or ${site.short} output.`,
                    },
                  ] as const
                ).map(
                  (group) =>
                    similar[group.key].length > 0 && (
                      <div key={group.key}>
                        <h3 className="text-sm font-semibold">{group.heading}</h3>
                        {group.note && (
                          <p className="mb-1 text-xs text-[var(--muted-foreground)]">
                            {group.note}
                          </p>
                        )}
                        <ul className="divide-y divide-[var(--border)]">
                          {(openSimilar[group.key]
                            ? similar[group.key]
                            : similar[group.key].slice(0, SIMILAR_LIMIT)
                          ).map((s) => (
                            <li
                              key={s.issn_l}
                              className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-2 text-sm first:pt-0 last:pb-0"
                            >
                              <Link
                                href={`/${inst}/journals/${s.issn_l}`}
                                className="font-medium underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                              >
                                {s.title ?? s.issn_l}
                              </Link>
                              <span className="text-xs text-[var(--muted-foreground)]">
                                {s.publisher_canonical ?? s.publisher_name ?? "Unknown publisher"}
                              </span>
                              <span className="ml-auto flex flex-wrap items-center gap-2">
                                <DealBadge covered={s.deal_covered} />
                                {s.works > 0 && (
                                  <span
                                    className="text-xs text-[var(--muted-foreground)]"
                                    title={`Known ${site.name} publications in this journal`}
                                  >
                                    {s.works.toLocaleString("en")} {site.short}{" "}
                                    {s.works === 1 ? "publication" : "publications"}
                                  </span>
                                )}
                                <QuartileBadge quartile={s.quartile ?? null} />
                                <span
                                  className="text-xs text-[var(--muted-foreground)]"
                                  title="Embedding similarity between the journals' research profiles"
                                >
                                  {s.similarity != null
                                    ? `${Math.round(s.similarity * 100)}% match`
                                    : `${s.shared_topics} shared ${
                                        s.shared_topics === 1 ? "topic" : "topics"
                                      }`}
                                  {s.similarity != null && (
                                    <span className="sr-only"> (embedding similarity)</span>
                                  )}
                                </span>
                              </span>
                            </li>
                          ))}
                        </ul>
                        {similar[group.key].length > SIMILAR_LIMIT && (
                          <MoreToggle
                            open={!!openSimilar[group.key]}
                            onToggle={() =>
                              setOpenSimilar((m) => ({ ...m, [group.key]: !m[group.key] }))
                            }
                            moreLabel={`Show all ${similar[group.key].length} journals`}
                          />
                        )}
                      </div>
                    ),
                )}
              </div>
            </CollapsibleCard>
          )}

          {(oaTopics.length > 0 || topics.length > 0) && (
            <CollapsibleCard
              id="topics"
              title="Topics"
              description={
                <p className="text-sm text-[var(--muted-foreground)]">
                  {oaTopics.length > 0
                    ? "Topics assigned by OpenAlex; the number is works in this journal classified under the topic."
                    : "Topics assigned by OpenAlex."}
                </p>
              }
              contentClassName="flex flex-wrap items-center gap-1.5"
            >
              {oaTopics.length > 0
                ? (allTopics ? oaTopics : oaTopics.slice(0, TOPICS_LIMIT)).map((topic) => (
                    <Link
                      key={topic.id}
                      href={`/?topic=${encodeURIComponent(topic.display_name)}&search_in=topic`}
                      className="inline-flex items-center gap-1.5 rounded-full bg-[var(--muted)] px-2.5 py-1 text-sm font-normal normal-case underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                      title={[
                        [
                          topic.subfield?.display_name,
                          topic.field?.display_name,
                          topic.domain?.display_name,
                        ]
                          .filter(Boolean)
                          .join(" → "),
                        `${(topic.count ?? 0).toLocaleString("en")} works`,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    >
                      {topic.display_name}
                      <span className="tabular-nums text-[var(--muted-foreground)]">
                        {(topic.count ?? 0).toLocaleString("en")}
                      </span>
                    </Link>
                  ))
                : (allTopics ? topics : topics.slice(0, TOPICS_LIMIT)).map((topic) => (
                    <Badge key={topic} variant="muted" className="font-normal normal-case">
                      {topic}
                    </Badge>
                  ))}
              {(oaTopics.length > 0 ? oaTopics.length : topics.length) > TOPICS_LIMIT && (
                <MoreToggle
                  open={allTopics}
                  onToggle={() => setAllTopics((v) => !v)}
                  moreLabel={`+${
                    (oaTopics.length > 0 ? oaTopics.length : topics.length) - TOPICS_LIMIT
                  } more`}
                />
              )}
              {oaTopics.length > 0 && (
                <SourceNote
                  {...(attribution.openalex ?? {})}
                  codes={attribution.openalex?.caveat_codes}
                />
              )}
            </CollapsibleCard>
          )}

          <CollapsibleCard id="metrics" title="Key stats" contentClassName="space-y-4 text-sm">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <Metric
                label="2-year mean citedness"
                hint="Average number of citations that works from the last two years have received, as counted by OpenAlex."
                value={
                  journal.twoyr_mean_citedness != null
                    ? journal.twoyr_mean_citedness.toFixed(1)
                    : "—"
                }
              />
              <Metric
                label="h-index"
                hint="h works of this journal have received at least h citations each (OpenAlex)."
                value={num("h_index")?.toLocaleString("en") ?? "—"}
                note="OpenAlex"
              />
              <Metric
                label="i10 index"
                hint="Number of works of this journal with at least 10 citations (OpenAlex)."
                value={num("i10_index")?.toLocaleString("en") ?? "—"}
                note="OpenAlex"
              />
            </div>
            <SourceNote
              {...(attribution.metrics ?? {})}
              codes={attribution.metrics?.caveat_codes}
            />
            {(openalex || metrics || openaire) && (
              <div className="border-t border-[var(--border)] pt-4">
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                  {openalex?.cited_by_count != null && (
                    <Metric
                      label="Total citations"
                      hint="All citations to works of this journal that OpenAlex has recorded."
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
                      hint="Number of works of this journal known to OpenAlex."
                      value={openalex.works_count.toLocaleString("en")}
                      note={
                        <SourceNote
                          {...(attribution.openalex ?? {})}
                          codes={attribution.openalex?.caveat_codes}
                        />
                      }
                    />
                  )}
                  {metrics && (
                    <Metric
                      label={`FWCI (${site.short} works)`}
                      hint={`Field-weighted citation impact of ${site.short} works: citations relative to the average for works of the same year, type, and field. 1.0 means average.`}
                      value={
                        metrics.fwci_avg != null && metrics.fwci_n > 0
                          ? metrics.fwci_avg.toFixed(2)
                          : "—"
                      }
                      note={
                        <>
                          n = {metrics.fwci_n} works{" "}
                          <SourceNote
                            {...(attribution.openalex ?? {})}
                            codes={attribution.openalex?.caveat_codes}
                          />
                        </>
                      }
                    />
                  )}
                  {metrics && metrics.retracted > 0 && (
                    <Metric
                      label={`Retracted ${site.short} works`}
                      hint={`${site.short} works in this journal that OpenAlex marks as retracted.`}
                      value={metrics.retracted.toLocaleString("en")}
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
                      hint={`${site.name} publications that OpenAIRE matched to this journal.`}
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
                    hint="SCImago Journal Rank: prestige-weighted average citations per recent work. Higher is better."
                    value={latestSjr.sjr !== null ? latestSjr.sjr.toFixed(3) : "—"}
                    note={latestSjr.year ? String(latestSjr.year) : undefined}
                  />
                  <Metric
                    label="Best quartile"
                    hint="Best quartile the journal reaches in any of its SCImago subject categories."
                    value={latestSjr.best_quartile ?? "—"}
                  />
                  <Metric
                    label="SJR h-index"
                    hint="h-index of the journal as computed by SCImago."
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

          <UtAuthorshipCard authorship={data.ut_authorship} inst={inst} />

          <PublicationsCard
            key={journal.issn_l}
            title={journal.title ?? journal.issn_l}
            openalex={openalex}
            worksNote={attribution.works ?? {}}
            requested={requestedWorksPage}
            worksQuery={worksQuery}
          />

          {data.openalex_only.available && (
            <CrisGapsCard openalexOnly={data.openalex_only} inst={inst} issnL={journal.issn_l} />
          )}

          {data.alternate_titles.length > 0 && <OtherNamesCard names={data.alternate_titles} />}

          <IdentifiersCard
            issnL={journal.issn_l}
            issns={data.issns}
            doajUrl={data.doaj_homepage_url}
            openalexUrl={openalex?.url}
            oaNlSlug={data.openaccess_nl_slug}
          />

          <CitationCard data={data} />
        </div>
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
