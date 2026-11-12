"use client";

import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import {
  DealBadge,
  OaStatusChip,
  OaTypeBadge,
  PureMatchBadge,
  QuartileBadge,
} from "@/components/badges";
import { BackLink } from "@/components/back-link";
import { CardPager } from "@/components/card-pager";
import { CollapsibleCard } from "@/components/collapsible-card";
import { OaTrend } from "@/components/oa-trend";
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
  type OrgUnitItem,
  type OrgUnitLevel,
} from "@/lib/api";
import { formatEur } from "@/lib/format";
import { workTypeLabel } from "@/lib/work-type";

const PAGE_SIZE = 20;

type OpenalexOnly = OrgUnitDetailResponse["openalex_only"];

/** OpenAlex works attributed to this unit's members that match no Pure
 * record: candidates missing from the research information system. */
function CrisGapsCard({ openalexOnly }: { openalexOnly: OpenalexOnly }) {
  const t = useTranslations("orgunits");
  const tc = useTranslations("common");
  const { total, items } = openalexOnly;
  return (
    <CollapsibleCard
      id="cris-gaps"
      title={t("detail.crisGaps.title")}
      description={
        <p className="text-sm text-[var(--muted-foreground)]">
          {t("detail.crisGaps.description", { count: total })}
          {total > items.length ? ` ${t("detail.crisGaps.showing", { count: items.length })}` : ""}
        </p>
      }
      contentClassName="text-sm"
    >
      {total === 0 ? (
        <p className="text-[var(--muted-foreground)]">{t("detail.crisGaps.empty")}</p>
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
                    {w.title ?? t("detail.crisGaps.untitled")}
                  </span>
                )}
                {w.year != null && (
                  <span className="tabular-nums text-[var(--muted-foreground)]">{w.year}</span>
                )}
                {w.venue && (
                  <span className="min-w-0 text-xs text-[var(--muted-foreground)]">{w.venue}</span>
                )}
                {w.work_type && <span className="text-xs">{workTypeLabel(tc, w.work_type)}</span>}
                <PureMatchBadge match={w.pure_match} url={w.pure_match_url} />
                <OaStatusChip status={w.oa_status} />
              </li>
            );
          })}
        </ul>
      )}
    </CollapsibleCard>
  );
}

/** Unit headline stats: authors, works, deal-covered share, APC spend. */
function UnitStats({ unit }: { unit: OrgUnitItem }) {
  const t = useTranslations("orgunits");
  const share = unit.n_works > 0 ? Math.round((unit.deal_works / unit.n_works) * 100) : 0;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-[var(--muted-foreground)]">
      <span className="tabular-nums">{t("counts.author", { count: unit.n_authors })}</span>
      <span aria-hidden>·</span>
      <span className="tabular-nums">{t("counts.work", { count: unit.n_works })}</span>
      <span aria-hidden>·</span>
      <span className="tabular-nums" title={t("tooltips.dealWorks")}>
        {t("counts.dealWork", { count: unit.deal_works })}
        {unit.n_works > 0 && ` ${t("detail.stats.share", { share })}`}
      </span>
      {unit.apc_n > 0 && (
        <>
          <span aria-hidden>·</span>
          <span className="tabular-nums" title={t("tooltips.apc", { count: unit.apc_n })}>
            {t("detail.stats.apc", { euro: formatEur(unit.apc_euro_total), count: unit.apc_n })}
          </span>
        </>
      )}
      {unit.n_groups != null && unit.n_groups > 0 && (
        <>
          <span aria-hidden>·</span>
          <span className="tabular-nums">{t("counts.group", { count: unit.n_groups })}</span>
        </>
      )}
    </div>
  );
}

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
  const { data, isPending, isError, error } = useOrgUnit(
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
  if (isPending) return <DetailSkeleton />;
  if (isError || !data)
    return (
      <ErrorPanel
        message={errorMessage(tc, error)}
        backHref={backHref}
        backLabel={t("detail.backGeneric")}
        backClassName=""
      />
    );

  // Keyed by unit so per-card pagination restarts on navigation.
  return (
    <OrgUnitDetail
      key={`${level}:${name}`}
      inst={inst}
      backHref={backHref}
      data={data}
      authorSort={authorSort}
      onAuthorSortChange={setAuthorSort}
    />
  );
}

function OrgUnitDetail({
  inst,
  backHref,
  data,
  authorSort,
  onAuthorSortChange,
}: {
  inst: string;
  backHref: string;
  data: OrgUnitDetailResponse;
  authorSort: OrgUnitAuthorSort;
  onAuthorSortChange: (sort: OrgUnitAuthorSort) => void;
}) {
  const t = useTranslations("orgunits");
  const { year_from, year_to } = useYearRange();
  const { unit, groups, journals, authors, works_by_year, deal_usage } = data;
  const trendYears = works_by_year.filter(
    (s) =>
      (year_from === undefined || s.year >= year_from) &&
      (year_to === undefined || s.year <= year_to),
  );
  const [groupPage, setGroupPage] = React.useState(1);
  const [authorPage, setAuthorPage] = React.useState(1);
  const groupRows = (groups ?? []).slice((groupPage - 1) * PAGE_SIZE, groupPage * PAGE_SIZE);
  const authorRows = authors.slice((authorPage - 1) * PAGE_SIZE, authorPage * PAGE_SIZE);
  const groupPages = Math.max(1, Math.ceil((groups ?? []).length / PAGE_SIZE));
  const authorPages = Math.max(1, Math.ceil(authors.length / PAGE_SIZE));

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <BackLink
        href={backHref}
        label={
          unit.level === "group"
            ? t("detail.back.group")
            : unit.level === "faculty"
              ? t("detail.back.faculty")
              : t("detail.back.institute")
        }
      />
      <header className="mb-6 mt-4">
        <h1 className="text-3xl font-bold text-balance">{unit.name}</h1>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Badge variant="muted" className="font-normal">
            {unit.level === "group"
              ? t("detail.badge.group")
              : unit.level === "institute"
                ? t("detail.badge.institute")
                : t("detail.badge.faculty")}
          </Badge>
          {unit.faculty && (
            <Badge variant="muted" className="font-normal">
              {unit.faculty}
            </Badge>
          )}
        </div>
        <UnitStats unit={unit} />
      </header>

      <div className="space-y-6">
        {groups != null && groups.length > 0 && (
          <CollapsibleCard id="groups" title={t("detail.groups.title")} contentClassName="text-sm">
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

        {authors.length > 0 && (
          <CollapsibleCard
            id="authors"
            title={t("detail.authors.title")}
            description={
              <div
                role="group"
                aria-label={t("detail.authors.rankBy")}
                className="mt-2 flex flex-wrap items-center gap-2"
              >
                <div className="flex overflow-hidden rounded-[var(--radius)] border border-[var(--input)]">
                  <Button
                    variant={authorSort === "share" ? "secondary" : "ghost"}
                    size="sm"
                    className="rounded-none"
                    aria-pressed={authorSort === "share"}
                    title={t("detail.authors.shareSortTitle")}
                    onClick={() => onAuthorSortChange("share")}
                  >
                    {t("detail.authors.shareSort")}
                  </Button>
                  <Button
                    variant={authorSort === "works" ? "secondary" : "ghost"}
                    size="sm"
                    className="rounded-none"
                    aria-pressed={authorSort === "works"}
                    onClick={() => onAuthorSortChange("works")}
                  >
                    {t("detail.authors.worksSort")}
                  </Button>
                </div>
              </div>
            }
            contentClassName="text-sm"
          >
            <Table>
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

        {data.openalex_only.available && <CrisGapsCard openalexOnly={data.openalex_only} />}

        {journals.length > 0 && (
          <CollapsibleCard
            id="journals"
            title={t("detail.journals.title")}
            contentClassName="text-sm"
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
          </CollapsibleCard>
        )}

        {trendYears.length > 0 && (
          <CollapsibleCard id="oa-over-time" title={t("detail.trendTitle")}>
            <OaTrend stats={trendYears} />
          </CollapsibleCard>
        )}

        {deal_usage.length > 0 && (
          <CollapsibleCard
            id="deal-usage"
            title={t("detail.dealUsage.title")}
            description={
              <p className="text-sm text-[var(--muted-foreground)]">
                {t("detail.dealUsage.description")}
              </p>
            }
            contentClassName="text-sm"
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
                      <span className="block max-w-72 truncate" title={d.label}>
                        {d.label}
                      </span>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {d.n_works.toLocaleString("en")}
                    </TableCell>
                    {/* euro 0 with no evidence rows means "no amount data",
                        not "free": sibling surfaces gate on apc_n > 0. */}
                    <TableCell className="text-right tabular-nums">
                      {d.euro ? `${formatEur(d.euro)} €` : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CollapsibleCard>
        )}
      </div>
    </div>
  );
}
