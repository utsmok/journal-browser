"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAdminResource } from "@/hooks/use-admin-resource";
import { adminPut, type WorkIdentityAdmin } from "@/lib/admin";

/** Matches the backend's WORK_IDENTITY_STATUSES; "all" omits the filter. */
const STATUS_FILTERS = ["candidate", "confirmed", "missing", "all"] as const;
type StatusFilter = (typeof STATUS_FILTERS)[number];

const SELECT_CLASS =
  "h-9 rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]";

function StatusBadge({ status }: { status: WorkIdentityAdmin["status"] }) {
  const variant = status === "confirmed" ? "secondary" : status === "missing" ? "outline" : "muted";
  return <Badge variant={variant}>{status}</Badge>;
}

function rowKey(row: WorkIdentityAdmin): string {
  return `${row.institution_id}:${row.source}:${row.source_pk}`;
}

/**
 * Cross-source work identity review: work_identity rows with per-row
 * status flips. Flips are durable server-side (harvest writes are
 * insert-only) and audited (status_changes); this panel reflects and
 * persists decisions. 'missing' rows are recorded lookup misses, not
 * evidence of a bad link — reopening one as candidate asks the fallback
 * passes to look again.
 */
export function WorkIdentitiesPanel({
  token,
  inst,
  onUnauthorized,
}: {
  token: string;
  /** Optional institution code; omitted lists every institution. */
  inst?: string;
  onUnauthorized: () => void;
}) {
  const [filter, setFilter] = useState<StatusFilter>("candidate");
  const [busy, setBusy] = useState<string | null>(null);
  const instQ = inst ? `&institution=${encodeURIComponent(inst)}` : "";
  const query = `work-identities?limit=500${instQ}${filter === "all" ? "" : `&status=${filter}`}`;
  const { data, setData, loading, error, setError } = useAdminResource<WorkIdentityAdmin[]>(
    query,
    token,
    onUnauthorized,
    "work identities",
  );
  const rows = data ?? [];

  const flip = async (row: WorkIdentityAdmin, status: string) => {
    if (row.status === status) return;
    const key = rowKey(row);
    setBusy(key);
    try {
      const updated = await adminPut<WorkIdentityAdmin>("work-identities", token, {
        institution_id: row.institution_id,
        source: row.source,
        source_pk: row.source_pk,
        status,
      });
      setData((current) => (current ?? []).map((r) => (rowKey(r) === key ? updated : r)));
    } catch (err) {
      setError(`Could not flip ${row.source_pk} (${err instanceof Error ? err.message : err}).`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label htmlFor="work-identity-status-filter" className="whitespace-nowrap">
          Status
        </label>
        <select
          id="work-identity-status-filter"
          title="Which identity statuses to list"
          value={filter}
          onChange={(event) => setFilter(event.target.value as StatusFilter)}
          className={SELECT_CLASS}
        >
          {STATUS_FILTERS.map((value) => (
            <option key={value} value={value}>
              {value === "all" ? "All" : `${value[0].toUpperCase()}${value.slice(1)}`}
            </option>
          ))}
        </select>
        <span className="text-[var(--muted-foreground)]" aria-live="polite">
          {loading ? "loading…" : `${rows.length.toLocaleString("en")} rows`}
        </span>
        {error && <p className="text-sm text-destructive">{error}</p>}
      </div>
      <Table>
        <caption className="sr-only">Work identity resolution rows</caption>
        <TableHeader>
          <TableRow>
            <TableHead>Work</TableHead>
            <TableHead>External id</TableHead>
            <TableHead>Source</TableHead>
            <TableHead>Matched by</TableHead>
            <TableHead>Confidence</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Review</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => {
            const key = rowKey(row);
            return (
              <TableRow key={key}>
                <TableCell className="max-w-72 truncate font-medium" title={row.work_title ?? ""}>
                  {row.work_title ?? <span className="font-mono text-xs">{row.work_id}</span>}
                </TableCell>
                <TableCell className="whitespace-nowrap font-mono text-xs">
                  {row.source_pk}
                </TableCell>
                <TableCell>{row.source}</TableCell>
                <TableCell className="font-mono text-xs">{row.matched_by}</TableCell>
                <TableCell className="tabular-nums">
                  {row.confidence == null ? "—" : row.confidence.toFixed(2)}
                </TableCell>
                <TableCell>
                  <StatusBadge status={row.status} />
                  {row.note && (
                    <Badge variant="muted" className="ml-1" title={row.note}>
                      note
                    </Badge>
                  )}
                </TableCell>
                <TableCell>
                  <div className="flex gap-1">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busy === key || row.status === "confirmed"}
                      onClick={() => void flip(row, "confirmed")}
                    >
                      Confirm
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busy === key || row.status === "candidate"}
                      onClick={() => void flip(row, "candidate")}
                      title="Back to the review queue"
                    >
                      Reopen
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busy === key || row.status === "missing"}
                      onClick={() => void flip(row, "missing")}
                      title="Recorded lookup miss: no evidence, not a bad link"
                    >
                      Miss
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
          {!loading && rows.length === 0 && (
            <TableRow>
              <TableCell colSpan={7} className="text-center text-[var(--muted-foreground)]">
                No {filter === "all" ? "" : `${filter} `}work identity rows for this institution.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}
