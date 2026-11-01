"use client";

import { useMemo, useState } from "react";

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
import { useAdminToken, type StatusChange } from "@/lib/admin";

/** Audit ledger: every audited admin status flip, filterable by surface. */
export function AuditSection() {
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
      <PageHeader
        title="Audit log"
        lede="Every audited admin status flip, newest first. Click an entry for the full record; the API keeps the complete history."
      >
        <Button variant="outline" size="sm" onClick={() => void changes.refresh()}>
          Refresh
        </Button>
      </PageHeader>

      <div className="flex flex-wrap items-center gap-4 text-sm">
        <div className="flex items-center gap-2">
          <label htmlFor="audit-surface">Surface</label>
          <select
            id="audit-surface"
            className="rounded-[var(--radius)] border border-input bg-[var(--card)] px-2 py-1"
            value={surface}
            onChange={(event) => setSurface(event.target.value)}
          >
            <option value="all">All</option>
            {surfaces.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>
        <Input
          aria-label="Search audit entries"
          placeholder="Search note, value, subject…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="w-72"
        />
        <span className="text-muted-foreground" aria-live="polite">
          {changes.loading ? "loading…" : `${rows.length.toLocaleString("en")} entries`}
        </span>
      </div>

      {changes.error && <p className="text-sm text-destructive">{changes.error}</p>}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>When</TableHead>
            <TableHead>Surface</TableHead>
            <TableHead>Change</TableHead>
            <TableHead>Subject</TableHead>
            <TableHead>Note</TableHead>
            <TableHead>By</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((change) => (
            <TableRow
              key={change.id}
              className="cursor-pointer"
              title="Click for the full audit entry"
              onClick={() => setSelected(change)}
            >
              <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                {new Date(change.changed_at).toLocaleString()}
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
                {JSON.stringify(change.row_key)}
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
                No audit entries match. Flips made in the identity and work-identity queues land
                here.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      {selected && <AuditDrawer entry={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
