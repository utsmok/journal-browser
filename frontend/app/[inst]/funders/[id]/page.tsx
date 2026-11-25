"use client";

import { ArrowRight, Check, ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import { CardPager } from "@/components/card-pager";
import { CollapsibleCard } from "@/components/collapsible-card";
import { ACCESS_TEXT, DataIcon, GreenGlyph, LockIcon, WorksGlyph } from "@/components/data-icons";
import { DetailSummaryPanel } from "@/components/detail-summary";
import { SectionNav, useLastDirectoryHref } from "@/components/journal/section-nav";
import { MoreToggle } from "@/components/journal/shared";
import { SourceNote } from "@/components/source-note";
import { DetailSkeleton, ErrorPanel } from "@/components/states";
import { InsetPanel } from "@/components/sub-panel";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useFunder } from "@/hooks/use-api";
import { useInstitution } from "@/hooks/use-institution";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { useYearRange } from "@/hooks/use-year-filter";
import { errorMessage, type FunderDetailResponse } from "@/lib/api";
import { countryName } from "@/lib/format";
import { useFunderPrefs } from "@/lib/funder-prefs";

const ROR_URL = "https://ror.org/";
const FUNDREF_URL = "https://doi.org/10.13039/";
const OPF_URL = "https://openpolicyfinder.jisc.ac.uk/";
const OPENAIRE_URL = "https://openaire.eu";
const PAGE_SIZE = 10;

function CanonLinks({ funder }: { funder: FunderDetailResponse }) {
  const t = useTranslations("funders");
  const links: { label: string; href: string }[] = [];
  if (funder.ror) links.push({ label: t("detail.ror"), href: ROR_URL + funder.ror });
  if (funder.fundref)
    links.push({ label: t("detail.fundref"), href: FUNDREF_URL + funder.fundref });
  if (funder.openalex_funder_id)
    links.push({ label: t("detail.openalex"), href: funder.openalex_funder_id });
  if (funder.url) links.push({ label: t("detail.website"), href: funder.url });
  return (
    <p className="flex flex-wrap gap-3 text-xs [&>a]:min-h-11 [&>a]:min-w-11 min-[1024px]:[&>a]:min-h-0 min-[1024px]:[&>a]:min-w-0">
      {links.map((l) => (
        <a
          key={l.label}
          href={l.href}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-0.5 text-[var(--primary-text)] underline-offset-2 hover:underline"
        >
          {l.label}
          <ExternalLink aria-hidden className="size-3.5" />
        </a>
      ))}
    </p>
  );
}

function policyValue(v: unknown, yesLabel: string, noLabel: string): string {
  if (typeof v === "boolean") return v ? yesLabel : noLabel;
  if (typeof v === "string") return v.replaceAll("_", " ");
  if (Array.isArray(v)) return v.map((x) => policyValue(x, yesLabel, noLabel)).join("; ");
  if (v && typeof v === "object") {
    return Object.values(v as Record<string, unknown>)
      .map((x) => policyValue(x, yesLabel, noLabel))
      .join("; ");
  }
  return String(v ?? "");
}

function reqSummary(t: (key: string) => string, req: string | null | undefined): string {
  switch (req) {
    case "requires":
      return t("search.facets.reqRequires");
    case "encourages":
      return t("search.facets.reqEncourages");
    case "no_policy_for":
      return t("search.facets.reqNone");
    case "does_no_mention":
      return t("search.facets.reqNotMentioned");
    default:
      return "—";
  }
}

const POLICY_LABEL_KEYS: Record<string, string> = {
  what: "detail.policy.what",
  when: "detail.policy.when",
  where: "detail.policy.where",
  license: "detail.policy.license",
  requirement: "detail.policy.requirement",
  special_conditions: "detail.policy.specialConditions",
  conditions: "detail.policy.conditions",
};

const NON_RULE_KEYS: Record<string, true> = { urls: true, notes: true, scope: true };

function PolicyRules({ rules }: { rules: Record<string, unknown> }) {
  const t = useTranslations("funders");
  const rows: [string, unknown][] = [];
  const seen = new Set<string>();
  for (const [k, key] of Object.entries(POLICY_LABEL_KEYS)) {
    if (k in rules) {
      rows.push([t(key), rules[k]]);
      seen.add(k);
    }
  }
  for (const k of Object.keys(rules)) {
    if (!seen.has(k) && !(k in NON_RULE_KEYS)) {
      rows.push([k.charAt(0).toUpperCase() + k.slice(1).replaceAll("_", " "), rules[k]]);
    }
  }
  if (rows.length === 0) return null;
  return (
    <dl className="grid grid-cols-[8.5rem_1fr] gap-x-3 gap-y-1 text-xs sm:text-sm">
      {rows.map(([label, value]) => (
        <React.Fragment key={label}>
          <dt className="text-[var(--muted-foreground)]">{label}</dt>
          <dd>{policyValue(value, t("detail.policy.yes"), t("detail.policy.no")) || "—"}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

function PolicyUrls({ urls }: { urls: unknown }) {
  if (!Array.isArray(urls) || urls.length === 0) return null;
  return (
    <ul className="mb-2.5 space-y-1 text-xs">
      {urls.map((u: { url?: string; description?: string }, i: React.Key) =>
        u?.url ? (
          <li key={i}>
            <a
              href={u.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex min-h-11 min-w-11 items-center gap-1 text-[var(--primary-text)] underline-offset-2 hover:underline min-[1024px]:min-h-0 min-[1024px]:min-w-0"
            >
              {u.description || u.url}
              <ExternalLink aria-hidden className="size-3" />
            </a>
          </li>
        ) : null,
      )}
    </ul>
  );
}

function PolicyBlock({ data }: { data: Record<string, unknown> | null | undefined }) {
  const t = useTranslations("funders");
  if (!data)
    return (
      <p className="text-sm text-[var(--muted-foreground)]">{t("detail.policy.notHarvested")}</p>
    );
  const RULE_KEYS = [
    "what",
    "when",
    "where",
    "license",
    "requirement",
    "conditions",
    "special_conditions",
  ];
  const flat = RULE_KEYS.some((k) => k in data) ? data : null;
  const rules = flat
    ? []
    : ([
        [t("detail.policy.archivingRules"), data.archiving_policy],
        [t("detail.policy.publishingRules"), data.publishing_policy],
      ].filter(([, v]) => v && typeof v === "object") as [string, Record<string, unknown>][]);
  const notes = Array.isArray(data.notes) ? (data.notes as string[]) : [];
  const scope = Array.isArray(data.scope) ? (data.scope as string[]) : [];
  return (
    <div className="text-sm">
      <PolicyUrls urls={data.urls} />
      {notes.map((n, i) => (
        <p key={i} className="mb-2 text-xs last:mb-0 sm:text-sm">
          {n}
        </p>
      ))}
      {scope.length > 0 && (
        <p className="mt-2.5 text-xs text-[var(--muted-foreground)]">
          {t("detail.policy.scope", {
            scope: scope
              .map((v) => policyValue(v, t("detail.policy.yes"), t("detail.policy.no")))
              .join(", "),
          })}
        </p>
      )}
      {flat && (
        <div className="mt-3 border-t border-[var(--border)] pt-2.5">
          <PolicyRules rules={flat} />
        </div>
      )}
      {rules.map(([label, block]) => (
        <div key={label} className="mt-3 border-t border-[var(--border)] pt-2.5">
          <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
            {label}
          </p>
          <PolicyRules rules={block} />
        </div>
      ))}
      {!flat && rules.length === 0 && (
        <div className="mt-2.5">
          <PolicyRules rules={data} />
        </div>
      )}
    </div>
  );
}

function OpenaireCard({ oa }: { oa: NonNullable<FunderDetailResponse["openaire"]> }) {
  const t = useTranslations("funders");
  const [showAllStreams, setShowAllStreams] = React.useState(false);
  const visibleStreams = showAllStreams ? oa.streams : oa.streams.slice(0, PAGE_SIZE);
  return (
    <CollapsibleCard
      id="funder-openaire"
      title={t("detail.openaire.title")}
      count={oa.streams.length > 0 ? oa.streams.length : undefined}
      defaultOpen={false}
      compact
      contentClassName="space-y-3 text-sm"
    >
      <dl className="grid grid-cols-[9rem_1fr] gap-x-3 gap-y-1 text-xs sm:text-sm">
        <dt className="text-[var(--muted-foreground)]">{t("detail.openaire.name")}</dt>
        <dd>{oa.name ?? "—"}</dd>
        {oa.short_name && (
          <>
            <dt className="text-[var(--muted-foreground)]">{t("detail.openaire.shortName")}</dt>
            <dd>{oa.short_name}</dd>
          </>
        )}
        {oa.jurisdiction && (
          <>
            <dt className="text-[var(--muted-foreground)]">{t("detail.openaire.jurisdiction")}</dt>
            <dd>{oa.jurisdiction}</dd>
          </>
        )}
        <dt className="text-[var(--muted-foreground)]">{t("detail.openaire.id")}</dt>
        <dd className="break-all">{oa.openaire_id}</dd>
      </dl>
      {oa.streams.length > 0 && (
        <InsetPanel title={t("detail.openaire.streams")} count={oa.streams.length}>
          <ul className="divide-y divide-[var(--border)] text-xs sm:text-sm">
            {visibleStreams.map((s) => (
              <li
                key={s.level0_id}
                className="flex justify-between gap-3 py-1.5 first:pt-0 last:pb-0"
              >
                <span className="min-w-0 truncate">{s.name ?? s.level0_id}</span>
                <span className="shrink-0 tabular-nums text-[var(--muted-foreground)]">
                  {s.n_projects.toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
          {oa.streams.length > PAGE_SIZE && (
            <div className="mt-1.5 border-t border-[var(--border)] pt-1.5">
              <MoreToggle
                open={showAllStreams}
                onToggle={() => setShowAllStreams((v) => !v)}
                moreLabel={t("detail.openaire.showAllStreams", { count: oa.streams.length })}
              />
            </div>
          )}
        </InsetPanel>
      )}
      <div className="border-t border-[var(--border)] pt-2">
        <SourceNote
          source={t("detail.openaire.source")}
          url={OPENAIRE_URL}
          codes={["openaire-enrichment"]}
        />
      </div>
    </CollapsibleCard>
  );
}

export default function FunderPage() {
  const t = useTranslations("funders");
  const tc = useTranslations("common");
  const params = useParams<{ id: string }>();
  const inst = useInstitution();
  const site = useSiteMeta();
  const [funder, setFunder] = useFunderPrefs();
  const id = params?.id ? Number(params.id) : undefined;
  const { year_from, year_to } = useYearRange();
  const backHref = useLastDirectoryHref("jb-last-funders", `/${inst}/funders`);
  const { data, isPending, isError, error } = useFunder(id, { year_from, year_to });
  const [journalPage, setJournalPage] = React.useState(1);

  React.useEffect(() => {
    setJournalPage(1);
  }, [id]);

  if (isPending) {
    return (
      <DetailSkeleton
        sections={[
          t("detail.oaTrendTitle"),
          t("detail.publicationsPolicy"),
          t("detail.dataPolicy"),
        ]}
      />
    );
  }
  if (isError || !data) {
    return (
      <ErrorPanel
        message={errorMessage(tc, error)}
        backHref={backHref}
        backLabel={t("detail.backToList")}
      />
    );
  }

  const trendYears = [...(data.works_by_year ?? [])].sort((a, b) => a.year - b.year);
  const mine = funder?.id === data.id;
  const journalPages = Math.max(1, Math.ceil(data.top_journals.length / PAGE_SIZE));
  const journalRows = data.top_journals.slice(
    (journalPage - 1) * PAGE_SIZE,
    journalPage * PAGE_SIZE,
  );

  const sections: { id: string; label: string }[] = [
    { id: "overview", label: t("detail.navOverview") },
    { id: "funder-publications-policy", label: t("detail.navPubPolicy") },
    { id: "funder-data-policy", label: t("detail.navDataPolicy") },
    ...(data.top_journals.length > 0
      ? [{ id: "funder-top-journals", label: t("detail.navJournals") }]
      : []),
    ...(data.openaire ? [{ id: "funder-openaire", label: t("detail.navOpenaire") }] : []),
  ];

  return (
    <>
      <SectionNav
        sections={sections}
        backFallback={`/${inst}/funders`}
        backStorageKey="jb-last-funders"
        backLabel={t("detail.backToList")}
      />
      <div className="mx-auto max-w-screen-2xl px-4 py-6">
        <header className="mb-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h1 className="text-2xl font-bold tracking-tight text-balance sm:text-3xl">
              {data.name}
            </h1>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant={mine ? "default" : "outline"}
                size="sm"
                aria-pressed={mine}
                onClick={() =>
                  setFunder(
                    mine
                      ? null
                      : { id: data.id, name: data.name ?? t("unnamedFunder", { id: data.id }) },
                  )
                }
                title={mine ? t("detail.myFunderHintOn") : t("detail.myFunderHintOff")}
              >
                {mine ? (
                  <>
                    <Check aria-hidden className="size-4" />
                    {t("detail.yourFunder")}
                  </>
                ) : (
                  t("detail.useAsMyFunder")
                )}
              </Button>
              {data.openalex_funder_id && (
                <Link
                  href={`/${inst}/collaborations?funder=${encodeURIComponent(`openalex:${data.openalex_funder_id.replace(/^https?:\/\/openalex\.org\//, "")}`)}`}
                  className="inline-flex min-h-11 items-center gap-1 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] px-3 text-sm font-medium hover:border-[var(--primary)] hover:text-[var(--primary-text)] min-[1024px]:h-8 min-[1024px]:min-h-0 min-[1024px]:text-xs"
                >
                  {t("detail.explorePartners")}
                  <ArrowRight aria-hidden className="size-3.5" />
                </Link>
              )}
            </div>
          </div>
          <div className="mt-1.5">
            <CanonLinks funder={data} />
          </div>
        </header>

        <div className="space-y-4">
          <DetailSummaryPanel
            id="overview"
            stats={[
              { label: t("detail.kpiCountry"), value: countryName(data.country) },
              {
                label: t("detail.kpiWorks", { inst: site.short }),
                value: data.n_ut_works.toLocaleString("en"),
                icon: (
                  <DataIcon className={`size-3.5 ${ACCESS_TEXT.brand}`}>
                    <WorksGlyph />
                  </DataIcon>
                ),
              },
              {
                label: t("detail.kpiPolicy"),
                value: data.policy_structured
                  ? t("detail.policyShortStructured")
                  : t("detail.policyShortText"),
              },
              {
                label: t("detail.kpiOaPub"),
                value: reqSummary(t, data.oa_publishing_req),
                icon: (
                  <DataIcon className={`size-3.5 ${ACCESS_TEXT.gold}`}>
                    <LockIcon state="open" />
                  </DataIcon>
                ),
              },
              {
                label: t("detail.kpiGreen"),
                value: reqSummary(t, data.green_archiving_req),
                icon: (
                  <DataIcon className={`size-3.5 ${ACCESS_TEXT.deal}`}>
                    <GreenGlyph />
                  </DataIcon>
                ),
              },
              {
                label: t("detail.kpiData"),
                value: reqSummary(t, data.data_policy_req),
              },
            ]}
            trendStats={trendYears}
            trendTitle={t("detail.oaTrendTitle")}
            trendFooter={
              <SourceNote
                source={t("detail.worksSource", { inst: site.short })}
                url={OPENAIRE_URL}
                codes={["openalex-coverage", "openaire-enrichment"]}
              />
            }
          />

          {/* Block 3: Side-by-side Policies */}
          <div className="grid gap-4 lg:grid-cols-2">
            <CollapsibleCard
              id="funder-publications-policy"
              title={t("detail.publicationsPolicy")}
              compact
            >
              <PolicyBlock data={data.publications_policy} />
              <div className="mt-2.5 border-t border-[var(--border)] pt-2">
                <SourceNote
                  source={t("sourceJisc")}
                  url={OPF_URL}
                  codes={["jisc-policy-currency"]}
                />
              </div>
            </CollapsibleCard>

            <CollapsibleCard id="funder-data-policy" title={t("detail.dataPolicy")} compact>
              <PolicyBlock data={data.data_archiving_policy} />
              <div className="mt-2.5 border-t border-[var(--border)] pt-2">
                <SourceNote
                  source={t("sourceJisc")}
                  url={OPF_URL}
                  codes={["jisc-policy-currency"]}
                />
              </div>
            </CollapsibleCard>
          </div>

          {/* Block 4: Top Journals */}
          {data.top_journals.length > 0 && (
            <CollapsibleCard
              id="funder-top-journals"
              title={t("instWorks", { inst: site.short })}
              count={data.top_journals.length}
              compact
              contentClassName="space-y-3 text-sm [&_td]:py-1.5 [&_th]:h-8"
            >
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("detail.journal")}</TableHead>
                    <TableHead>{t("detail.issnL")}</TableHead>
                    <TableHead className="text-right">{t("detail.works")}</TableHead>
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
                          {j.title ?? j.issn_l}
                        </Link>
                      </TableCell>
                      <TableCell className="tabular-nums text-[var(--muted-foreground)]">
                        {j.issn_l}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {j.n_works.toLocaleString("en")}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {journalPages > 1 && (
                <CardPager
                  page={journalPage}
                  pages={journalPages}
                  total={data.top_journals.length}
                  onPage={setJournalPage}
                  label={t("detail.pagerJournals")}
                />
              )}
              <div className="border-t border-[var(--border)] pt-2.5">
                <SourceNote
                  source={t("detail.worksSource", { inst: site.short })}
                  url={OPENAIRE_URL}
                  codes={["openalex-coverage", "openaire-enrichment"]}
                />
              </div>
            </CollapsibleCard>
          )}

          {/* Block 5: OpenAIRE Reference */}
          {data.openaire && <OpenaireCard oa={data.openaire} />}
        </div>
      </div>
    </>
  );
}
