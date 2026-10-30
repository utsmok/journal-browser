"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import { DealBadge, OaTypeBadge, QuartileBadge } from "@/components/badges";
import { BackLink } from "@/components/back-link";
import { CardPager } from "@/components/card-pager";
import { CollapsibleCard } from "@/components/collapsible-card";
import { OaTrend } from "@/components/oa-trend";
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
import { useOrgUnit } from "@/hooks/use-api";
import { useInstitution } from "@/hooks/use-institution";
import {
  encodeNamePath,
  errorMessage,
  type OrgUnitDetailResponse,
  type OrgUnitItem,
  type OrgUnitLevel,
} from "@/lib/api";
import { formatEur } from "@/lib/format";

const PAGE_SIZE = 20;

/** Unit headline stats: authors, works, deal-covered share, APC spend. */
function UnitStats({ unit }: { unit: OrgUnitItem }) {
  const share = unit.n_works > 0 ? Math.round((unit.deal_works / unit.n_works) * 100) : 0;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-[var(--muted-foreground)]">
      <span className="tabular-nums">
        {unit.n_authors.toLocaleString("en")} {unit.n_authors === 1 ? "author" : "authors"}
      </span>
      <span aria-hidden>·</span>
      <span className="tabular-nums">
        {unit.n_works.toLocaleString("en")} {unit.n_works === 1 ? "work" : "works"}
      </span>
      <span aria-hidden>·</span>
      <span className="tabular-nums" title="Works in journals covered by an open access deal">
        {unit.deal_works.toLocaleString("en")} deal-covered
        {unit.n_works > 0 && ` (${share}%)`}
      </span>
      {unit.apc_n > 0 && (
        <>
          <span aria-hidden>·</span>
          <span
            className="tabular-nums"
            title={`APC paid for ${unit.apc_n} ${unit.apc_n === 1 ? "article" : "articles"}`}
          >
            {formatEur(unit.apc_euro_total)} € APC ({unit.apc_n})
          </span>
        </>
      )}
      {unit.n_groups != null && unit.n_groups > 0 && (
        <>
          <span aria-hidden>·</span>
          <span className="tabular-nums">
            {unit.n_groups.toLocaleString("en")} research {unit.n_groups === 1 ? "group" : "groups"}
          </span>
        </>
      )}
    </div>
  );
}

export default function OrgUnitPage() {
  const params = useParams<{ slug: string[] }>();
  const inst = useInstitution();
  const segments = params?.slug ?? [];
  const [levelSeg, ...nameSegs] = segments;
  const level: OrgUnitLevel | undefined =
    levelSeg === "faculty" || levelSeg === "group" ? levelSeg : undefined;
  const name = nameSegs.map(decodeURIComponent).join("/");

  const backHref = level === "group" ? `/${inst}/orgunit?level=group` : `/${inst}/orgunit`;
  const { data, isPending, isError, error } = useOrgUnit(level, level && name ? name : undefined);

  if (!level)
    return (
      <div className="mx-auto max-w-screen-2xl px-4 py-10">
        <p className="text-[var(--destructive)]">Unknown unit type. Use a faculty or group page.</p>
        <div className="mt-2">
          <BackLink href={`/${inst}/orgunit`} label="Back to faculties" />
        </div>
      </div>
    );
  if (isPending) return <DetailSkeleton />;
  if (isError || !data)
    return (
      <ErrorPanel
        message={errorMessage(error)}
        backHref={backHref}
        backLabel="Back"
        backClassName=""
      />
    );

  // Keyed by unit so per-card pagination restarts on navigation.
  return <OrgUnitDetail key={`${level}:${name}`} inst={inst} backHref={backHref} data={data} />;
}

function OrgUnitDetail({
  inst,
  backHref,
  data,
}: {
  inst: string;
  backHref: string;
  data: OrgUnitDetailResponse;
}) {
  const { unit, groups, journals, authors, works_by_year, deal_usage } = data;
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
        label={unit.level === "group" ? "Back to research groups" : "Back to faculties"}
      />
      <header className="mb-6 mt-4">
        <h1 className="text-3xl font-bold text-balance">{unit.name}</h1>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Badge variant="muted" className="font-normal">
            {unit.level === "group" ? "Research group" : "Faculty"}
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
          <CollapsibleCard id="groups" title="Research groups" contentClassName="text-sm">
            <Table>
              <caption className="sr-only">Research groups of this faculty</caption>
              <TableHeader>
                <TableRow>
                  <TableHead>Research group</TableHead>
                  <TableHead className="text-right">Authors</TableHead>
                  <TableHead className="text-right">Works</TableHead>
                  <TableHead className="text-right">Deal-covered</TableHead>
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
                label="groups"
              />
            )}
          </CollapsibleCard>
        )}

        {authors.length > 0 && (
          <CollapsibleCard id="authors" title="Most publishing authors" contentClassName="text-sm">
            <Table>
              <caption className="sr-only">Authors of this unit</caption>
              <TableHeader>
                <TableRow>
                  <TableHead>Author</TableHead>
                  <TableHead className="text-right">Works</TableHead>
                  <TableHead>Topic</TableHead>
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
                label="authors"
              />
            )}
          </CollapsibleCard>
        )}

        {journals.length > 0 && (
          <CollapsibleCard id="journals" title="Journals" contentClassName="text-sm">
            <Table>
              <caption className="sr-only">Journals this unit publishes in</caption>
              <TableHeader>
                <TableRow>
                  <TableHead>Journal</TableHead>
                  <TableHead className="text-right">Works</TableHead>
                  <TableHead>Access</TableHead>
                  <TableHead>Q</TableHead>
                  <TableHead>Deal</TableHead>
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

        {works_by_year.length > 0 && (
          <CollapsibleCard id="oa-over-time" title="Open access over time">
            <OaTrend stats={works_by_year} />
          </CollapsibleCard>
        )}

        {deal_usage.length > 0 && (
          <CollapsibleCard id="deal-usage" title="Deal usage" contentClassName="text-sm">
            <Table>
              <caption className="sr-only">Open access deals used by this unit</caption>
              <TableHeader>
                <TableRow>
                  <TableHead>Agreement</TableHead>
                  <TableHead className="text-right">Works</TableHead>
                  <TableHead className="text-right">APC</TableHead>
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
                    <TableCell className="text-right tabular-nums">{formatEur(d.euro)} €</TableCell>
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
