"use client";

import { AdminDrawer } from "@/components/admin/drawer";
import { RecordField, RecordJson } from "@/components/admin/record";
import { formatDateTime } from "@/lib/format";
import type { StatusChange } from "@/lib/admin";

/** One audited status flip in full: subject key, old/new, note, author. */
export function AuditDrawer({ entry, onClose }: { entry: StatusChange; onClose: () => void }) {
  return (
    <AdminDrawer title="Audit entry" onClose={onClose}>
      <div className="space-y-6">
        <dl className="divide-y">
          <RecordField label="When" value={formatDateTime(entry.changed_at)} />
          <RecordField label="Surface" value={entry.table_name} mono />
          <RecordField label="Field" value={entry.field} mono />
          <RecordField label="Old value" value={entry.old_value ?? "∅"} mono />
          <RecordField label="New value" value={entry.new_value} mono />
          <RecordField label="Note" value={entry.note} />
          <RecordField label="Changed by" value={entry.changed_by} />
        </dl>
        <RecordJson label="Subject key (row_key)" data={entry.row_key} />
        <RecordJson label="Entry as stored" data={entry} />
      </div>
    </AdminDrawer>
  );
}
