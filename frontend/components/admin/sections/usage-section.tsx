"use client";

import { useState } from "react";

import { PageHeader } from "@/components/admin/admin-shell";
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
import { useAdminToken, type UsageEventsPage, type UsageSummary } from "@/lib/admin";

const PAGE_SIZE = 50;

const EVENT_TYPES = ["page_view", "search", "error"] as const;
const EVENT_BARS: Record<string, string> = {
  page_view: "bg-slate-400 dark:bg-slate-500",
  search: "bg-orange-400 dark:bg-orange-500",
  error: "bg-red-400 dark:bg-red-500",
};
const EVENT_LABELS: Record<string, string> = {
  page_view: "Page views",
  search: "Searches",
  error: "Errors",
};

function StatCard({ label, value, sub }: { label: string; value: number | null; sub?: string }) {
  return (
    <div className="rounded-[var(--radius)] border bg-[var(--card)] p-4 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
        {label}
      </p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">
        {value === null ? "…" : value.toLocaleString("en")}
      </p>
      {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

/** Hand-rolled stacked per-day event chart (no chart library), StatBars
 * spirit: one column per day, segments stack page views → searches → errors. */
function DailyChart({ daily }: { daily: UsageSummary["daily"] }) {
  const max = Math.max(1, ...daily.map((d) => d.page_view + d.search + d.error));
  const labelEvery = Math.ceil(daily.length / 16);
  return (
    <div>
      <div className="flex h-40 items-end gap-1" role="img" aria-label="Usage events per day">
        {daily.map((d, i) => {
          const t = d.page_view + d.search + d.error;
          return (
            <div
              key={d.date}
              className="flex h-full flex-1 flex-col items-center justify-end gap-1"
            >
              <div
                className="flex w-full flex-col-reverse overflow-hidden rounded-t"
                style={{ height: `${Math.max((t / max) * 100, t > 0 ? 2 : 0)}%` }}
                title={`${d.date}: ${t} events`}
              >
                {EVENT_TYPES.map((type) => {
                  const n = d[type];
                  if (n === 0) return null;
                  return (
                    <div
                      key={type}
                      className={EVENT_BARS[type]}
                      style={{ flexGrow: n, flexBasis: 0 }}
                      title={`${d.date} · ${EVENT_LABELS[type]}: ${n}`}
                    />
                  );
                })}
              </div>
              {i % labelEvery === 0 && (
                <span className="text-[10px] tabular-nums text-muted-foreground">
                  {d.date.slice(5)}
                </span>
              )}
            </div>
          );
        })}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {EVENT_TYPES.map((type) => (
          <li key={type} className="flex items-center gap-1.5">
            <span
              aria-hidden
              className={`inline-block size-2.5 rounded-full ${EVENT_BARS[type]}`}
            />
            {EVENT_LABELS[type]}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Usage analytics: rollup dashboard plus the raw event list, so the owner
 * can see what the anonymous tracker actually records. */
export function UsageSection() {
  const [token, setToken] = useAdminToken();
  const logout = () => setToken(null);
  const [days, setDays] = useState(30);
  const [eventType, setEventType] = useState("all");
  const [offset, setOffset] = useState(0);

  const summary = useAdminResource<UsageSummary>(
    `/usage/summary?days=${days}`,
    token ?? "",
    logout,
    "usage summary",
  );
  const events = useAdminResource<UsageEventsPage>(
    `/usage/events?days=${days}&limit=${PAGE_SIZE}&offset=${offset}${eventType === "all" ? "" : `&event_type=${eventType}`}`,
    token ?? "",
    logout,
    "usage events",
  );

  const changeDays = (d: number) => {
    setDays(d);
    setOffset(0);
  };
  const changeFilter = (v: string) => {
    setEventType(v);
    setOffset(0);
  };

  const s = summary.data;
  const totals = s?.totals;
  const items = events.data?.items ?? [];
  const total = events.data?.total ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Usage"
        lede="Anonymous client activity: page views, searches (real queries vs default browse loads), and errors, with the raw event feed below. Raw IPs are nulled after the retention window."
      >
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            void summary.refresh();
            void events.refresh();
          }}
        >
          Refresh
        </Button>
      </PageHeader>

      <div className="flex flex-wrap items-center gap-4 text-sm">
        <div className="flex items-center gap-2">
          <label htmlFor="usage-days">Window</label>
          <select
            id="usage-days"
            className="rounded-[var(--radius)] border border-input bg-[var(--card)] px-2 py-1"
            value={days}
            onChange={(event) => changeDays(Number(event.target.value))}
          >
            <option value={7}>7 days</option>
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
          </select>
        </div>
        <span className="text-muted-foreground" aria-live="polite">
          {summary.loading ? "loading…" : `${days}-day window`}
        </span>
      </div>

      {summary.error && <p className="text-sm text-destructive">{summary.error}</p>}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Page views" value={totals ? (totals.page_view ?? 0) : null} />
        <StatCard
          label="Searches"
          value={s ? s.searches.browse + s.searches.queries : null}
          sub={
            s
              ? `${s.searches.queries.toLocaleString("en")} queries · ${s.searches.browse.toLocaleString("en")} browse loads`
              : undefined
          }
        />
        <StatCard label="Errors" value={totals ? (totals.error ?? 0) : null} />
        <StatCard label="Sessions" value={s ? s.sessions : null} />
      </div>

      {s && s.daily.length > 0 && <DailyChart daily={s.daily} />}

      {s && (
        <div className="grid gap-6 lg:grid-cols-2">
          <div>
            <h3 className="mb-2 text-sm font-semibold">Top paths</h3>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Path</TableHead>
                  <TableHead className="text-right">Views</TableHead>
                  <TableHead className="text-right">Avg dwell</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {s.top_paths.map((p) => (
                  <TableRow key={p.path}>
                    <TableCell className="max-w-72 truncate font-mono text-xs" title={p.path}>
                      {p.path}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {p.page_views.toLocaleString("en")}
                    </TableCell>
                    <TableCell className="text-right tabular-nums text-muted-foreground">
                      {p.avg_duration_ms === null
                        ? "—"
                        : `${(p.avg_duration_ms / 1000).toFixed(1)}s`}
                    </TableCell>
                  </TableRow>
                ))}
                {s.top_paths.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={3} className="text-center text-muted-foreground">
                      No page views in this window.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>

          <div>
            <h3 className="mb-2 text-sm font-semibold">Top queries</h3>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Query</TableHead>
                  <TableHead className="text-right">Count</TableHead>
                  <TableHead className="text-right">Zero results</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {s.top_queries.map((q) => (
                  <TableRow key={q.query}>
                    <TableCell className="max-w-72 truncate" title={q.query}>
                      {q.query}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {q.count.toLocaleString("en")}
                    </TableCell>
                    <TableCell className="text-right tabular-nums text-muted-foreground">
                      {Math.round(q.zero_share * 100)}%
                    </TableCell>
                  </TableRow>
                ))}
                {s.top_queries.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={3} className="text-center text-muted-foreground">
                      No search queries in this window.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>

          <div>
            <h3 className="mb-2 text-sm font-semibold">Top refs</h3>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Ref</TableHead>
                  <TableHead className="text-right">Views</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {s.top_refs.map((r) => (
                  <TableRow key={`${r.ref_type}:${r.ref_id}`}>
                    <TableCell className="font-mono text-xs">
                      {r.ref_type}:{r.ref_id}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {r.count.toLocaleString("en")}
                    </TableCell>
                  </TableRow>
                ))}
                {s.top_refs.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={2} className="text-center text-muted-foreground">
                      No ref-tracked views in this window.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>

          <div>
            <h3 className="mb-2 text-sm font-semibold">Errors</h3>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Message</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead className="text-right">Count</TableHead>
                  <TableHead>Last</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {s.errors.map((e, i) => (
                  <TableRow key={i}>
                    <TableCell className="max-w-64 truncate text-xs" title={e.message ?? ""}>
                      {e.status ? `${e.status} · ` : ""}
                      {e.message ?? "—"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{e.source}</TableCell>
                    <TableCell className="text-right tabular-nums">{e.count}</TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                      {new Date(e.last_ts).toLocaleString()}
                    </TableCell>
                  </TableRow>
                ))}
                {s.errors.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={4} className="text-center text-muted-foreground">
                      No client errors in this window.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>

          <div>
            <h3 className="mb-2 text-sm font-semibold">Countries</h3>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Country</TableHead>
                  <TableHead className="text-right">Events</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {s.countries.map((c) => (
                  <TableRow key={c.country}>
                    <TableCell>{c.country}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {c.count.toLocaleString("en")}
                    </TableCell>
                  </TableRow>
                ))}
                {s.countries.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={2} className="text-center text-muted-foreground">
                      No geo-enriched events in this window.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </div>
      )}

      <div>
        <h3 className="mb-2 text-sm font-semibold">Recent events</h3>
        <div className="mb-2 flex flex-wrap items-center gap-4 text-sm">
          <div className="flex items-center gap-2">
            <label htmlFor="usage-event-type">Type</label>
            <select
              id="usage-event-type"
              className="rounded-[var(--radius)] border border-input bg-[var(--card)] px-2 py-1"
              value={eventType}
              onChange={(event) => changeFilter(event.target.value)}
            >
              <option value="all">All</option>
              {EVENT_TYPES.map((type) => (
                <option key={type} value={type}>
                  {EVENT_LABELS[type]}
                </option>
              ))}
            </select>
          </div>
          <span className="text-muted-foreground" aria-live="polite">
            {events.loading
              ? "loading…"
              : total === 0
                ? "no events"
                : `${offset + 1}–${offset + items.length} of ${total.toLocaleString("en")}`}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={offset === 0 || events.loading}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Prev
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={offset + PAGE_SIZE >= total || events.loading}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Next
            </Button>
          </div>
        </div>

        {events.error && <p className="mb-2 text-sm text-destructive">{events.error}</p>}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>When</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Path</TableHead>
              <TableHead>Query</TableHead>
              <TableHead>Ref</TableHead>
              <TableHead>Source / status</TableHead>
              <TableHead className="text-right">Duration</TableHead>
              <TableHead>Country</TableHead>
              <TableHead>IP</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow key={item.id}>
                <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                  {new Date(item.ts).toLocaleString()}
                </TableCell>
                <TableCell className="text-xs">{item.event_type}</TableCell>
                <TableCell className="max-w-56 truncate font-mono text-xs" title={item.path}>
                  {item.path}
                </TableCell>
                <TableCell className="text-xs">
                  {item.event_type === "search" ? (
                    item.is_browse ? (
                      <Badge variant="muted">browse load</Badge>
                    ) : (
                      (item.query ?? "—")
                    )
                  ) : (
                    "—"
                  )}
                </TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">
                  {item.ref_type ? `${item.ref_type}:${item.ref_id}` : "—"}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {item.event_type === "error"
                    ? `${item.source ?? "—"}${item.status ? ` · ${item.status}` : ""}`
                    : "—"}
                </TableCell>
                <TableCell className="text-right tabular-nums text-xs text-muted-foreground">
                  {item.duration_ms === null ? "—" : `${(item.duration_ms / 1000).toFixed(1)}s`}
                </TableCell>
                <TableCell className="text-xs">{item.country ?? "—"}</TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">
                  {item.ip ?? "—"}
                </TableCell>
              </TableRow>
            ))}
            {!events.loading && items.length === 0 && (
              <TableRow>
                <TableCell colSpan={9} className="text-center text-muted-foreground">
                  No events match this window and type.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
