"use client";

import { ArrowRight, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import { DealBadge, OaTypeBadge, QuartileBadge } from "@/components/badges";
import { BackLink } from "@/components/back-link";
import { CardPager } from "@/components/card-pager";
import { orgTypeCssVar } from "@/components/collaborations/labels";
import { CollapsibleCard } from "@/components/collapsible-card";
import { CrisGapsSection } from "@/components/cris-gaps-section";
import { ACCESS_TEXT, ApcGlyph, DataIcon, DealGlyph, WorksGlyph } from "@/components/data-icons";
import { DetailSummaryPanel } from "@/components/detail-summary";
import { SectionNav } from "@/components/journal/section-nav";
import { OrcidLink } from "@/components/orcid-link";
import { DetailSkeleton, ErrorPanel } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useOrgUnit } from "@/hooks/use-api";
import { useInstitution } from "@/hooks/use-institution";
import { useYearRange } from "@/hooks/use-year-filter";
import {
  encodeNamePath,
  errorMessage,
  type OrgUnitAuthorSort,
  type OrgUnitDetailResponse,
  type OrgUnitLevel,
} from "@/lib/api";
import { countryName, formatEur } from "@/lib/format";

const PAGE_SIZE = 10;

export default function OrgUnitPage() {
  const t = useTranslations("orgunits");
  const tc = useTranslations("common");
  const params = useParams<{ slug: string[] }>();
  const inst = useInstitution();
  const segments = params?.slug ?? [];
  const [levelSeg, ...nameSegs] = segments;
  const level: OrgUnitLevel | undefined =
    levelSeg === "faculty" || levelSeg === "group" || levelSeg === "institute"
      ? levelSeg
      : undefined;
  const name = nameSegs.map(decodeURIComponent).join("/");

  const backHref = level === "faculty" ? `/${inst}/orgunit` : `/${inst}/orgunit?level=${level}`;
  const { year_from, year_to } = useYearRange();
  const [authorSort, setAuthorSort] = React.useState<OrgUnitAuthorSort>("share");
  const { data, isPending, isFetching, isError, error } = useOrgUnit(
    level,
    level && name ? name : undefined,
    { year_from, year_to },
    authorSort,
  );

  if (!level)
    return (
      <div className="mx-auto max-w-screen-2xl px-4 py-10">
        <p className="text-[var(--destructive)]">{t("detail.unknownType")}</p>
        <div className="mt-2">
          <BackLink href={`/${inst}/orgunit`} label={t("detail.back.faculty")} />
        </div>
      </div>
    );
  if (isPending && !data)
    return (
      <DetailSkeleton
        title={name}
        sections={[
          t("detail.trendTitle"),
          t("detail.groups.title"),
          t("detail.authors.title"),
          t("detail.journals.title"),
        ]}
      />
    );
  if (isError || !data)
    return (
      <ErrorPanel
        message={errorMessage(tc, error)}
        backHref={backHref}
        backLabel={t("detail.backGeneric")}
        backClassName=""
      />
    );

  return (
    <OrgUnitDetail
      key={`${level}:${name}`}
      inst={inst}
      backHref={backHref}
      data={data}
      isFetching={isFetching}
      authorSort={authorSort}
      onAuthorSortChange={setAuthorSort}
    />
  );
}

function OrgUnitDetail({
  inst,
  backHref,
  data,
  isFetching,
  authorSort,
  onAuthorSortChange,
}: {
  inst: string;
  backHref: string;
  data: OrgUnitDetailResponse;
  isFetching: boolean;
  authorSort: OrgUnitAuthorSort;
  onAuthorSortChange: (sort: OrgUnitAuthorSort) => void;
}) {
  const t = useTranslations("orgunits");
  const { year_from, year_to } = useYearRange();
  const { unit, groups, journals, authors, works_by_year, deal_usage, top_partners } = data;
  const partnersQuery = `level=${encodeURIComponent(unit.level)}&faculty=${encodeURIComponent(unit.name)}`;
  const trendYears = works_by_year.filter(
    (s) =>
      (year_from === undefined || s.year >= year_from) &&
      (year_to === undefined || s.year <= year_to),
  );
  const [groupPage, setGroupPage] = React.useState(1);
  const [journalPage, setJournalPage] = React.useState(1);
  const [authorPage, setAuthorPage] = React.useState(1);
  const groupRows = (groups ?? []).slice((groupPage - 1) * PAGE_SIZE, groupPage * PAGE_SIZE);
  const journalRows = journals.slice((journalPage - 1) * PAGE_SIZE, journalPage * PAGE_SIZE);
  const authorRows = authors.slice((authorPage - 1) * PAGE_SIZE, authorPage * PAGE_SIZE);
  const groupPages = Math.max(1, Math.ceil((groups ?? []).length / PAGE_SIZE));
  const journalPages = Math.max(1, Math.ceil(journals.length / PAGE_SIZE));
  const authorPages = Math.max(1, Math.ceil(authors.length / PAGE_SIZE));

  const dealShare = unit.n_works > 0 ? Math.round((unit.deal_works / unit.n_works) * 100) : 0;
  const backLabel =
    unit.level === "group"
      ? t("detail.back.group")
      : unit.level === "faculty"
        ? t("detail.back.faculty")
        : t("detail.back.institute");

  const sections: { id: string; label: string }[] = [
    { id: "overview", label: t("detail.navOverview") },
    ...(groups != null && groups.length > 0
      ? [{ id: "groups", label: t("detail.navGroups") }]
      : []),
    ...(deal_usage.length > 0 ? [{ id: "deal-usage", label: t("detail.navDeals") }] : []),
    ...(journals.length > 0 ? [{ id: "journals", label: t("detail.navJournals") }] : []),
    ...(authors.length > 0 ? [{ id: "authors", label: t("detail.navAuthors") }] : []),
    ...((top_partners?.length ?? 0) > 0
      ? [{ id: "collaboration-partners", label: t("detail.navPartners") }]
      : []),
    ...(data.openalex_only.available ? [{ id: "cris-gaps", label: t("detail.navCrisGaps") }] : []),
  ];

  const kpis = [
    { label: t("detail.kpiAuthors"), value: unit.n_authors.toLocaleString("en") },
    {
      label: t("detail.kpiWorks"),
      value: unit.n_works.toLocaleString("en"),
      icon: (
        <DataIcon className={`size-3.5 ${ACCESS_TEXT.brand}`}>
          <WorksGlyph />
        </DataIcon>
      ),
    },
    {
      label: t("detail.kpiDealWorks"),
      value: `${unit.deal_works.toLocaleString("en")}${unit.n_works > 0 ? ` (${dealShare}%)` : ""}`,
      icon: (
        <DataIcon className={`size-3.5 ${ACCESS_TEXT.deal}`}>
          <DealGlyph />
        </DataIcon>
      ),
      hint: t("tooltips.dealWorks"),
    },
    ...(unit.apc_n > 0
      ? [
          {
            label: t("detail.kpiApcSpend"),
            value: `€${formatEur(unit.apc_euro_total)}`,
            icon: (
              <DataIcon className={`size-3.5 ${ACCESS_TEXT.brand}`}>
                <ApcGlyph />
              </DataIcon>
            ),
            hint: t("tooltips.apc", { count: unit.apc_n }),
            sub: `${unit.apc_n} articles`,
          },
        ]
      : []),
    ...(unit.n_groups != null && unit.n_groups > 0
      ? [{ label: t("detail.navGroups"), value: unit.n_groups.toLocaleString("en") }]
      : []),
  ];

  return (
    <>
      <SectionNav
        sections={sections}
        backFallback={backHref}
        backStorageKey="jb-last-orgunits"
        backLabel={backLabel}
      />
      <div className="mx-auto max-w-screen-2xl px-4 py-6">
        <header className="mb-4">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight text-balance sm:text-3xl">
              {unit.name}
            </h1>
            <Badge variant="muted" className="font-normal">
              {unit.level === "group"
                ? t("detail.badge.group")
                : unit.level === "institute"
                  ? t("detail.badge.institute")
                  : t("detail.badge.faculty")}
            </Badge>
            {unit.faculty && (
              <Link
                href={`/${inst}/orgunit/faculty/${encodeNamePath(unit.faculty)}`}
                className="inline-flex items-center rounded-md border border-[var(--border)] bg-[var(--muted)] px-2.5 py-0.5 text-xs text-[var(--foreground)] underline-offset-2 hover:border-[var(--primary)] hover:text-[var(--primary-text)] hover:underline"
              >
                {unit.faculty}
              </Link>
            )}
          </div>
        </header>

        <div className="space-y-4">
          <DetailSummaryPanel
            id="overview"
            stats={kpis}
            trendStats={trendYears}
            trendTitle={t("detail.trendTitle")}
          />

          {/* Block 3: Sub-units & Deal usage */}
          {groups != null && groups.length > 0 && (
            <CollapsibleCard
              id="groups"
              title={t("detail.groups.title")}
              count={groups.length}
              compact
              contentClassName="space-y-3 text-sm [&_td]:py-1.5 [&_th]:h-8"
            >
              <Table>
                <caption className="sr-only">{t("detail.groups.caption")}</caption>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("detail.groups.column")}</TableHead>
                    <TableHead className="text-right">{t("columns.authors")}</TableHead>
                    <TableHead className="text-right">{t("columns.works")}</TableHead>
                    <TableHead className="text-right">{t("columns.dealWorks")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {groupRows.map((g) => {
                    const share = g.n_works > 0 ? Math.round((g.deal_works / g.n_works) * 100) : 0;
                    return (
                      <TableRow key={g.name}>
                        <TableCell className="font-medium">
                          <Link
                            href={`/${inst}/orgunit/group/${encodeNamePath(g.name)}`}
                            className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                          >
                            {g.name}
                          </Link>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {g.n_authors.toLocaleString("en")}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {g.n_works.toLocaleString("en")}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {g.deal_works.toLocaleString("en")}
                          {g.n_works > 0 && (
                            <span className="text-[var(--muted-foreground)]"> ({share}%)</span>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
              {groupPages > 1 && (
                <CardPager
                  page={groupPage}
                  pages={groupPages}
                  total={(groups ?? []).length}
                  onPage={setGroupPage}
                  label={t("detail.groups.pager")}
                />
              )}
            </CollapsibleCard>
          )}

          {deal_usage.length > 0 && (
            <CollapsibleCard
              id="deal-usage"
              title={t("detail.dealUsage.title")}
              count={deal_usage.length}
              compact
              description={
                <p className="text-xs text-[var(--muted-foreground)]">
                  {t("detail.dealUsage.description")}
                </p>
              }
              contentClassName="text-sm [&_td]:py-1.5 [&_th]:h-8"
            >
              <Table>
                <caption className="sr-only">{t("detail.dealUsage.caption")}</caption>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("columns.agreement")}</TableHead>
                    <TableHead className="text-right">{t("columns.works")}</TableHead>
                    <TableHead className="text-right">{t("columns.apc")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {deal_usage.map((d) => (
                    <TableRow key={d.label}>
                      <TableCell className="font-medium">
                        <Link
                          href={`/${inst}/deals`}
                          className="block max-w-72 truncate underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                          title={d.label}
                        >
                          {d.label}
                        </Link>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {d.n_works.toLocaleString("en")}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {d.euro ? `€${formatEur(d.euro)}` : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CollapsibleCard>
          )}

          {/* Block 4: Journals, Authors & Collaborators */}
          {journals.length > 0 && (
            <CollapsibleCard
              id="journals"
              title={t("detail.journals.title")}
              count={journals.length}
              compact
              contentClassName="space-y-3 text-sm [&_td]:py-1.5 [&_th]:h-8"
            >
              <Table>
                <caption className="sr-only">{t("detail.journals.caption")}</caption>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("columns.journal")}</TableHead>
                    <TableHead className="text-right">{t("columns.works")}</TableHead>
                    <TableHead>{t("columns.access")}</TableHead>
                    <TableHead>{t("columns.quartile")}</TableHead>
                    <TableHead>{t("columns.deal")}</TableHead>
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
                      <TableCell>
                        <QuartileBadge quartile={j.quartile} />
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
                  total={journals.length}
                  onPage={setJournalPage}
                  label={t("detail.journals.pager")}
                />
              )}
            </CollapsibleCard>
          )}

          {authors.length > 0 && (
            <CollapsibleCard
              id="authors"
              title={t("detail.authors.title")}
              count={authors.length}
              compact
              description={
                <div
                  role="group"
                  aria-label={t("detail.authors.rankBy")}
                  className="mt-1 flex flex-wrap items-center gap-2"
                >
                  <div className="flex overflow-hidden rounded-[var(--radius)] border border-[var(--input)]">
                    <Button
                      variant={authorSort === "share" ? "secondary" : "ghost"}
                      size="sm"
                      className="h-7 rounded-none px-2.5 text-xs"
                      aria-pressed={authorSort === "share"}
                      title={t("detail.authors.shareSortTitle")}
                      onClick={() => onAuthorSortChange("share")}
                    >
                      {t("detail.authors.shareSort")}
                    </Button>
                    <Button
                      variant={authorSort === "works" ? "secondary" : "ghost"}
                      size="sm"
                      className="h-7 rounded-none px-2.5 text-xs"
                      aria-pressed={authorSort === "works"}
                      onClick={() => onAuthorSortChange("works")}
                    >
                      {t("detail.authors.worksSort")}
                    </Button>
                  </div>
                  {isFetching && (
                    <Loader2
                      aria-hidden
                      className="size-3.5 animate-spin text-[var(--muted-foreground)]"
                    />
                  )}
                </div>
              }
              contentClassName="space-y-3 text-sm [&_td]:py-1.5 [&_th]:h-8"
            >
              <Table className={isFetching ? "opacity-60 transition-opacity" : undefined}>
                <caption className="sr-only">{t("detail.authors.caption")}</caption>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("columns.author")}</TableHead>
                    <TableHead className="text-right" title={t("detail.authors.shareHeaderTitle")}>
                      {t("detail.authors.shareHeader")}
                    </TableHead>
                    <TableHead className="text-right">{t("columns.works")}</TableHead>
                    <TableHead>{t("columns.topic")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {authorRows.map((a) => (
                    <TableRow key={a.pure_uuid}>
                      <TableCell className="font-medium">
                        <Link
                          href={`/${inst}/author/${a.pure_uuid}`}
                          className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                        >
                          {a.name}
                        </Link>
                        {a.orcid && (
                          <span className="ml-2">
                            <OrcidLink orcid={a.orcid} />
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {a.oa_diamond_gold_share != null ? (
                          `${Math.round(a.oa_diamond_gold_share * 100)}%`
                        ) : (
                          <span className="text-[var(--muted-foreground)]">
                            {t("detail.authors.shareUnavailable")}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {a.n_works.toLocaleString("en")}
                      </TableCell>
                      <TableCell>
                        {a.primary_topic ? (
                          <span className="block max-w-40 truncate" title={a.primary_topic}>
                            {a.primary_topic}
                          </span>
                        ) : (
                          <span className="text-[var(--muted-foreground)]">—</span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {authorPages > 1 && (
                <CardPager
                  page={authorPage}
                  pages={authorPages}
                  total={authors.length}
                  onPage={setAuthorPage}
                  label={t("detail.authors.pager")}
                />
              )}
            </CollapsibleCard>
          )}

          {(top_partners?.length ?? 0) > 0 && (
            <CollapsibleCard
              id="collaboration-partners"
              title={t("detail.partners.title")}
              count={(top_partners ?? []).length}
              compact
              description={
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs text-[var(--muted-foreground)]">
                    {t("detail.partners.description")}
                  </p>
                  <Link
                    href={`/${inst}/collaborations?${partnersQuery}`}
                    className="inline-flex items-center gap-1 text-xs font-medium text-[var(--primary-text)] underline-offset-2 hover:underline"
                  >
                    {t("detail.partners.exploreAll")}
                    <ArrowRight aria-hidden className="size-3.5" />
                  </Link>
                </div>
              }
              contentClassName="text-sm [&_td]:py-1.5 [&_th]:h-8"
            >
              <Table>
                <caption className="sr-only">{t("detail.partners.caption")}</caption>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("detail.partners.colPartner")}</TableHead>
                    <TableHead>{t("detail.partners.colCountry")}</TableHead>
                    <TableHead className="text-right">{t("detail.partners.colWorks")}</TableHead>
                    <TableHead className="text-right">{t("detail.partners.colOa")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(top_partners ?? []).map((p) => (
                    <TableRow key={p.ror}>
                      <TableCell className="font-medium">
                        <span className="inline-flex items-center gap-2">
                          <span
                            aria-hidden
                            className="inline-block size-2.5 shrink-0 rounded-full"
                            style={{ backgroundColor: orgTypeCssVar(p.org_type) }}
                          />
                          <Link
                            href={`/${inst}/collaborations/${encodeURIComponent(p.ror)}?${partnersQuery}`}
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

          {/* Block 5: Evidence & Data Quality */}
          <CrisGapsSection
            target={{ kind: "orgunit", level: unit.level, name: unit.name }}
            available={data.openalex_only.available}
          />
        </div>
      </div>
    </>
  );
}
