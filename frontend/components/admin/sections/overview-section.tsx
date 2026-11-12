"use client";

import Link from "next/link";
import { useState } from "react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/admin/admin-shell";
import { RunDrawer } from "@/components/admin/run-drawer";
import { RunsTable } from "@/components/admin/runs-table";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAdminResource } from "@/hooks/use-admin-resource";
import { formatDateTime } from "@/lib/format";
import { useAdminToken, type AdminRun, type AdminSummary, type FlaggedDeal } from "@/lib/admin";

function StatCard({
  href,
  label,
  value,
  warn,
}: {
  href: string;
  label: string;
  value: number | null;
  warn?: boolean;
}) {
  const tone = warn && (value ?? 0) > 0 ? "text-destructive" : "text-[var(--foreground)]";
  return (
    <Link
      href={href}
      className="rounded-[var(--radius)] border bg-[var(--card)] p-4 shadow-sm transition-colors hover:bg-[var(--muted)]"
    >
      <p className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
        {label}
      </p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone}`}>
        {value === null ? "…" : value.toLocaleString("en")}
      </p>
    </Link>
  );
}

/** Admin landing page: pipeline health counters plus recent activity. */
export function OverviewSection({ inst, basePath }: { inst?: string; basePath: string }) {
  const t = useTranslations("admin");
  const [token, setToken] = useAdminToken();
  const logout = () => setToken(null);
  const scope = inst ? `?institution=${encodeURIComponent(inst)}` : "";
  const summary = useAdminResource<AdminSummary>(
    `/summary${scope}`,
    token ?? "",
    logout,
    "summary",
  );
  const runs = useAdminResource<AdminRun[]>(
    `/runs?limit=8${inst ? `&institution=${encodeURIComponent(inst)}` : ""}`,
    token ?? "",
    logout,
    "recent runs",
  );
  const flagged = useAdminResource<FlaggedDeal[]>("/flagged", token ?? "", logout, "flagged deals");
  const [selectedRun, setSelectedRun] = useState<AdminRun | null>(null);

  const s = summary.data;
  const lastRun = s?.last_run;
  const flaggedRows = (flagged.data ?? []).slice(0, 6);

  return (
    <div className="space-y-8">
      <PageHeader
        title={t("overview.title")}
        lede={inst ? t("overview.ledeInst", { inst }) : t("overview.ledeAll")}
      />

      {summary.error && <p className="text-sm text-destructive">{summary.error}</p>}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatCard
          href={`${basePath}/runs`}
          label={t("overview.statFailedRuns")}
          value={s?.failed_runs_24h ?? null}
          warn
        />
        <StatCard
          href={`${basePath}/runs`}
          label={t("overview.statRunning")}
          value={s?.running_runs ?? null}
          warn
        />
        <StatCard
          href={`${basePath}/deals`}
          label={t("overview.statFlaggedDeals")}
          value={s?.flagged_deals ?? null}
          warn
        />
        <StatCard
          href={`${basePath}/feedback`}
          label={t("overview.statOpenFeedback")}
          value={s?.open_feedback ?? null}
          warn
        />
        <StatCard
          href={`${basePath}/identities`}
          label={t("overview.statAuthorCandidates")}
          value={s?.author_identity_candidates ?? null}
        />
        <StatCard
          href={`${basePath}/work-identities`}
          label={t("overview.statWorkCandidates")}
          value={s?.work_identity_candidates ?? null}
        />
      </div>

      {!inst && (s?.flagged_deals ?? 0) > 0 && (
        <p className="text-xs text-muted-foreground">{t("overview.scopeNote")}</p>
      )}

      {lastRun && (
        <p className="text-sm text-muted-foreground">
          {t("overview.lastRunPrefix")}{" "}
          <span className="font-medium text-[var(--foreground)]">
            {lastRun.source} / {lastRun.entity_type}
          </span>{" "}
          {lastRun.institution_code
            ? t("overview.lastRunMetaInst", {
                status: lastRun.status,
                started: formatDateTime(lastRun.started_at),
                instCode: lastRun.institution_code,
              })
            : t("overview.lastRunMeta", {
                status: lastRun.status,
                started: formatDateTime(lastRun.started_at),
              })}
        </p>
      )}

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">{t("overview.recentRunsTitle")}</h2>
          <Link href={`${basePath}/runs`} className="text-sm underline-offset-2 hover:underline">
            {t("overview.viewAll")}
          </Link>
        </div>
        {runs.error && <p className="text-sm text-destructive">{runs.error}</p>}
        <RunsTable runs={runs.data ?? []} onRowClick={setSelectedRun} />
        {!runs.loading && (runs.data ?? []).length === 0 && (
          <p className="text-sm text-muted-foreground">{t("overview.noRuns")}</p>
        )}
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">
            {flagged.data
              ? t("overview.flaggedTitle", { count: flagged.data.length })
              : t("overview.flaggedTitleLoading")}
          </h2>
          <Link href={`${basePath}/deals`} className="text-sm underline-offset-2 hover:underline">
            {t("overview.reviewInDeals")}
          </Link>
        </div>
        {flagged.error && <p className="text-sm text-destructive">{flagged.error}</p>}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("deals.flaggedColumnPublisher")}</TableHead>
              <TableHead>{t("deals.flaggedColumnEsac")}</TableHead>
              <TableHead>{t("deals.flaggedColumnStatus")}</TableHead>
              <TableHead>{t("deals.flaggedColumnJournals")}</TableHead>
              <TableHead>{t("deals.flaggedColumnReason")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {flaggedRows.map((deal) => (
              <TableRow key={deal.id}>
                <TableCell className="font-medium">{deal.publisher}</TableCell>
                <TableCell className="font-mono text-xs">{deal.esac_id ?? "—"}</TableCell>
                <TableCell>{deal.status}</TableCell>
                <TableCell className="tabular-nums">{deal.journals}</TableCell>
                <TableCell
                  className="max-w-md truncate text-muted-foreground"
                  title={deal.reason ?? ""}
                >
                  {deal.reason ?? "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {!flagged.loading && (flagged.data ?? []).length === 0 && (
          <p className="text-sm text-muted-foreground">{t("overview.noFlagged")}</p>
        )}
      </section>

      {selectedRun && <RunDrawer run={selectedRun} onClose={() => setSelectedRun(null)} />}
    </div>
  );
}
