"use client";

import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/format";
import { daysAgo, sourceInfo, type FreshnessStatus, type SourceFreshness } from "@/lib/freshness";
import { cn } from "@/lib/utils";

const SCHEDULE_LABEL = {
  nightly: "scheduleNightly",
  weekly: "scheduleWeekly",
  manual: "scheduleManual",
} as const;
const STATUS_LABEL = { ok: "statusOk", overdue: "statusOverdue", failed: "statusFailed" } as const;
const STATUS_BADGE = { ok: "muted", overdue: "outline", failed: "destructive" } as const;

function StatusBadge({ status }: { status: FreshnessStatus }) {
  const t = useTranslations("about");
  return (
    <Badge
      variant={STATUS_BADGE[status]}
      className={cn(
        "font-medium",
        status === "overdue" && "border-amber-500/60 text-amber-700 dark:text-amber-400",
      )}
    >
      {t(`freshness.${STATUS_LABEL[status]}`)}
    </Badge>
  );
}

function RefreshedAt({ at, now }: { at: string | null | undefined; now: Date }) {
  const t = useTranslations("about");
  if (!at) return <>{t("freshness.neverRefreshed")}</>;
  return (
    <>
      {formatDate(at)}{" "}
      <span className="text-[var(--muted-foreground)]">
        ({t("freshness.age", { days: daysAgo(at, now) })})
      </span>
    </>
  );
}

/** "Data freshness" table of the About page: the institution's own sources
 * first, then those shared by every institution. The rows come from
 * /meta/freshness (services/freshness.py in the backend). From md up it is a
 * table; below that each source is a card, because five columns do not fit a
 * phone. */
export function FreshnessTable({
  rows,
  institution,
  portalUrl,
}: {
  rows: SourceFreshness[];
  institution: string;
  portalUrl: string;
}) {
  const t = useTranslations("about");
  const now = new Date();
  const groups = [
    {
      label: t("freshness.groupInstitution", { institution }),
      rows: rows.filter((row) => row.institution_code),
    },
    { label: t("freshness.groupShared"), rows: rows.filter((row) => !row.institution_code) },
  ].filter((group) => group.rows.length > 0);

  // What one row shows, built once for both layouts.
  function view(row: SourceFreshness) {
    const info = sourceInfo(row.source);
    const href = row.source === "pure" ? portalUrl : info.url;
    const description = `freshness.rows.${row.source}`;
    const name = (
      <>
        {info.name}{" "}
        {href && <ExternalLink aria-hidden className="inline-block size-3 align-[-0.15em]" />}
      </>
    );
    return {
      name: href ? (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="font-semibold text-[var(--primary-text)] hover:underline"
        >
          {name}
        </a>
      ) : (
        <span className="font-semibold">{name}</span>
      ),
      provides: t.has(description) ? t(description) : null,
      refreshed: <RefreshedAt at={row.last_success_at} now={now} />,
      schedule: t(`freshness.${SCHEDULE_LABEL[row.schedule]}`),
      status: <StatusBadge status={row.status} />,
    };
  }

  return (
    <>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full min-w-[40rem] text-sm">
          <caption className="sr-only">{t("freshness.tableCaption")}</caption>
          <thead>
            <tr className="text-left text-xs text-[var(--muted-foreground)]">
              <th scope="col" className="py-1 pr-4 font-medium">
                {t("freshness.columnSource")}
              </th>
              <th scope="col" className="py-1 pr-4 font-medium">
                {t("freshness.columnProvides")}
              </th>
              <th scope="col" className="py-1 pr-4 font-medium">
                {t("freshness.columnLastRefreshed")}
              </th>
              <th scope="col" className="py-1 pr-4 font-medium">
                {t("freshness.columnExpected")}
              </th>
              <th scope="col" className="py-1 font-medium">
                {t("freshness.columnStatus")}
              </th>
            </tr>
          </thead>
          {groups.map((group) => (
            <tbody key={group.label}>
              <tr>
                <th
                  scope="rowgroup"
                  colSpan={5}
                  className="pt-3 pb-1 text-left text-xs font-semibold text-[var(--muted-foreground)]"
                >
                  {group.label}
                </th>
              </tr>
              {group.rows.map((row) => {
                const v = view(row);
                return (
                  <tr
                    key={`${row.institution_code ?? "shared"}:${row.source}`}
                    className="border-t border-[var(--border)] align-top"
                  >
                    <td className="py-2 pr-4 whitespace-nowrap">{v.name}</td>
                    <td className="max-w-[28rem] py-2 pr-4 text-[var(--muted-foreground)]">
                      {v.provides}
                    </td>
                    <td className="py-2 pr-4 whitespace-nowrap tabular-nums">{v.refreshed}</td>
                    <td className="py-2 pr-4 whitespace-nowrap text-[var(--muted-foreground)]">
                      {v.schedule}
                    </td>
                    <td className="py-2 whitespace-nowrap">{v.status}</td>
                  </tr>
                );
              })}
            </tbody>
          ))}
        </table>
      </div>

      <div className="space-y-4 md:hidden">
        {groups.map((group) => (
          <div key={group.label}>
            <h3 className="mb-2 text-xs font-semibold text-[var(--muted-foreground)]">
              {group.label}
            </h3>
            <ul className="space-y-2">
              {group.rows.map((row) => {
                const v = view(row);
                return (
                  <li
                    key={`${row.institution_code ?? "shared"}:${row.source}`}
                    className="rounded-[var(--radius)] border border-[var(--border)] p-3 text-sm"
                  >
                    <div className="flex items-start justify-between gap-3">
                      {v.name}
                      {v.status}
                    </div>
                    <p className="mt-2 text-[var(--muted-foreground)]">
                      {t("freshness.columnLastRefreshed")}:{" "}
                      <span className="tabular-nums text-[var(--foreground)]">{v.refreshed}</span>
                    </p>
                    <p className="text-[var(--muted-foreground)]">
                      {t("freshness.columnExpected")}: {v.schedule}
                    </p>
                    {v.provides && (
                      <p className="mt-2 text-xs text-[var(--muted-foreground)]">{v.provides}</p>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </>
  );
}
