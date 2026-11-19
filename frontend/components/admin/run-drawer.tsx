"use client";

import { AdminDrawer } from "@/components/admin/drawer";
import { RecordField, RecordJson } from "@/components/admin/record";
import { StatusBadge } from "@/components/admin/runs-table";
import { useTranslations } from "next-intl";
import type { AdminRun } from "@/lib/admin";

/** Full harvest-run detail: timing, identity, and the stats payload. */
export function RunDrawer({ run, onClose }: { run: AdminRun; onClose: () => void }) {
  const t = useTranslations("admin");
  const duration =
    run.started_at && run.finished_at
      ? `${Math.round((new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000)}s`
      : null;
  return (
    <AdminDrawer
      title={t("runs.drawerTitle", {
        id: run.id,
        source: `${run.source}/${run.entity_type}`,
      })}
      onClose={onClose}
    >
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <StatusBadge status={run.status} />
        </div>
        <dl className="divide-y">
          <RecordField label={t("runs.drawerRunId")} value={run.id} mono />
          <RecordField label={t("runs.drawerSource")} value={run.source} mono />
          <RecordField label={t("runs.drawerEntityType")} value={run.entity_type} mono />
          <RecordField
            label={t("runs.drawerInstitution")}
            value={run.institution_code ?? t("runs.shared")}
          />
          <RecordField label={t("runs.drawerStarted")} value={run.started_at} />
          <RecordField label={t("runs.drawerFinished")} value={run.finished_at} />
          <RecordField label={t("runs.drawerDuration")} value={duration} />
        </dl>
        {typeof run.stats === "object" && run.stats !== null && (
          <RecordJson label={t("runs.drawerStats")} data={run.stats} />
        )}
      </div>
    </AdminDrawer>
  );
}
