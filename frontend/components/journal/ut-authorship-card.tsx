"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { CollapsibleCard } from "@/components/collapsible-card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { UtAuthorship } from "@/components/journal/shared";

/** Who at this institution authors the journal's works: distinct works
 * per faculty and research group, plus the most prolific UT authors. */
export function UtAuthorshipCard({ authorship, inst }: { authorship: UtAuthorship; inst: string }) {
  const t = useTranslations("journals");
  const empty =
    authorship.faculties.length === 0 &&
    authorship.research_groups.length === 0 &&
    authorship.top_authors.length === 0;
  return (
    <CollapsibleCard
      id="ut-authorship"
      title={t("utAuthorship.title")}
      defaultOpen={false}
      description={
        <p className="text-sm text-[var(--muted-foreground)]">
          {t("utAuthorship.description", { count: authorship.n_ut_works })}
        </p>
      }
      contentClassName="space-y-5 text-sm"
    >
      {empty ? (
        <p className="text-[var(--muted-foreground)]">{t("utAuthorship.empty")}</p>
      ) : (
        <>
          {(
            [
              {
                heading: t("utAuthorship.facultiesHeading"),
                caption: t("utAuthorship.captionFaculties"),
                rows: authorship.faculties,
              },
              {
                heading: t("utAuthorship.groupsHeading"),
                caption: t("utAuthorship.captionGroups"),
                rows: authorship.research_groups,
              },
            ] as const
          ).map(
            (table) =>
              table.rows.length > 0 && (
                <div key={table.heading}>
                  <h3 className="mb-1 text-sm font-semibold">{table.heading}</h3>
                  <Table>
                    <caption className="sr-only">{table.caption}</caption>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t("utAuthorship.nameCol")}</TableHead>
                        <TableHead className="text-right">{t("utAuthorship.worksCol")}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {table.rows.map((row) => (
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
              <h3 className="mb-1 text-sm font-semibold">{t("utAuthorship.topAuthorsHeading")}</h3>
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
