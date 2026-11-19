"use client";

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDateTime } from "@/lib/format";
import type { AdminRun, InstitutionDirectoryEntry } from "@/lib/admin";

export function StatusBadge({ status }: { status: string }) {
  const variant =
    status === "completed"
      ? "secondary"
      : status === "failed"
        ? "destructive"
        : status === "running"
          ? "default"
          : "muted";
  return <Badge variant={variant}>{status}</Badge>;
}

/** Top stat pairs as compact copy ("3,875 policies · 282 funders"); the
 * full JSON stays in the tooltip for anything the summary leaves out. */
function statsSummary(stats: AdminRun["stats"]): string {
  const entries = Object.entries(stats ?? {})
    .filter(([, v]) => typeof v === "number" || typeof v === "string")
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 3);
  if (entries.length === 0) return "—";
  return entries
    .map(
      ([k, v]) => `${typeof v === "number" ? v.toLocaleString("en") : v} ${k.replace(/_/g, " ")}`,
    )
    .join(" · ");
}

/** Harvest runs table shared by the global and per-institution admin pages. */
export function RunsTable({
  runs,
  directory = [],
  onRowClick,
}: {
  runs: AdminRun[];
  directory?: InstitutionDirectoryEntry[];
  onRowClick?: (run: AdminRun) => void;
}) {
  const t = useTranslations("admin");
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("runs.columnsNumber")}</TableHead>
          <TableHead>{t("runs.columnsInstitution")}</TableHead>
          <TableHead>{t("runs.columnsSource")}</TableHead>
          <TableHead>{t("runs.columnsStatus")}</TableHead>
          <TableHead>{t("runs.columnsStarted")}</TableHead>
          <TableHead>{t("runs.columnsStats")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run) => (
          <TableRow
            key={run.id}
            className={onRowClick ? "cursor-pointer" : undefined}
            title={onRowClick ? t("runs.clickForDetails") : undefined}
            onClick={onRowClick ? () => onRowClick(run) : undefined}
          >
            <TableCell>{run.id}</TableCell>
            <TableCell>
              {run.institution_code == null
                ? t("runs.shared")
                : (directory.find((i) => i.code === run.institution_code)?.short_name ??
                  run.institution_code)}
            </TableCell>
            <TableCell>
              {run.source}/{run.entity_type}
            </TableCell>
            <TableCell>
              <StatusBadge status={run.status} />
            </TableCell>
            <TableCell className="whitespace-nowrap text-muted-foreground">
              {formatDateTime(run.started_at)}
            </TableCell>
            <TableCell className="max-w-md truncate text-xs" title={JSON.stringify(run.stats)}>
              {statsSummary(run.stats)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
