"use client";

import { AdminDrawer } from "@/components/admin/drawer";
import { RecordField, RecordJson } from "@/components/admin/record";
import { useTranslations } from "next-intl";
import { formatDateTime } from "@/lib/format";
import type { StatusChange } from "@/lib/admin";

/** One audited status flip in full: subject key, old/new, note, author. */
export function AuditDrawer({ entry, onClose }: { entry: StatusChange; onClose: () => void }) {
  const t = useTranslations("admin");
  return (
    <AdminDrawer title={t("audit.drawerTitle")} onClose={onClose}>
      <div className="space-y-6">
        <dl className="divide-y">
          <RecordField label={t("audit.when")} value={formatDateTime(entry.changed_at)} />
          <RecordField label={t("audit.surface")} value={entry.table_name} mono />
          <RecordField label={t("audit.field")} value={entry.field} mono />
          <RecordField label={t("audit.oldValue")} value={entry.old_value ?? "∅"} mono />
          <RecordField label={t("audit.newValue")} value={entry.new_value} mono />
          <RecordField label={t("audit.note")} value={entry.note} />
          <RecordField label={t("audit.changedBy")} value={entry.changed_by} />
        </dl>
        <RecordJson label={t("audit.subjectKey")} data={entry.row_key} />
        <RecordJson label={t("audit.entryAsStored")} data={entry} />
      </div>
    </AdminDrawer>
  );
}
