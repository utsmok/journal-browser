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
import { adminPut, type AuthorIdentityAdmin } from "@/lib/admin";

/** Matches the backend's IDENTITY_STATUSES; "all" omits the filter param. */
const STATUS_FILTERS = ["candidate", "confirmed", "rejected", "all"] as const;
type StatusFilter = (typeof STATUS_FILTERS)[number];

const SELECT_CLASS =
  "h-9 rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]";

function StatusBadge({ status }: { status: AuthorIdentityAdmin["status"] }) {
  const variant =
    status === "confirmed" ? "secondary" : status === "rejected" ? "outline" : "muted";
  return <Badge variant={variant}>{status}</Badge>;
}

function rowKey(row: AuthorIdentityAdmin): string {
  return `${row.institution_id}:${row.author_pure_uuid}:${row.source}:${row.external_id}`;
}

/**
 * Identity-cascade review: the resolution rows with per-row status flips.
 * A flip is sticky server-side and reaches authors.openalex_ids at the
 * next authors ingest; the panel just reflects and persists decisions.
 * Every actual flip is audited server-side (status_changes).
 */
export function IdentitiesPanel({
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
  const query = `author-identities?limit=500${instQ}${filter === "all" ? "" : `&status=${filter}`}`;
  const { data, setData, loading, error, setError } = useAdminResource<AuthorIdentityAdmin[]>(
    query,
    token,
    onUnauthorized,
    "identities",
  );
  const rows = data ?? [];

  const flip = async (row: AuthorIdentityAdmin, status: string) => {
    if (row.status === status) return;
    const key = rowKey(row);
    setBusy(key);
    try {
      const updated = await adminPut<AuthorIdentityAdmin>("author-identities", token, {
        institution_id: row.institution_id,
        author_pure_uuid: row.author_pure_uuid,
        source: row.source,
        external_id: row.external_id,
        status,
      });
      // Replace from the server response; the flip is audited and sticky
      // there, so the row we show must be the stored one.
      setData((current) => (current ?? []).map((r) => (rowKey(r) === key ? updated : r)));
    } catch (err) {
      setError(`Could not flip ${row.external_id} (${err instanceof Error ? err.message : err}).`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label htmlFor="identity-status-filter" className="whitespace-nowrap">
          Status
        </label>
        <select
          id="identity-status-filter"
          title="Which resolution statuses to list"
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
        <caption className="sr-only">Author identity resolution rows</caption>
        <TableHeader>
          <TableRow>
            <TableHead>Author</TableHead>
            <TableHead>External id</TableHead>
            <TableHead>Source</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Method</TableHead>
            <TableHead className="text-right">Works</TableHead>
            <TableHead>Evidence</TableHead>
            <TableHead>Review</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => {
            const key = rowKey(row);
            return (
              <TableRow key={key}>
                <TableCell className="font-medium">
                  {row.author_name ?? (
                    <span className="font-mono text-xs">{row.author_pure_uuid}</span>
                  )}
                </TableCell>
                <TableCell className="whitespace-nowrap font-mono text-xs">
                  {row.source === "openalex" ? (
                    <a
                      href={`https://openalex.org/${row.external_id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                    >
                      {row.external_id}
                    </a>
                  ) : (
                    row.external_id
                  )}
                </TableCell>
                <TableCell>{row.source}</TableCell>
                <TableCell>
                  <StatusBadge status={row.status} />
                  {row.orcid_corroborated && (
                    <Badge
                      variant="muted"
                      className="ml-1"
                      title="An ORCID iD on the matched profile corroborates this binding"
                    >
                      orcid
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="text-xs">{row.method ?? "—"}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {row.n_works.toLocaleString("en")}
                </TableCell>
                <TableCell
                  className="max-w-64 truncate font-mono text-xs"
                  title={JSON.stringify(row.evidence)}
                >
                  {JSON.stringify(row.evidence)}
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
                      disabled={busy === key || row.status === "rejected"}
                      onClick={() => void flip(row, "rejected")}
                    >
                      Reject
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
          {!loading && rows.length === 0 && (
            <TableRow>
              <TableCell colSpan={8} className="text-center text-[var(--muted-foreground)]">
                No {filter === "all" ? "" : `${filter} `}identity rows for this institution.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}
