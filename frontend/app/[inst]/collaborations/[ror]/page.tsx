"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import { DealBadge, OaStatusChip, OaTypeBadge, QuartileBadge } from "@/components/badges";
import { CardPager } from "@/components/card-pager";
import { ActiveFiltersBar } from "@/components/collaborations/active-filters";
import { BarList } from "@/components/collaborations/bar-list";
import { orgTypeCssVar, useCollabLabels } from "@/components/collaborations/labels";
import { CollaborationSources } from "@/components/collaborations/sources";
import {
  EMPTY_COLLAB_FILTERS,
  useCollabParams,
  writeCollabParams,
} from "@/components/collaborations/use-collab-params";
import { CollapsibleCard } from "@/components/collapsible-card";
import { ACCESS_TEXT, DataIcon, LockIcon, WorksGlyph } from "@/components/data-icons";
import { DetailSummaryPanel } from "@/components/detail-summary";
import { GapCsvButton } from "@/components/gap-csv-button";
import { SectionNav } from "@/components/journal/section-nav";
import { MoreToggle } from "@/components/journal/shared";
import { ErrorPanel, ListSkeletonRows } from "@/components/states";
import { TopicChipList } from "@/components/topic-chips";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useCollaboration, useCollaborationWorks } from "@/hooks/use-api";
import { useInstitution } from "@/hooks/use-institution";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { useYearRange } from "@/hooks/use-year-filter";
import {
  ApiError,
  collaborationCsvHref,
  encodeNamePath,
  errorMessage,
  type StatsYear,
} from "@/lib/api";
import { workTypeLabel } from "@/lib/work-type";

const PAGE_SIZE = 10;
const SUBLIST_CAP = 10;
const linkClass = "underline-offset-2 hover:text-[var(--primary-text)] hover:underline";
const dottedLink = "underline decoration-dotted underline-offset-2 hover:decoration-solid";
const external = { target: "_blank", rel: "noopener noreferrer" } as const;

function CreditsList({
  title,
  empty,
  rows,
  showAllLabel,
}: {
  title: string;
  empty: string;
  showAllLabel: (count: number) => string;
  rows: {
    key: string;
    label: string;
    note: string;
    works: number;
    href?: string;
  }[];
}) {
  const [open, setOpen] = React.useState(false);
  const visible = open ? rows : rows.slice(0, SUBLIST_CAP);
  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
        {title}
      </h3>
      {rows.length === 0 ? (
        <p className="mt-2 text-sm text-[var(--muted-foreground)]">{empty}</p>
      ) : (
        <>
          <ol className="mt-1 divide-y divide-[var(--border)]">
            {visible.map((row) => (
              <li
                key={row.key}
                className="flex items-baseline justify-between gap-3 py-1.5 text-sm"
              >
                <span className="min-w-0 truncate">
                  {row.href ? (
                    <Link href={row.href} className={`font-medium ${linkClass}`}>
                      {row.label}
                    </Link>
                  ) : (
                    <span className="font-medium">{row.label}</span>
                  )}
                  {row.note && (
                    <span className="ml-2 text-xs text-[var(--muted-foreground)]">{row.note}</span>
                  )}
                </span>
                <span className="shrink-0 tabular-nums">{row.works.toLocaleString("en")}</span>
              </li>
            ))}
          </ol>
          {rows.length > SUBLIST_CAP && (
            <div className="mt-1.5">
              <MoreToggle
                open={open}
                onToggle={() => setOpen((o) => !o)}
                moreLabel={showAllLabel(rows.length)}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}

function PartnerPageInner() {
  const t = useTranslations("collaborations");
  const tc = useTranslations("common");
  const inst = useInstitution();
  const site = useSiteMeta();
  const labels = useCollabLabels();
  const { ror } = useParams<{ ror: string }>();
  const { year_from, year_to } = useYearRange();
  const [filters, updateFilters] = useCollabParams();
  const [worksPage, setWorksPage] = React.useState(1);
  const [journalPage, setJournalPage] = React.useState(1);
  const [collabExpanded, setCollabExpanded] = React.useState<Record<string, boolean>>({});
  const [worksOpened, setWorksOpened] = React.useState(false);

  const params = React.useMemo(
    () => ({ ...filters, year_from, year_to }),
    [filters, year_from, year_to],
  );

  React.useEffect(() => {
    setWorksPage(1);
    setJournalPage(1);
  }, [params]);

  const offset = (worksPage - 1) * PAGE_SIZE;
  const detail = useCollaboration(ror, params);
  const works = useCollaborationWorks(ror ?? "", params, offset, PAGE_SIZE);
  const d = detail.data;

  const listQuery = writeCollabParams(filters);
  const listHref = `/${inst}/collaborations${listQuery ? `?${listQuery}` : ""}`;

  const linkTypes: Record<string, string> = {
    website: t("detail.linkTypes.website"),
    wikipedia: t("detail.linkTypes.wikipedia"),
    linkedin: t("detail.linkTypes.linkedin"),
    twitter: t("detail.linkTypes.twitter"),
    facebook: t("detail.linkTypes.facebook"),
    instagram: t("detail.linkTypes.instagram"),
    youtube: t("detail.linkTypes.youtube"),
    github: t("detail.linkTypes.github"),
  };
  const relationTypes: Record<string, string> = {
    parent: t("detail.relationTypes.parent"),
    child: t("detail.relationTypes.child"),
    related: t("detail.relationTypes.related"),
    successor: t("detail.relationTypes.successor"),
    predecessor: t("detail.relationTypes.predecessor"),
  };

  if (detail.isError) {
    const missing = detail.error instanceof ApiError && detail.error.status === 404;
    return (
      <ErrorPanel
        message={missing ? t("detail.notFound") : errorMessage(tc, detail.error)}
        backHref={listHref}
        backLabel={t("detail.back")}
      />
    );
  }

  const bareRor = (value: string) => value.replace(/^https?:\/\/ror\.org\//, "");

  const from = year_from ?? (d?.per_year.length ? d.per_year[0].year : (site.windowStart ?? 2010));
  const to =
    year_to ??
    (d?.per_year.length ? d.per_year[d.per_year.length - 1].year : new Date().getFullYear());

  const trendStats: StatsYear[] = (d?.per_year ?? []).map((y) => ({
    year: y.year,
    works_count: y.works,
    works_count_source: "pure_canon",
    oa_gold: y.oa_gold ?? 0,
    oa_diamond: y.oa_diamond ?? 0,
    oa_hybrid: y.oa_hybrid ?? 0,
    oa_green: y.oa_green ?? 0,
    oa_bronze: y.oa_bronze ?? 0,
    oa_closed: y.oa_closed ?? 0,
  }));

  const typeRows = (d?.works_by_type ?? []).map((row) => ({
    label: workTypeLabel(tc, row.value) ?? row.value,
    count: row.count,
  }));

  const share =
    d?.share == null
      ? null
      : d.share * 100 < 0.1 && d.share > 0
        ? "<0.1"
        : (d.share * 100).toFixed(1).replace(/\.0$/, "");
  const oaPct = d?.oa_share != null ? `${Math.round(d.oa_share * 100)}%` : "—";

  const facts: { term: string; value: React.ReactNode }[] = [];
  if (d) {
    if (d.parent_name) {
      facts.push({ term: t("detail.facts.parent"), value: d.parent_name });
    }
    facts.push({
      term: t("detail.facts.ror"),
      value: (
        <a href={`https://ror.org/${bareRor(d.ror)}`} {...external} className={dottedLink}>
          {bareRor(d.ror)}
        </a>
      ),
    });
    if (d.openalex_id) {
      const id = d.openalex_id.replace(/^https?:\/\/openalex\.org\//, "");
      facts.push({
        term: t("detail.facts.openalex"),
        value: (
          <a href={`https://openalex.org/${id}`} {...external} className={dottedLink}>
            {id}
          </a>
        ),
      });
    }
    const aliases = d.labels.filter((label) => label !== d.name);
    if (aliases.length) {
      facts.push({ term: t("detail.facts.aliases"), value: aliases.join("; ") });
    }
    const links = d.links.filter((link) => /^https?:\/\//.test(link.value));
    if (links.length) {
      facts.push({
        term: t("detail.facts.links"),
        value: (
          <span className="flex flex-wrap gap-x-3">
            {links.map((link) => (
              <a
                key={`${link.type}:${link.value}`}
                href={link.value}
                {...external}
                className={dottedLink}
              >
                {linkTypes[link.type] ?? link.type}
              </a>
            ))}
          </span>
        ),
      });
    }
    if (d.relationships.length) {
      facts.push({
        term: t("detail.facts.relationships"),
        value: (
          <ul className="space-y-0.5">
            {d.relationships.map((rel) => (
              <li
                key={`${rel.type}:${rel.ror}`}
                className="flex flex-wrap items-baseline gap-x-1.5"
              >
                <span className="text-[var(--muted-foreground)]">
                  {relationTypes[rel.type.toLowerCase()] ?? rel.type}:
                </span>
                {rel.is_partner ? (
                  <Link
                    href={`/${inst}/collaborations/${encodeURIComponent(bareRor(rel.ror))}${listQuery ? `?${listQuery}` : ""}`}
                    className={`font-medium ${linkClass}`}
                  >
                    {rel.label}
                  </Link>
                ) : (
                  <a
                    href={`https://ror.org/${bareRor(rel.ror)}`}
                    {...external}
                    className={dottedLink}
                  >
                    {rel.label}
                  </a>
                )}
              </li>
            ))}
          </ul>
        ),
      });
    }
  }

  const shown = works.data?.items.length ?? 0;
  const totalWorks = works.data?.total ?? 0;
  const workPages = Math.max(1, Math.ceil(totalWorks / PAGE_SIZE));
  const hasUtCollab =
    (d?.ut_faculties.length ?? 0) > 0 ||
    (d?.ut_groups.length ?? 0) > 0 ||
    (d?.ut_authors.length ?? 0) > 0;
  const journalList = d?.top_journals ?? [];
  const journalPages = Math.max(1, Math.ceil(journalList.length / PAGE_SIZE));
  const pagedJournals = journalList.slice((journalPage - 1) * PAGE_SIZE, journalPage * PAGE_SIZE);

  const sections: { id: string; label: string }[] = d
    ? [
        { id: "overview", label: t("detail.navOverview") },
        ...(hasUtCollab ? [{ id: "ut-collaborators", label: t("detail.navUtCollab") }] : []),
        ...(journalList.length > 0 || d.top_topics.length > 0
          ? [{ id: "journals-topics", label: t("detail.navJournals") }]
          : []),
        { id: "credits", label: t("detail.navCredits") },
        ...((d.merged_children?.length ?? 0) > 0
          ? [{ id: "merged-subunits", label: t("detail.navMerged") }]
          : []),
        { id: "shared-works", label: t("detail.navWorks") },
      ]
    : [];

  return (
    <>
      {sections.length > 0 && (
        <SectionNav sections={sections} backHref={listHref} backLabel={t("detail.back")} />
      )}
      <div className="mx-auto max-w-screen-2xl px-4 py-6">
        <ActiveFiltersBar
          params={filters}
          onChange={updateFilters}
          variant="banner"
          onResetAll={() => updateFilters(EMPTY_COLLAB_FILTERS)}
        />

        {detail.isPending && (
          <div className="mt-4">
            <ListSkeletonRows rows={6} />
          </div>
        )}

        {d && (
          <div className="mt-3 space-y-4">
            <header>
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-2xl font-bold tracking-tight text-balance sm:text-3xl">
                  {d.name}
                </h1>
                {d.org_type && (
                  <Badge variant="muted" className="inline-flex items-center gap-1.5 font-normal">
                    <span
                      aria-hidden
                      className="inline-block size-2 rounded-full"
                      style={{ backgroundColor: orgTypeCssVar(d.org_type) }}
                    />
                    {labels.orgType(d.org_type)}
                  </Badge>
                )}
                {(d.city || d.country_code) && (
                  <span className="text-xs text-[var(--muted-foreground)]">
                    {[d.city, d.country_code ? labels.region(d.country_code) : null]
                      .filter(Boolean)
                      .join(", ")}
                  </span>
                )}
                {d.shares_deals && (
                  <Badge variant="outline" className="font-normal">
                    {t("detail.facts.sharesDeals")}
                  </Badge>
                )}
                {d.status && d.status !== "active" && (
                  <Badge variant="outline" className="font-normal">
                    {t("detail.facts.inactive")}
                  </Badge>
                )}
              </div>

              <dl className="mt-3 grid gap-x-6 gap-y-1.5 text-xs sm:grid-cols-2 xl:grid-cols-3">
                {facts.map((fact) => (
                  <div key={fact.term} className="flex gap-2.5">
                    <dt className="w-28 shrink-0 text-[var(--muted-foreground)]">{fact.term}</dt>
                    <dd className="min-w-0">{fact.value}</dd>
                  </div>
                ))}
              </dl>
            </header>

            <DetailSummaryPanel
              id="overview"
              stats={[
                {
                  label: t("detail.kpi.works"),
                  value: d.works.toLocaleString("en"),
                  icon: (
                    <DataIcon className={`size-3.5 ${ACCESS_TEXT.brand}`}>
                      <WorksGlyph />
                    </DataIcon>
                  ),
                  sub:
                    share !== null
                      ? t("detail.kpi.share", {
                          share,
                          inst: site.short,
                          from: String(from),
                          to: String(to),
                        })
                      : undefined,
                },
                {
                  label: t("detail.kpi.oa"),
                  value: oaPct,
                  icon: (
                    <DataIcon className={`size-3.5 ${ACCESS_TEXT.gold}`}>
                      <LockIcon state="open" />
                    </DataIcon>
                  ),
                  sub: t("detail.kpi.oaSub", {
                    oa: (d.oa_works ?? 0).toLocaleString("en"),
                    closed: (d.closed_works ?? 0).toLocaleString("en"),
                  }),
                },
                {
                  label: t("detail.kpi.lead"),
                  value: (
                    <>
                      {(d.home_corresponding_works ?? 0).toLocaleString("en")}{" "}
                      <span className="text-sm font-normal text-[var(--muted-foreground)]">
                        / {d.corresponding_works.toLocaleString("en")}
                      </span>
                    </>
                  ),
                  sub: t("detail.kpi.leadSub", {
                    home: (d.home_corresponding_works ?? 0).toLocaleString("en"),
                    inst: site.short,
                    partner: d.corresponding_works.toLocaleString("en"),
                  }),
                },
                {
                  label: t("detail.kpi.authorships"),
                  value: d.authorships.toLocaleString("en"),
                  sub: t("detail.kpi.authorshipsSub"),
                },
              ]}
              trendStats={trendStats}
              trendTitle={t("detail.trend.title")}
              rightSlot={
                typeRows.length > 0 ? (
                  <BarList title={t("detail.trend.byType")} rows={typeRows} />
                ) : undefined
              }
            />

            {(d.deal_closed_works ?? 0) > 0 && (
              <div className="rounded-[var(--radius)] border border-amber-500/40 bg-amber-500/10 px-4 py-2.5 text-xs sm:text-sm text-[var(--foreground)]">
                {t("detail.dealClosedAlert", {
                  count: d.deal_closed_works,
                  inst: site.short,
                })}
              </div>
            )}

            {/* Block 3: UT Collaborators */}
            {hasUtCollab && (
              <CollapsibleCard
                id="ut-collaborators"
                title={t("detail.utCollab.title", { inst: site.short, partner: d.name })}
                compact
                contentClassName="text-sm"
              >
                <div className="grid gap-6 lg:grid-cols-3">
                  {d.ut_faculties.length > 0 && (
                    <div>
                      <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                        {t("detail.utCollab.faculties")}
                      </h3>
                      <ol className="mt-1 divide-y divide-[var(--border)]">
                        {(collabExpanded.fac
                          ? d.ut_faculties
                          : d.ut_faculties.slice(0, SUBLIST_CAP)
                        ).map((u) => (
                          <li
                            key={u.name}
                            className="flex items-baseline justify-between gap-3 py-1.5"
                          >
                            <Link
                              href={`/${inst}/orgunit/faculty/${encodeNamePath(u.name)}`}
                              className={`min-w-0 truncate font-medium ${linkClass}`}
                            >
                              {u.name}
                            </Link>
                            <span className="shrink-0 tabular-nums">
                              {u.works.toLocaleString("en")}
                            </span>
                          </li>
                        ))}
                      </ol>
                      {d.ut_faculties.length > SUBLIST_CAP && (
                        <div className="mt-1.5">
                          <MoreToggle
                            open={!!collabExpanded.fac}
                            onToggle={() => setCollabExpanded((m) => ({ ...m, fac: !m.fac }))}
                            moreLabel={t("detail.showAllCount", { count: d.ut_faculties.length })}
                          />
                        </div>
                      )}
                    </div>
                  )}

                  {d.ut_groups.length > 0 && (
                    <div>
                      <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                        {t("detail.utCollab.groups")}
                      </h3>
                      <ol className="mt-1 divide-y divide-[var(--border)]">
                        {(collabExpanded.grp ? d.ut_groups : d.ut_groups.slice(0, SUBLIST_CAP)).map(
                          (u) => (
                            <li
                              key={u.name}
                              className="flex items-baseline justify-between gap-3 py-1.5"
                            >
                              <Link
                                href={`/${inst}/orgunit/group/${encodeNamePath(u.name)}`}
                                className={`min-w-0 truncate font-medium ${linkClass}`}
                              >
                                {u.name}
                              </Link>
                              <span className="shrink-0 tabular-nums">
                                {u.works.toLocaleString("en")}
                              </span>
                            </li>
                          ),
                        )}
                      </ol>
                      {d.ut_groups.length > SUBLIST_CAP && (
                        <div className="mt-1.5">
                          <MoreToggle
                            open={!!collabExpanded.grp}
                            onToggle={() => setCollabExpanded((m) => ({ ...m, grp: !m.grp }))}
                            moreLabel={t("detail.showAllCount", { count: d.ut_groups.length })}
                          />
                        </div>
                      )}
                    </div>
                  )}

                  {d.ut_authors.length > 0 && (
                    <div>
                      <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                        {t("detail.utCollab.authors")}
                      </h3>
                      <ol className="mt-1 divide-y divide-[var(--border)]">
                        {(collabExpanded.auth
                          ? d.ut_authors
                          : d.ut_authors.slice(0, SUBLIST_CAP)
                        ).map((a) => (
                          <li
                            key={a.pure_uuid}
                            className="flex items-baseline justify-between gap-3 py-1.5"
                          >
                            <span className="min-w-0">
                              <Link
                                href={`/${inst}/author/${encodeURIComponent(a.pure_uuid)}`}
                                className={`block truncate font-medium ${linkClass}`}
                              >
                                {a.name}
                              </Link>
                              {(a.research_group || a.faculty) && (
                                <span className="block truncate text-xs text-[var(--muted-foreground)]">
                                  {a.research_group ?? a.faculty}
                                </span>
                              )}
                            </span>
                            <span className="shrink-0 tabular-nums">
                              {a.works.toLocaleString("en")}
                            </span>
                          </li>
                        ))}
                      </ol>
                      {d.ut_authors.length > SUBLIST_CAP && (
                        <div className="mt-1.5">
                          <MoreToggle
                            open={!!collabExpanded.auth}
                            onToggle={() => setCollabExpanded((m) => ({ ...m, auth: !m.auth }))}
                            moreLabel={t("detail.showAllCount", { count: d.ut_authors.length })}
                          />
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </CollapsibleCard>
            )}

            {/* Block 4: Shared journals, Topics, Funders & Projects */}
            {(journalList.length > 0 || d.top_topics.length > 0) && (
              <CollapsibleCard
                id="journals-topics"
                title={t("detail.journals.title")}
                count={journalList.length > 0 ? journalList.length : undefined}
                compact
                contentClassName="space-y-4 text-sm [&_td]:py-1.5 [&_th]:h-8"
              >
                {d.top_topics.length > 0 && (
                  <div>
                    <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                      {t("detail.journals.topicsHeading")}
                    </h3>
                    <TopicChipList
                      items={d.top_topics.map((topic) => ({
                        name: topic.value,
                        count: topic.count,
                        href: `/${inst}/collaborations?topic=${encodeURIComponent(topic.value)}`,
                      }))}
                      limit={8}
                    />
                  </div>
                )}

                {journalList.length > 0 && (
                  <>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>{t("detail.journals.colJournal")}</TableHead>
                          <TableHead className="text-right">
                            {t("detail.journals.colWorks")}
                          </TableHead>
                          <TableHead className="text-right">
                            {t("detail.journals.colClosed")}
                          </TableHead>
                          <TableHead>{t("detail.journals.colAccess")}</TableHead>
                          <TableHead>{t("detail.journals.colQuartile")}</TableHead>
                          <TableHead>{t("detail.journals.colDeal")}</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {pagedJournals.map((j) => (
                          <TableRow key={j.issn_l}>
                            <TableCell className="font-medium">
                              <Link href={`/${inst}/journals/${j.issn_l}`} className={linkClass}>
                                {j.title}
                              </Link>
                            </TableCell>
                            <TableCell className="text-right tabular-nums">
                              {j.works.toLocaleString("en")}
                            </TableCell>
                            <TableCell className="text-right tabular-nums text-[var(--muted-foreground)]">
                              {j.closed_works > 0 ? j.closed_works.toLocaleString("en") : "—"}
                            </TableCell>
                            <TableCell>
                              <OaTypeBadge oaType={j.oa_type ?? null} />
                            </TableCell>
                            <TableCell>
                              <QuartileBadge quartile={j.quartile ?? null} />
                            </TableCell>
                            <TableCell>
                              <DealBadge covered={j.deal_covered} />
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                    {journalPages > 1 && (
                      <CardPager
                        page={journalPage}
                        pages={journalPages}
                        total={journalList.length}
                        onPage={setJournalPage}
                        label={t("detail.pagerJournals")}
                      />
                    )}
                  </>
                )}
              </CollapsibleCard>
            )}

            <CollapsibleCard id="credits" title={t("detail.credits.title")} compact>
              <div className="grid gap-6 lg:grid-cols-2">
                <CreditsList
                  title={t("detail.funders")}
                  empty={t("detail.noFunders")}
                  showAllLabel={(count) => t("detail.showAllCount", { count })}
                  rows={d.funders.map((f) => ({
                    key: f.key,
                    label: f.name,
                    note: labels.sources(f.sources),
                    works: f.works,
                    href: f.jisc_funder_id ? `/${inst}/funders/${f.jisc_funder_id}` : undefined,
                  }))}
                />
                <CreditsList
                  title={t("detail.projects")}
                  empty={t("detail.noProjects")}
                  showAllLabel={(count) => t("detail.showAllCount", { count })}
                  rows={d.projects.map((p) => ({
                    key: p.key,
                    label: p.acronym
                      ? `${p.acronym}${p.code ? ` (${p.code})` : ""}`
                      : p.code || p.key,
                    note: [
                      p.funder,
                      p.sources?.length ? labels.sources(p.sources) : labels.source(p.source),
                    ]
                      .filter(Boolean)
                      .join(" · "),
                    works: p.works,
                  }))}
                />
              </div>
            </CollapsibleCard>

            {/* Block 5: Sub-units & Shared Works (default collapsed) */}
            {(d.merged_children?.length ?? 0) > 0 && (
              <CollapsibleCard
                id="merged-subunits"
                title={t("detail.merged.title")}
                count={d.merged_children.length}
                defaultOpen={false}
                compact
                description={
                  <p className="text-xs text-[var(--muted-foreground)]">
                    {t("detail.merged.description")}
                  </p>
                }
              >
                <ul className="divide-y divide-[var(--border)] text-sm">
                  {d.merged_children.map((child) => (
                    <li
                      key={child.ror}
                      className="flex flex-wrap items-baseline justify-between gap-2 py-1.5"
                    >
                      <span className="flex flex-wrap items-center gap-2">
                        <Link
                          href={`/${inst}/collaborations/${encodeURIComponent(child.ror)}?rollup=0`}
                          className={`font-medium ${linkClass}`}
                        >
                          {child.name}
                        </Link>
                        {child.status && child.status !== "active" && (
                          <Badge variant="outline" className="text-[10px] font-normal">
                            {child.status}
                          </Badge>
                        )}
                      </span>
                      <span className="tabular-nums text-[var(--muted-foreground)]">
                        {t("detail.merged.works", { count: child.works })}
                      </span>
                    </li>
                  ))}
                </ul>
              </CollapsibleCard>
            )}

            <CollapsibleCard
              id="shared-works"
              title={t("detail.works.title")}
              count={works.data ? totalWorks : d.works}
              defaultOpen={false}
              compact
              onOpenChange={setWorksOpened}
              description={
                <div className="mt-1 flex flex-wrap items-center justify-between gap-3">
                  <span className="text-xs text-[var(--muted-foreground)]">
                    {worksOpened &&
                      totalWorks > 0 &&
                      t("range", {
                        from: (offset + 1).toLocaleString("en"),
                        to: (offset + shown).toLocaleString("en"),
                        total: totalWorks.toLocaleString("en"),
                      })}
                  </span>
                  <GapCsvButton href={collaborationCsvHref(inst, params, ror)} />
                </div>
              }
              contentClassName="space-y-3 text-sm [&_td]:py-1.5 [&_th]:h-8"
            >
              {works.isPending && <ListSkeletonRows rows={6} />}
              {works.isError && (
                <p role="alert" className="text-[var(--destructive)]">
                  {errorMessage(tc, works.error)}
                </p>
              )}
              {works.data && (
                <>
                  <Table className={works.isPlaceholderData ? "opacity-60" : undefined}>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t("detail.works.work")}</TableHead>
                        <TableHead>{t("detail.works.year")}</TableHead>
                        <TableHead>{t("detail.works.journal")}</TableHead>
                        <TableHead>{t("detail.works.oa")}</TableHead>
                        <TableHead>{t("detail.works.authors", { inst: site.short })}</TableHead>
                        <TableHead>{t("detail.works.lead")}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {works.data.items.length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={6} className="text-[var(--muted-foreground)]">
                            {t("table.empty")}
                          </TableCell>
                        </TableRow>
                      ) : (
                        works.data.items.map((w) => {
                          const authorLinks = w.author_links ?? [];
                          const visibleLinks = authorLinks.slice(0, 3);
                          const moreCount =
                            (authorLinks.length ? authorLinks.length : w.authors.length) - 3;
                          const leadLabel =
                            w.home_corresponding && w.corresponding
                              ? t("detail.works.leadBoth")
                              : w.home_corresponding
                                ? t("detail.works.leadHome", { inst: site.short })
                                : w.corresponding
                                  ? t("detail.works.leadPartner")
                                  : "—";
                          return (
                            <TableRow key={w.pure_uuid}>
                              <TableCell className="max-w-md">
                                {w.doi ? (
                                  <a
                                    href={`https://doi.org/${w.doi}`}
                                    {...external}
                                    className={`font-medium ${dottedLink}`}
                                  >
                                    {w.title}
                                  </a>
                                ) : (
                                  <span className="font-medium">{w.title}</span>
                                )}
                                {w.work_type && (
                                  <span className="ml-2 text-xs text-[var(--muted-foreground)]">
                                    {workTypeLabel(tc, w.work_type) ?? w.work_type}
                                  </span>
                                )}
                              </TableCell>
                              <TableCell className="whitespace-nowrap tabular-nums">
                                {w.year}
                              </TableCell>
                              <TableCell className="max-w-xs">
                                {w.journal_issn_l ? (
                                  <span className="inline-flex flex-wrap items-center gap-1.5">
                                    <Link
                                      href={`/${inst}/journals/${w.journal_issn_l}`}
                                      className={linkClass}
                                    >
                                      {w.journal_title ?? w.journal_issn_l}
                                    </Link>
                                    {w.deal_covered && <DealBadge covered />}
                                  </span>
                                ) : (
                                  <span className="text-[var(--muted-foreground)]">—</span>
                                )}
                              </TableCell>
                              <TableCell>
                                {w.oa_status ? (
                                  <OaStatusChip status={w.oa_status} />
                                ) : (
                                  <span className="text-[var(--muted-foreground)]">—</span>
                                )}
                              </TableCell>
                              <TableCell className="max-w-xs text-[var(--muted-foreground)]">
                                {visibleLinks.length > 0 ? (
                                  <>
                                    {visibleLinks.map((a, idx) => (
                                      <React.Fragment key={`${a.name}-${idx}`}>
                                        {idx > 0 && ", "}
                                        {a.pure_uuid ? (
                                          <Link
                                            href={`/${inst}/author/${encodeURIComponent(a.pure_uuid)}`}
                                            className={linkClass}
                                          >
                                            {a.name}
                                          </Link>
                                        ) : (
                                          a.name
                                        )}
                                      </React.Fragment>
                                    ))}
                                    {moreCount > 0 &&
                                      ` ${t("detail.works.moreAuthors", { count: moreCount })}`}
                                  </>
                                ) : (
                                  <>
                                    {w.authors.slice(0, 3).join(", ")}
                                    {moreCount > 0 &&
                                      ` ${t("detail.works.moreAuthors", { count: moreCount })}`}
                                  </>
                                )}
                              </TableCell>
                              <TableCell className="whitespace-nowrap text-[var(--muted-foreground)]">
                                {leadLabel}
                              </TableCell>
                            </TableRow>
                          );
                        })
                      )}
                    </TableBody>
                  </Table>

                  {workPages > 1 && (
                    <CardPager
                      page={worksPage}
                      pages={workPages}
                      total={totalWorks}
                      onPage={setWorksPage}
                      isFetching={works.isFetching}
                      label={t("detail.pagerWorks")}
                    />
                  )}
                </>
              )}
            </CollapsibleCard>

            <CollaborationSources />
          </div>
        )}
      </div>
    </>
  );
}

export default function PartnerPage() {
  return (
    <React.Suspense fallback={null}>
      <PartnerPageInner />
    </React.Suspense>
  );
}
