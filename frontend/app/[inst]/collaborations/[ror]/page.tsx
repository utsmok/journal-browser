"use client";

import { useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import * as React from "react";

import { BackLink } from "@/components/back-link";
import { BarList } from "@/components/collaborations/bar-list";
import { useCollabLabels } from "@/components/collaborations/labels";
import { Pager } from "@/components/collaborations/pager";
import { CollaborationSources } from "@/components/collaborations/sources";
import { useCollabParams, writeCollabParams } from "@/components/collaborations/use-collab-params";
import { GapCsvButton } from "@/components/gap-csv-button";
import { ErrorPanel, ListSkeletonRows } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
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
  COLLAB_DEFAULT_YEARS,
  COLLAB_PAGE_SIZE,
  collaborationCsvHref,
  errorMessage,
} from "@/lib/api";
import { workTypeLabel } from "@/lib/work-type";

/** Years listed one by one in the per-year chart; longer ranges list only
 * the years that have works. */
const MAX_YEAR_ROWS = 30;

const linkClass = "underline decoration-dotted underline-offset-2 hover:decoration-solid";
const external = { target: "_blank", rel: "noopener noreferrer" } as const;

function Credits({
  title,
  empty,
  rows,
}: {
  title: string;
  empty: string;
  rows: { key: string; label: string; note: string; works: number }[];
}) {
  return (
    <div>
      <h3 className="text-sm font-semibold">{title}</h3>
      {rows.length === 0 ? (
        <p className="mt-2 text-sm text-[var(--muted-foreground)]">{empty}</p>
      ) : (
        <ol className="mt-1 divide-y divide-[var(--border)]">
          {rows.map((row) => (
            <li key={row.key} className="flex items-baseline justify-between gap-4 py-1.5 text-sm">
              <span className="min-w-0 truncate">
                {row.label}
                {row.note && (
                  <span className="ml-2 text-xs text-[var(--muted-foreground)]">{row.note}</span>
                )}
              </span>
              <span className="shrink-0 tabular-nums">{row.works.toLocaleString("en")}</span>
            </li>
          ))}
        </ol>
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
  const [filters] = useCollabParams();
  const [offset, setOffset] = React.useState(0);

  // The list filters carry over, so a partner opened under a funder shows
  // only the works that funder paid for.
  const params = React.useMemo(
    () =>
      year_from === undefined
        ? { ...filters, ...COLLAB_DEFAULT_YEARS }
        : { ...filters, year_from, year_to },
    [filters, year_from, year_to],
  );

  React.useEffect(() => {
    setOffset(0);
  }, [params]);

  const detail = useCollaboration(ror, params);
  const works = useCollaborationWorks(ror ?? "", params, offset);
  const d = detail.data;

  const from = params.year_from ?? COLLAB_DEFAULT_YEARS.year_from;
  const to = params.year_to ?? COLLAB_DEFAULT_YEARS.year_to;
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

  // ROR ids arrive as bare ids or as full URLs; the page shows the bare id.
  const bareRor = (value: string) => value.replace(/^https?:\/\/ror\.org\//, "");
  const facts: { term: string; value: React.ReactNode }[] = [];
  if (d) {
    if (d.org_type) facts.push({ term: t("detail.facts.type"), value: labels.orgType(d.org_type) });
    if (d.country_code) {
      facts.push({ term: t("detail.facts.country"), value: labels.region(d.country_code) });
    }
    if (d.city) facts.push({ term: t("detail.facts.city"), value: d.city });
    if (d.parent_name) {
      facts.push({ term: t("detail.facts.parent"), value: d.parent_name });
    }
    facts.push({
      term: t("detail.facts.ror"),
      value: (
        <a href={`https://ror.org/${bareRor(d.ror)}`} {...external} className={linkClass}>
          {bareRor(d.ror)}
        </a>
      ),
    });
    if (d.openalex_id) {
      const id = d.openalex_id.replace(/^https?:\/\/openalex\.org\//, "");
      facts.push({
        term: t("detail.facts.openalex"),
        value: (
          <a href={`https://openalex.org/${id}`} {...external} className={linkClass}>
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
                className={linkClass}
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
              <li key={`${rel.type}:${rel.ror}`}>
                <span className="text-[var(--muted-foreground)]">
                  {relationTypes[rel.type.toLowerCase()] ?? rel.type}:{" "}
                </span>
                <a href={`https://ror.org/${bareRor(rel.ror)}`} {...external} className={linkClass}>
                  {rel.label}
                </a>
              </li>
            ))}
          </ul>
        ),
      });
    }
  }

  // Per-year counts arrive only for years with works; a short range lists
  // every year so gaps stay visible.
  let yearRows: { label: string; count: number }[] = [];
  let typeRows: { label: string; count: number }[] = [];
  if (d) {
    typeRows = d.works_by_type.map((row) => ({
      label: workTypeLabel(tc, row.value) ?? row.value,
      count: row.count,
    }));
    const counts = new Map(d.per_year.map((row) => [row.year, row.works]));
    const span = to - from + 1;
    yearRows =
      span > 0 && span <= MAX_YEAR_ROWS
        ? Array.from({ length: span }, (_, i) => ({
            label: String(from + i),
            count: counts.get(from + i) ?? 0,
          }))
        : d.per_year.map((row) => ({ label: String(row.year), count: row.works }));
  }
  const share =
    d?.share == null
      ? null
      : d.share * 100 < 0.1
        ? "<0.1"
        : (d.share * 100).toFixed(1).replace(/\.0$/, "");
  const shown = works.data?.items.length ?? 0;
  const total = works.data?.total ?? 0;

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <BackLink href={listHref} label={t("detail.back")} />
      {detail.isPending && (
        <div className="mt-4">
          <ListSkeletonRows rows={6} />
        </div>
      )}
      {d && (
        <>
          <header className="mt-4">
            <h1 className="text-3xl font-bold text-balance">{d.name}</h1>
            {d.status && d.status !== "active" && (
              <Badge variant="outline" className="mt-2">
                {t("detail.facts.inactive")}
              </Badge>
            )}
            <dl className="mt-4 grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2 xl:grid-cols-3">
              {facts.map((fact) => (
                <div key={fact.term} className="flex gap-3">
                  <dt className="w-36 shrink-0 text-[var(--muted-foreground)]">{fact.term}</dt>
                  <dd className="min-w-0">{fact.value}</dd>
                </div>
              ))}
            </dl>
          </header>

          <div className="mt-6 max-w-prose space-y-1 text-sm">
            <p>
              {t("detail.stats", {
                works: d.works.toLocaleString("en"),
                corresponding: d.corresponding_works.toLocaleString("en"),
                authorships: d.authorships.toLocaleString("en"),
                from,
                to,
              })}
            </p>
            {share !== null && (
              <p className="text-[var(--muted-foreground)]">
                {t("detail.share", { share, inst: site.short })}
              </p>
            )}
          </div>

          <div className="mt-8 grid gap-8 lg:grid-cols-2">
            <Credits
              title={t("detail.funders")}
              empty={t("detail.noFunders")}
              rows={d.funders.map((f) => ({
                key: f.key,
                label: f.name,
                note: labels.sources(f.sources),
                works: f.works,
              }))}
            />
            <Credits
              title={t("detail.projects")}
              empty={t("detail.noProjects")}
              rows={d.projects.map((p) => ({
                key: p.key,
                label: p.acronym || p.code || p.key,
                note: [p.funder, p.code, labels.source(p.source)].filter(Boolean).join(" · "),
                works: p.works,
              }))}
            />
          </div>

          <div className="mt-8 grid gap-8 lg:grid-cols-2">
            <BarList title={t("detail.byType")} rows={typeRows} />
            <BarList title={t("detail.byYear")} rows={yearRows} />
          </div>

          <section className="mt-8" aria-labelledby="partner-works-title">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 id="partner-works-title" className="text-base font-semibold">
                {t("detail.works.title")}
              </h2>
              <GapCsvButton href={collaborationCsvHref(inst, params, ror)} />
            </div>
            <div className="mt-3">
              {works.isPending && <ListSkeletonRows rows={6} />}
              {works.isError && (
                <div>
                  <p role="alert" className="text-[var(--destructive)]">
                    {errorMessage(tc, works.error)}
                  </p>
                </div>
              )}
              {works.data && (
                <Card>
                  <CardContent className="pt-6">
                    <Table className={works.isPlaceholderData ? "opacity-60" : undefined}>
                      <TableHeader>
                        <TableRow>
                          <TableHead>{t("detail.works.work")}</TableHead>
                          <TableHead>{t("detail.works.year")}</TableHead>
                          <TableHead>{t("detail.works.type")}</TableHead>
                          <TableHead>{t("detail.works.authors")}</TableHead>
                          <TableHead>{t("detail.works.corresponding")}</TableHead>
                          <TableHead>{t("detail.works.source")}</TableHead>
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
                            const authors = w.authors.slice(0, 3).join(", ");
                            const more = w.authors.length - 3;
                            return (
                              <TableRow key={w.pure_uuid}>
                                <TableCell className="max-w-md">
                                  {w.doi ? (
                                    <a
                                      href={`https://doi.org/${w.doi}`}
                                      {...external}
                                      className={`font-medium ${linkClass}`}
                                    >
                                      {w.title}
                                    </a>
                                  ) : (
                                    <span className="font-medium">{w.title}</span>
                                  )}
                                </TableCell>
                                <TableCell className="tabular-nums">{w.year}</TableCell>
                                <TableCell className="text-[var(--muted-foreground)]">
                                  {workTypeLabel(tc, w.work_type) ?? "—"}
                                </TableCell>
                                <TableCell className="max-w-xs text-[var(--muted-foreground)]">
                                  {authors}
                                  {more > 0 && ` ${t("detail.works.moreAuthors", { count: more })}`}
                                </TableCell>
                                <TableCell>
                                  {w.corresponding ? t("detail.works.correspondingYes") : "—"}
                                </TableCell>
                                <TableCell className="text-[var(--muted-foreground)]">
                                  {labels.source(w.source)}
                                </TableCell>
                              </TableRow>
                            );
                          })
                        )}
                      </TableBody>
                    </Table>
                    {total > COLLAB_PAGE_SIZE && (
                      <Pager
                        offset={offset}
                        shown={shown}
                        total={total}
                        pageSize={COLLAB_PAGE_SIZE}
                        onOffset={setOffset}
                      />
                    )}
                  </CardContent>
                </Card>
              )}
            </div>
          </section>

          <div className="mt-8">
            <CollaborationSources />
          </div>
        </>
      )}
    </div>
  );
}

/** useSearchParams needs a Suspense boundary during prerender. */
export default function PartnerPage() {
  return (
    <React.Suspense fallback={null}>
      <PartnerPageInner />
    </React.Suspense>
  );
}
