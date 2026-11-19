"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/admin/admin-shell";
import { AuditDrawer } from "@/components/admin/audit-drawer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
import { useAdminToken, type StatusChange } from "@/lib/admin";

/** Compact row-key copy ("openalex · A501234…"); the full JSON is one
 * hover away in the title attribute and the drawer. */
function subjectSummary(rowKey: StatusChange["row_key"]): string {
  const values = Object.values(rowKey ?? {})
    .filter((v): v is string | number => typeof v === "string" || typeof v === "number")
    .slice(0, 3);
  return values.length > 0 ? values.join(" · ") : "—";
}

/** Audit ledger: every audited admin status flip, filterable by surface. */
export function AuditSection() {
  const t = useTranslations("admin");
  const [token, setToken] = useAdminToken();
  const logout = () => setToken(null);
  const [surface, setSurface] = useState("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<StatusChange | null>(null);

  const changes = useAdminResource<StatusChange[]>(
    "/status-changes?limit=500",
    token ?? "",
    logout,
    "audit log",
  );

  const surfaces = useMemo(
    () => Array.from(new Set((changes.data ?? []).map((change) => change.table_name))).sort(),
    [changes.data],
  );
  const q = query.trim().toLowerCase();
  const rows = (changes.data ?? []).filter((change) => {
    if (surface !== "all" && change.table_name !== surface) return false;
    if (q === "") return true;
    const hay = [
      change.note ?? "",
      change.changed_by ?? "",
      change.old_value ?? "",
      change.new_value,
      JSON.stringify(change.row_key),
    ]
      .join(" ")
      .toLowerCase();
    return hay.includes(q);
  });

  return (
    <div className="space-y-6">
      <PageHeader title={t("audit.title")} lede={t("audit.lede")}>
        <Button variant="outline" size="sm" onClick={() => void changes.refresh()}>
          {t("refresh")}
        </Button>
      </PageHeader>

      <div className="flex flex-wrap items-center gap-4 text-sm">
        <div className="flex items-center gap-2">
          <label htmlFor="audit-surface">{t("audit.surfaceLabel")}</label>
          <select
            id="audit-surface"
            className="rounded-[var(--radius)] border border-input bg-[var(--card)] px-2 py-1"
            value={surface}
            onChange={(event) => setSurface(event.target.value)}
          >
            <option value="all">{t("all")}</option>
            {surfaces.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>
        <Input
          aria-label={t("audit.searchAria")}
          placeholder={t("audit.searchPlaceholder")}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="w-72"
        />
        <span className="text-muted-foreground" aria-live="polite">
          {changes.loading ? t("loading") : t("audit.entriesCount", { count: rows.length })}
        </span>
      </div>

      {changes.error && <p className="text-sm text-destructive">{changes.error}</p>}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("audit.columnWhen")}</TableHead>
            <TableHead>{t("audit.columnSurface")}</TableHead>
            <TableHead>{t("audit.columnChange")}</TableHead>
            <TableHead>{t("audit.columnSubject")}</TableHead>
            <TableHead>{t("audit.columnNote")}</TableHead>
            <TableHead>{t("audit.columnBy")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((change) => (
            <TableRow
              key={change.id}
              className="cursor-pointer"
              title={t("audit.rowTitle")}
              onClick={() => setSelected(change)}
            >
              <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                {formatDateTime(change.changed_at)}
              </TableCell>
              <TableCell className="text-xs">
                {change.table_name}
                {change.field !== "status" ? ` · ${change.field}` : ""}
              </TableCell>
              <TableCell className="whitespace-nowrap text-xs">
                {change.old_value ?? "∅"} → {change.new_value}
              </TableCell>
              <TableCell
                className="max-w-56 truncate font-mono text-xs"
                title={JSON.stringify(change.row_key)}
              >
                {subjectSummary(change.row_key)}
              </TableCell>
              <TableCell className="max-w-64 truncate text-xs" title={change.note ?? ""}>
                {change.note ?? "—"}
              </TableCell>
              <TableCell className="text-xs">{change.changed_by ?? "—"}</TableCell>
            </TableRow>
          ))}
          {!changes.loading && rows.length === 0 && (
            <TableRow>
              <TableCell colSpan={6} className="text-center text-muted-foreground">
                {t("audit.empty")}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      {selected && <AuditDrawer entry={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
