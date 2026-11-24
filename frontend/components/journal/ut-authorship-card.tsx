"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import * as React from "react";

import { CollapsibleCard } from "@/components/collapsible-card";
import { MoreToggle, type UtAuthorship } from "@/components/journal/shared";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { encodeNamePath } from "@/lib/api";

const SUBTABLE_CAP = 10;

/** Who at this institution authors the journal's works: distinct works
 * per faculty and research group, plus the most prolific UT authors. */
export function UtAuthorshipCard({ authorship, inst }: { authorship: UtAuthorship; inst: string }) {
  const t = useTranslations("journals");
  const [showAll, setShowAll] = React.useState<Record<string, boolean>>({});
  const empty =
    authorship.faculties.length === 0 &&
    authorship.research_groups.length === 0 &&
    authorship.top_authors.length === 0;
  return (
    <CollapsibleCard
      id="ut-authorship"
      title={t("utAuthorship.title")}
      count={authorship.n_ut_works > 0 ? authorship.n_ut_works : undefined}
      defaultOpen={false}
      compact
      description={
        <p className="text-xs text-[var(--muted-foreground)]">
          {t("utAuthorship.description", { count: authorship.n_ut_works })}
        </p>
      }
      contentClassName="space-y-4 text-sm [&_td]:py-1.5 [&_th]:h-8"
    >
      {empty ? (
        <p className="text-[var(--muted-foreground)]">{t("utAuthorship.empty")}</p>
      ) : (
        <>
          {(
            [
              {
                key: "faculties",
                level: "faculty" as const,
                heading: t("utAuthorship.facultiesHeading"),
                caption: t("utAuthorship.captionFaculties"),
                rows: authorship.faculties,
              },
              {
                key: "groups",
                level: "group" as const,
                heading: t("utAuthorship.groupsHeading"),
                caption: t("utAuthorship.captionGroups"),
                rows: authorship.research_groups,
              },
            ] as const
          ).map((table) => {
            if (table.rows.length === 0) return null;
            const expanded = !!showAll[table.key];
            const visible = expanded ? table.rows : table.rows.slice(0, SUBTABLE_CAP);
            return (
              <div key={table.heading}>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                  {table.heading}
                </h3>
                <Table>
                  <caption className="sr-only">{table.caption}</caption>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("utAuthorship.nameCol")}</TableHead>
                      <TableHead className="text-right">{t("utAuthorship.worksCol")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {visible.map((row) => (
                      <TableRow key={row.name}>
                        <TableCell className="font-medium">
                          <Link
                            href={`/${inst}/orgunit/${table.level}/${encodeNamePath(row.name)}`}
                            className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                          >
                            {row.name}
                          </Link>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {row.works.toLocaleString("en")}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                {table.rows.length > SUBTABLE_CAP && (
                  <div className="mt-1.5">
                    <MoreToggle
                      open={expanded}
                      onToggle={() => setShowAll((s) => ({ ...s, [table.key]: !s[table.key] }))}
                      moreLabel={t("list.showAllCount", { count: table.rows.length })}
                    />
                  </div>
                )}
              </div>
            );
          })}
          {authorship.top_authors.length > 0 && (
            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                {t("utAuthorship.topAuthorsHeading")}
              </h3>
              <Table>
                <caption className="sr-only">{t("utAuthorship.captionTopAuthors")}</caption>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("utAuthorship.authorCol")}</TableHead>
                    <TableHead className="text-right">{t("utAuthorship.worksCol")}</TableHead>
                    <TableHead>{t("utAuthorship.affiliationCol")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(showAll.authors
                    ? authorship.top_authors
                    : authorship.top_authors.slice(0, SUBTABLE_CAP)
                  ).map((a) => (
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
              {authorship.top_authors.length > SUBTABLE_CAP && (
                <div className="mt-1.5">
                  <MoreToggle
                    open={!!showAll.authors}
                    onToggle={() => setShowAll((s) => ({ ...s, authors: !s.authors }))}
                    moreLabel={t("list.showAllCount", { count: authorship.top_authors.length })}
                  />
                </div>
              )}
            </div>
          )}
        </>
      )}
    </CollapsibleCard>
  );
}
