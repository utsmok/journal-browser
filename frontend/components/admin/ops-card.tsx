"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { useAdminResource } from "@/hooks/use-admin-resource";
import { formatDate, formatDateTime } from "@/lib/format";
import type { components } from "@/lib/api-types";
import { sourceInfo, staleSources, type SourceFreshness } from "@/lib/freshness";
import { useAdminToken } from "@/lib/admin";
import { cn } from "@/lib/utils";

type AdminOpsStatus = components["schemas"]["AdminOpsStatusOut"];

const SCHEDULE_LABELS: Record<string, string> = {
  refresh_wave: "ops.scheduleRefreshWave",
  source_wave: "ops.scheduleSourceWave",
  backup: "ops.scheduleBackup",
};

const SOURCE_SCHEDULE_LABELS = {
  nightly: "ops.sourceScheduleNightly",
  weekly: "ops.sourceScheduleWeekly",
  manual: "ops.sourceScheduleManual",
} as const;
const SOURCE_STATUS_LABELS = {
  ok: "ops.sourceStatusOk",
  overdue: "ops.sourceStatusOverdue",
  failed: "ops.sourceStatusFailed",
} as const;
const SOURCE_STATUS_BADGE = { ok: "muted", overdue: "outline", failed: "destructive" } as const;

function formatBytes(n: number): string {
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} GB`;
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${n} B`;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap justify-between gap-x-4 gap-y-0.5 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right">{children}</span>
    </div>
  );
}

function SourceRow({ row }: { row: SourceFreshness }) {
  const t = useTranslations("admin");
  return (
    <tr className="border-t border-[var(--border)] align-top">
      <td className="py-1.5 pr-3 font-medium">{sourceInfo(row.source).name}</td>
      <td className="py-1.5 pr-3">{row.institution_code ?? t("ops.freshnessShared")}</td>
      <td className="py-1.5 pr-3 text-muted-foreground">
        {t(SOURCE_SCHEDULE_LABELS[row.schedule])}
      </td>
      <td className="py-1.5 pr-3 whitespace-nowrap tabular-nums">
        {row.last_success_at ? formatDate(row.last_success_at) : t("ops.freshnessNever")}
      </td>
      <td className="py-1.5 whitespace-nowrap">
        <Badge
          variant={SOURCE_STATUS_BADGE[row.status]}
          className={cn(
            "font-medium",
            row.status === "overdue" && "border-amber-500/60 text-amber-700 dark:text-amber-400",
          )}
        >
          {t(SOURCE_STATUS_LABELS[row.status])}
        </Badge>
        {row.failed_parts.length > 0 && (
          <>
            {" "}
            <span className="text-muted-foreground">({row.failed_parts.join(", ")})</span>
          </>
        )}
      </td>
    </tr>
  );
}

/** Operations card for the admin overview: the nightly wave outcome, the
 * scheduled jobs, the newest backup, and per-source data freshness for every
 * institution. Sources that failed or missed a refresh are named at the top.
 * The endpoint is read-only by design — there is no "run now" trigger. */
export function OpsCard({ basePath }: { basePath: string }) {
  const t = useTranslations("admin");
  const [token, setToken] = useAdminToken();
  const logout = () => setToken(null);
  const ops = useAdminResource<AdminOpsStatus>("/ops/status", token ?? "", logout, "ops status");
  const ops_ = ops.data;

  if (ops.loading) return <p className="text-sm text-muted-foreground">{t("loading")}</p>;
  if (ops.error) return <p className="text-sm text-destructive">{ops.error}</p>;
  if (!ops_) return null;

  const wave = ops_.last_wave;
  const backup = ops_.backup;
  // Failed refreshes first: they need someone to look, an overdue source
  // usually only needs time.
  const stale = staleSources(ops_.sources);
  const failed = stale.filter((row) => row.status === "failed").length;
  const overdue = stale.length - failed;
  const problems: string[] = [];
  if (failed > 0) problems.push(t("ops.attentionFailed", { count: failed }));
  if (overdue > 0) problems.push(t("ops.attentionOverdue", { count: overdue }));

  return (
    <section className="space-y-3" data-testid="ops-card">
      <h2 className="text-lg font-semibold">{t("ops.title")}</h2>
      {stale.length > 0 && (
        <div
          role="alert"
          data-testid="ops-stale-sources"
          className="rounded-[var(--radius)] border border-destructive/40 bg-destructive/10 p-4 text-sm"
        >
          <p className="font-semibold text-destructive">
            {t("ops.attentionTitle")}: {problems.join(", ")}.
          </p>
          <ul className="mt-2 space-y-0.5">
            {stale.map((row) => (
              <li key={`${row.institution_code ?? "shared"}:${row.source}`}>
                <strong>{sourceInfo(row.source).name}</strong>
                {row.institution_code ? ` (${row.institution_code})` : ""}:{" "}
                {t(SOURCE_STATUS_LABELS[row.status])}
                {" · "}
                {t("ops.attentionLast", {
                  date: row.last_success_at
                    ? formatDate(row.last_success_at)
                    : t("ops.freshnessNever"),
                })}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2 rounded-[var(--radius)] border bg-[var(--card)] p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("ops.lastWave")}
          </p>
          {wave ? (
            <>
              <Row label={t("ops.waveWindow")}>
                {formatDateTime(wave.window_start)} → {formatDateTime(wave.window_end)}
              </Row>
              <Row label={t("ops.waveOutcome")}>
                <span className={wave.failed > 0 ? "font-medium text-destructive" : undefined}>
                  {t("ops.waveStageCounts", { stages: wave.stages.length, failed: wave.failed })}
                </span>
              </Row>
              <ul className="space-y-0.5 text-xs text-muted-foreground">
                {wave.stages.map((stage) => (
                  <li key={`${stage.source}/${stage.entity_type}`}>
                    {stage.source}/{stage.entity_type}:{" "}
                    <span className={stage.status === "failed" ? "text-destructive" : undefined}>
                      {stage.status}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">{t("ops.waveNone")}</p>
          )}
          <Link href={`${basePath}/runs`} className="text-sm underline-offset-2 hover:underline">
            {t("ops.waveAllRuns")}
          </Link>
        </div>

        <div className="space-y-2 rounded-[var(--radius)] border bg-[var(--card)] p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("ops.schedules")}
          </p>
          {ops_.schedules.map((schedule) => (
            <Row key={schedule.name} label={t(SCHEDULE_LABELS[schedule.name] ?? schedule.name)}>
              {schedule.next_run_utc ? (
                <>
                  {formatDateTime(schedule.next_run_utc)}{" "}
                  <span className="text-xs text-muted-foreground">
                    ({schedule.cron}
                    {schedule.from_env ? "" : `, ${t("ops.scheduleDefault")}`})
                  </span>
                </>
              ) : (
                <span className="text-destructive">{schedule.error ?? "—"}</span>
              )}
            </Row>
          ))}
          <p className="text-xs text-muted-foreground">{t("ops.schedulesNote")}</p>
          <p className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)] pt-1">
            {t("ops.backup")}
          </p>
          {backup.available ? (
            <Row label={backup.file ?? ""}>
              {formatBytes(backup.size_bytes ?? 0)} · {formatDateTime(backup.modified_at)}
            </Row>
          ) : (
            <p className="text-sm text-muted-foreground">
              {t("ops.backupUnavailable")}
              {backup.detail ? ` (${backup.detail})` : ""}
            </p>
          )}
        </div>
      </div>

      <div className="rounded-[var(--radius)] border bg-[var(--card)] p-4">
        <p className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
          {t("ops.freshness")}
        </p>
        {stale.length === 0 && ops_.sources.length > 0 && (
          <p className="mt-1 text-sm text-muted-foreground">{t("ops.attentionNone")}</p>
        )}
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-xs">
            <caption className="sr-only">{t("ops.freshnessCaption")}</caption>
            <thead>
              <tr className="text-left text-muted-foreground">
                <th scope="col" className="py-1 pr-3 font-medium">
                  {t("ops.freshnessSource")}
                </th>
                <th scope="col" className="py-1 pr-3 font-medium">
                  {t("ops.freshnessInstitution")}
                </th>
                <th scope="col" className="py-1 pr-3 font-medium">
                  {t("ops.freshnessExpected")}
                </th>
                <th scope="col" className="py-1 pr-3 font-medium">
                  {t("ops.freshnessLastSuccess")}
                </th>
                <th scope="col" className="py-1 font-medium">
                  {t("ops.freshnessStatus")}
                </th>
              </tr>
            </thead>
            <tbody>
              {ops_.sources.map((row) => (
                <SourceRow key={`${row.institution_code ?? "shared"}:${row.source}`} row={row} />
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          {t("ops.generatedAt", { at: formatDateTime(ops_.generated_at) })}
        </p>
        <p className="mt-3 text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
          {t("ops.tableTimestamps")}
        </p>
        <div className="mt-2 grid gap-x-8 gap-y-0.5 sm:grid-cols-2 lg:grid-cols-3">
          {Object.entries(ops_.tables).map(([source, at]) => (
            <Row key={source} label={t(`ops.table_${source}`)}>
              {formatDateTime(at)}
            </Row>
          ))}
        </div>
      </div>
    </section>
  );
}
