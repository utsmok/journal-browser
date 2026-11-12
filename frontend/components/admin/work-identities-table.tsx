"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { WorkIdentityDrawer } from "@/components/admin/work-identity-drawer";
import { CardPager } from "@/components/card-pager";
import { useReviewer } from "@/components/admin/record";
import { Badge } from "@/components/ui/badge";
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
import { adminPut, type WorkIdentityAdmin, type WorkIdentityPage } from "@/lib/admin";

/** Matches the backend's WORK_IDENTITY_STATUSES; "all" omits the filter. */
const STATUS_FILTERS = ["candidate", "confirmed", "missing", "all"] as const;
type StatusFilter = (typeof STATUS_FILTERS)[number];

const FILTER_LABEL_KEYS: Record<
  StatusFilter,
  `workIdentities.status${string}` | "workIdentities.all"
> = {
  candidate: "workIdentities.statusCandidate",
  confirmed: "workIdentities.statusConfirmed",
  missing: "workIdentities.statusMissing",
  all: "workIdentities.all",
};

/** Lowercase status word for the empty-state sentence. */
const EMPTY_STATUS_WORDS: Record<Exclude<StatusFilter, "all">, string> = {
  candidate: "candidate",
  confirmed: "confirmed",
  missing: "missing",
};

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
  const t = useTranslations("admin");
  const [filter, setFilter] = useState<StatusFilter>("candidate");
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState<string | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [reviewer, setReviewer] = useReviewer();
  // The institution prop changes the query outside this panel; without a
  // reset a stale page can land past the new total and read as "no rows".
  useEffect(() => setPage(1), [inst]);
  const instQ = inst ? `&institution=${encodeURIComponent(inst)}` : "";
  const query = `/work-identities?limit=50&offset=${(page - 1) * 50}${instQ}${filter === "all" ? "" : `&status=${filter}`}`;
  const { data, setData, loading, error, setError } = useAdminResource<WorkIdentityPage>(
    query,
    token,
    onUnauthorized,
    "work identities",
  );
  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / 50));
  const selected = items.find((row) => rowKey(row) === selectedKey) ?? null;

  const flip = async (
    row: WorkIdentityAdmin,
    status: string,
    note = "",
    changedBy = "",
  ): Promise<void> => {
    if (row.status === status) return;
    const key = rowKey(row);
    setBusy(key);
    try {
      const updated = await adminPut<WorkIdentityAdmin>("/work-identities", token, {
        institution_id: row.institution_id,
        source: row.source,
        source_pk: row.source_pk,
        status,
        ...(changedBy ? { changed_by: changedBy } : {}),
        ...(note ? { note } : {}),
      });
      setData((current) =>
        current
          ? { ...current, items: current.items.map((r) => (rowKey(r) === key ? updated : r)) }
          : current,
      );
    } catch (err) {
      setError(
        t("workIdentities.flipFailed", {
          id: row.source_pk,
          message: err instanceof Error ? err.message : String(err),
        }),
      );
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label htmlFor="work-identity-status-filter" className="whitespace-nowrap">
          {t("workIdentities.statusLabel")}
        </label>
        <select
          id="work-identity-status-filter"
          title={t("workIdentities.statusFilterTitle")}
          value={filter}
          onChange={(event) => {
            setFilter(event.target.value as StatusFilter);
            setPage(1);
          }}
          className={SELECT_CLASS}
        >
          {STATUS_FILTERS.map((value) => (
            <option key={value} value={value}>
              {t(FILTER_LABEL_KEYS[value])}
            </option>
          ))}
        </select>
        <label htmlFor="work-identity-reviewer" className="whitespace-nowrap text-muted-foreground">
          {t("workIdentities.reviewer")}
        </label>
        <Input
          id="work-identity-reviewer"
          placeholder={t("workIdentities.reviewerPlaceholder")}
          value={reviewer}
          onChange={(event) => setReviewer(event.target.value)}
          className="h-9 w-56"
        />
        <span className="text-[var(--muted-foreground)]" aria-live="polite">
          {loading ? t("loading") : t("workIdentities.rowsCount", { count: total })}
        </span>
        {error && <p className="text-sm text-destructive">{error}</p>}
      </div>
      <Table>
        <caption className="sr-only">{t("workIdentities.caption")}</caption>
        <TableHeader>
          <TableRow>
            <TableHead>{t("workIdentities.columnWork")}</TableHead>
            <TableHead>{t("workIdentities.columnExternalId")}</TableHead>
            <TableHead>{t("workIdentities.columnSource")}</TableHead>
            {!inst && <TableHead>{t("workIdentities.columnInstitution")}</TableHead>}
            <TableHead>{t("workIdentities.columnMatchedBy")}</TableHead>
            <TableHead>{t("workIdentities.columnConfidence")}</TableHead>
            <TableHead>{t("workIdentities.columnStatus")}</TableHead>
            <TableHead>{t("workIdentities.columnReview")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((row) => {
            const key = rowKey(row);
            return (
              <TableRow
                key={key}
                className="cursor-pointer"
                title={t("workIdentities.rowTitle")}
                onClick={() => setSelectedKey(key)}
              >
                <TableCell className="max-w-72 truncate font-medium" title={row.work_title ?? ""}>
                  {row.work_title ?? <span className="font-mono text-xs">{row.work_id}</span>}
                </TableCell>
                <TableCell className="whitespace-nowrap font-mono text-xs">
                  {row.source_pk}
                </TableCell>
                <TableCell>{row.source}</TableCell>
                {!inst && <TableCell>{row.institution_code ?? "—"}</TableCell>}
                <TableCell className="font-mono text-xs">{row.matched_by}</TableCell>
                <TableCell className="tabular-nums">
                  {row.confidence == null ? "—" : row.confidence.toFixed(2)}
                </TableCell>
                <TableCell>
                  <StatusBadge status={row.status} />
                  {row.note && (
                    <Badge variant="muted" className="ml-1" title={row.note}>
                      {t("workIdentities.noteBadge")}
                    </Badge>
                  )}
                </TableCell>
                <TableCell>
                  <div className="flex gap-1">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busy === key || row.status === "confirmed"}
                      onClick={(event) => {
                        event.stopPropagation();
                        void flip(row, "confirmed");
                      }}
                    >
                      {t("workIdentities.confirm")}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busy === key || row.status === "candidate"}
                      onClick={(event) => {
                        event.stopPropagation();
                        void flip(row, "candidate");
                      }}
                      title={t("workIdentities.reopenTitle")}
                    >
                      {t("workIdentities.reopen")}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busy === key || row.status === "missing"}
                      onClick={(event) => {
                        event.stopPropagation();
                        void flip(row, "missing");
                      }}
                      title={t("workIdentities.missTitle")}
                    >
                      {t("workIdentities.miss")}
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
          {!loading && items.length === 0 && (
            <TableRow>
              <TableCell
                colSpan={inst ? 7 : 8}
                className="text-center text-[var(--muted-foreground)]"
              >
                {filter === "all"
                  ? t(inst ? "workIdentities.emptyAllInst" : "workIdentities.emptyAll")
                  : t(inst ? "workIdentities.emptyStatusInst" : "workIdentities.emptyStatus", {
                      status: EMPTY_STATUS_WORDS[filter],
                    })}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      {pages > 1 && (
        <CardPager
          page={page}
          pages={pages}
          total={total}
          onPage={setPage}
          label={t("workIdentities.pagerRows")}
        />
      )}
      {selected && (
        <WorkIdentityDrawer
          key={rowKey(selected)}
          row={selected}
          busy={busy}
          onClose={() => setSelectedKey(null)}
          onFlip={(row, status, note, changedBy) => void flip(row, status, note, changedBy)}
        />
      )}
    </div>
  );
}
