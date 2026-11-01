"use client";

import { AdminDrawer } from "@/components/admin/drawer";
import { RecordField, RecordJson } from "@/components/admin/record";
import { StatusBadge } from "@/components/admin/runs-table";
import type { AdminRun } from "@/lib/admin";

/** Full harvest-run detail: timing, identity, and the stats payload. */
export function RunDrawer({ run, onClose }: { run: AdminRun; onClose: () => void }) {
  const duration =
    run.started_at && run.finished_at
      ? `${Math.round((new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000)}s`
      : null;
  return (
    <AdminDrawer
      title={`Harvest run #${run.id} — ${run.source}/${run.entity_type}`}
      onClose={onClose}
    >
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <StatusBadge status={run.status} />
        </div>
        <dl className="divide-y">
          <RecordField label="Run id" value={run.id} mono />
          <RecordField label="Source" value={run.source} mono />
          <RecordField label="Entity type" value={run.entity_type} mono />
          <RecordField label="Institution" value={run.institution_code ?? "shared"} />
          <RecordField label="Started" value={run.started_at} />
          <RecordField label="Finished" value={run.finished_at} />
          <RecordField label="Duration" value={duration} />
        </dl>
        {typeof run.stats === "object" && run.stats !== null && (
          <RecordJson label="Stats payload" data={run.stats} />
        )}
      </div>
    </AdminDrawer>
  );
}
