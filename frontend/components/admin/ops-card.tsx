"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { useAdminResource } from "@/hooks/use-admin-resource";
import { formatDateTime } from "@/lib/format";
import type { components } from "@/lib/api-types";
import { useAdminToken } from "@/lib/admin";

type AdminOpsStatus = components["schemas"]["AdminOpsStatusOut"];

const SCHEDULE_LABELS: Record<string, string> = {
  refresh_wave: "ops.scheduleRefreshWave",
  source_wave: "ops.scheduleSourceWave",
  backup: "ops.scheduleBackup",
};

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

/** Operations card for the admin overview: the nightly wave outcome, the
 * scheduled jobs, the newest backup, and per-source data freshness. The
 * endpoint is read-only by design — there is no "run now" trigger. */
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

  return (
    <section className="space-y-3" data-testid="ops-card">
      <h2 className="text-lg font-semibold">{t("ops.title")}</h2>
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
        <div className="mt-2 grid gap-x-8 gap-y-0.5 sm:grid-cols-2 lg:grid-cols-3">
          {Object.entries(ops_.tables).map(([source, at]) => (
            <Row key={source} label={t(`ops.table_${source}`)}>
              {formatDateTime(at)}
            </Row>
          ))}
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          {t("ops.generatedAt", { at: formatDateTime(ops_.generated_at) })}
        </p>
      </div>
    </section>
  );
}
