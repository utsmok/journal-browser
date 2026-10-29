"use client";

import { Fragment, useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  AdminError,
  adminDelete,
  adminGet,
  adminPatch,
  type FeedbackAdmin,
} from "@/lib/admin";

const STATUSES = ["todo", "in_progress", "done", "wontfix"] as const;
const PRIORITIES = ["low", "normal", "high", "critical"] as const;

function FeedbackDetail({
  item,
  token,
  onUnauthorized,
  onChanged,
}: {
  item: FeedbackAdmin;
  token: string;
  onUnauthorized: (token: string | null) => void;
  onChanged: () => void;
}) {
  const [notes, setNotes] = useState(item.resolution_notes ?? "");
  const [error, setError] = useState<string | null>(null);
  // page_data is the widget's own buildPageDump output; the contract types it
  // as a free-form object, so the two read sites narrow it here.
  const pageData = item.page_data as
    | { url?: string; queries?: unknown[] }
    | undefined;

  async function run(fn: () => Promise<unknown>) {
    try {
      await fn();
      setError(null);
      onChanged();
    } catch (err) {
      if (err instanceof AdminError && err.status === 401) {
        onUnauthorized(null);
        return;
      }
      setError(`Update failed (${err instanceof Error ? err.message : err}).`);
    }
  }

  return (
    <TableRow>
      <TableCell colSpan={5}>
        <div className="space-y-3 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--muted)] p-3">
          <p className="whitespace-pre-wrap text-sm">{item.description}</p>
          {item.page_url && (
            <p className="text-xs text-[var(--muted-foreground)]">
              Page: <span className="font-mono">{item.page_url}</span>
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <textarea
              className="min-h-16 flex-1 rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-3 py-2 text-sm"
              placeholder="Resolution notes…"
              value={notes}
              maxLength={8000}
              onChange={(e) => setNotes(e.target.value)}
            />
            <Button
              size="sm"
              onClick={() => run(() => adminPatch(`/feedback/${item.id}`, token, { resolution_notes: notes }))}
            >
              Save notes
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                if (confirm("Delete this feedback report?")) {
                  void run(() => adminDelete(`/feedback/${item.id}`, token));
                }
              }}
            >
              Delete
            </Button>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          {pageData && (
            <details>
              <summary className="cursor-pointer text-xs text-[var(--muted-foreground)]">
                Page data ({pageData.queries?.length ?? 0} cached responses)
                {pageData.url ? ` — ${pageData.url}` : ""}
              </summary>
              <pre className="mt-2 max-h-72 overflow-auto rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-2 text-xs">
                {JSON.stringify(item.page_data, null, 2)}
              </pre>
            </details>
          )}
        </div>
      </TableCell>
    </TableRow>
  );
}

/** Admin triage for user feedback: filter by status, patch inline, expand for
 * details and the page-data dump. */
export function FeedbackSection({
  token,
  onUnauthorized,
}: {
  token: string;
  onUnauthorized: (token: string | null) => void;
}) {
  const [items, setItems] = useState<FeedbackAdmin[]>([]);
  const [filter, setFilter] = useState<string>("all");
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const q = filter === "all" ? "" : `?status=${encodeURIComponent(filter)}`;
      setItems(await adminGet<FeedbackAdmin[]>(`/feedback${q}`, token));
      setError(null);
    } catch (err) {
      if (err instanceof AdminError && err.status === 401) {
        onUnauthorized(null);
        return;
      }
      setError(`Could not load feedback (${err instanceof Error ? err.message : err}).`);
    }
  }, [token, filter, onUnauthorized]);

  useEffect(() => {
    void load();
  }, [load]);

  async function patch(id: number, body: Record<string, string>) {
    try {
      await adminPatch(`/feedback/${id}`, token, body);
      await load();
    } catch (err) {
      if (err instanceof AdminError && err.status === 401) {
        onUnauthorized(null);
        return;
      }
      setError(`Update failed (${err instanceof Error ? err.message : err}).`);
    }
  }

  const selectCls = "rounded-[var(--radius)] border border-input bg-[var(--card)] px-2 py-1 text-xs";

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Feedback ({items.length})</h2>
        <div className="flex items-center gap-2 text-sm">
          <label htmlFor="feedback-filter" className="text-muted-foreground">
            Status
          </label>
          <select
            id="feedback-filter"
            className={selectCls}
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value);
              setOpenId(null);
            }}
          >
            <option value="all">All</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s.replace("_", " ")}
              </option>
            ))}
          </select>
        </div>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Received</TableHead>
            <TableHead>Title</TableHead>
            <TableHead>Category</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Priority</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => (
            <Fragment key={item.id}>
              <TableRow
                className="cursor-pointer"
                title="Click to open this report"
                onClick={() => setOpenId(openId === item.id ? null : item.id)}
              >
                <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                  {new Date(item.created_at).toLocaleString()}
                </TableCell>
                <TableCell className="max-w-xs truncate font-medium" title={item.title}>
                  {item.title}
                </TableCell>
                <TableCell className="text-xs">{item.category ?? "—"}</TableCell>
                <TableCell onClick={(e) => e.stopPropagation()}>
                  <select
                    className={selectCls}
                    value={item.status}
                    onChange={(e) => void patch(item.id, { status: e.target.value })}
                    aria-label={`Status of: ${item.title}`}
                  >
                    {STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {s.replace("_", " ")}
                      </option>
                    ))}
                  </select>
                </TableCell>
                <TableCell onClick={(e) => e.stopPropagation()}>
                  <select
                    className={selectCls}
                    value={item.priority}
                    onChange={(e) => void patch(item.id, { priority: e.target.value })}
                    aria-label={`Priority of: ${item.title}`}
                  >
                    {PRIORITIES.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                </TableCell>
              </TableRow>
              {openId === item.id && (
                <FeedbackDetail
                  key={`detail-${item.id}`}
                  item={item}
                  token={token}
                  onUnauthorized={onUnauthorized}
                  onChanged={load}
                />
              )}
            </Fragment>
          ))}
        </TableBody>
      </Table>
    </section>
  );
}
