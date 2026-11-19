"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

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
import { formatDateTime } from "@/lib/format";
import { useAdminToken, type UsageEventsPage, type UsageSummary } from "@/lib/admin";

const PAGE_SIZE = 50;

const EVENT_TYPES = ["page_view", "search", "error"] as const;
const EVENT_BARS: Record<string, string> = {
  page_view: "bg-slate-400 dark:bg-slate-500",
  search: "bg-orange-400 dark:bg-orange-500",
  error: "bg-red-400 dark:bg-red-500",
};
const EVENT_LABEL_KEYS: Record<(typeof EVENT_TYPES)[number], `usage.event${string}`> = {
  page_view: "usage.eventPageViews",
  search: "usage.eventSearches",
  error: "usage.eventErrors",
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
  const t = useTranslations("admin");
  const max = Math.max(1, ...daily.map((d) => d.page_view + d.search + d.error));
  const labelEvery = Math.ceil(daily.length / 16);
  return (
    <div>
      <div className="flex h-40 items-end gap-1" role="img" aria-label={t("usage.chartAria")}>
        {daily.map((d, i) => {
          const total = d.page_view + d.search + d.error;
          return (
            <div
              key={d.date}
              className="flex h-full flex-1 flex-col items-center justify-end gap-1"
            >
              <div
                className="flex w-full flex-col-reverse overflow-hidden rounded-t"
                style={{ height: `${Math.max((total / max) * 100, total > 0 ? 2 : 0)}%` }}
                title={t("usage.chartDayTitle", { date: d.date, count: total })}
              >
                {EVENT_TYPES.map((type) => {
                  const n = d[type];
                  if (n === 0) return null;
                  return (
                    <div
                      key={type}
                      className={EVENT_BARS[type]}
                      style={{ flexGrow: n, flexBasis: 0 }}
                      title={t("usage.chartSegmentTitle", {
                        date: d.date,
                        label: t(EVENT_LABEL_KEYS[type]),
                        count: n,
                      })}
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
            {t(EVENT_LABEL_KEYS[type])}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Usage analytics: rollup dashboard plus the raw event list, so the owner
 * can see what the anonymous tracker actually records. */
export function UsageSection() {
  const t = useTranslations("admin");
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
      <PageHeader title={t("usage.title")} lede={t("usage.lede")}>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            void summary.refresh();
            void events.refresh();
          }}
        >
          {t("refresh")}
        </Button>
      </PageHeader>

      <div className="flex flex-wrap items-center gap-4 text-sm">
        <div className="flex items-center gap-2">
          <label htmlFor="usage-days">{t("usage.windowLabel")}</label>
          <select
            id="usage-days"
            className="rounded-[var(--radius)] border border-input bg-[var(--card)] px-2 py-1"
            value={days}
            onChange={(event) => changeDays(Number(event.target.value))}
          >
            <option value={7}>{t("usage.days7")}</option>
            <option value={30}>{t("usage.days30")}</option>
            <option value={90}>{t("usage.days90")}</option>
          </select>
        </div>
        <span className="text-muted-foreground" aria-live="polite">
          {summary.loading ? t("loading") : t("usage.windowCount", { days })}
        </span>
      </div>

      {summary.error && <p className="text-sm text-destructive">{summary.error}</p>}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          label={t("usage.eventPageViews")}
          value={totals ? (totals.page_view ?? 0) : null}
        />
        <StatCard
          label={t("usage.eventSearches")}
          value={s ? s.searches.browse + s.searches.queries : null}
          sub={
            s
              ? t("usage.searchesSub", {
                  queries: s.searches.queries.toLocaleString("en"),
                  browse: s.searches.browse.toLocaleString("en"),
                })
              : undefined
          }
        />
        <StatCard label={t("usage.eventErrors")} value={totals ? (totals.error ?? 0) : null} />
        <StatCard label={t("usage.statSessions")} value={s ? s.sessions : null} />
      </div>

      {s && s.daily.length > 0 && <DailyChart daily={s.daily} />}

      {s && (
        <div className="grid gap-6 lg:grid-cols-2">
          <div>
            <h3 className="mb-2 text-sm font-semibold">{t("usage.topPaths")}</h3>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("usage.columnPath")}</TableHead>
                  <TableHead className="text-right">{t("usage.columnViews")}</TableHead>
                  <TableHead className="text-right">{t("usage.columnAvgDwell")}</TableHead>
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
                      {t("usage.noPaths")}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>

          <div>
            <h3 className="mb-2 text-sm font-semibold">{t("usage.topQueries")}</h3>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("usage.columnQuery")}</TableHead>
                  <TableHead className="text-right">{t("usage.columnCount")}</TableHead>
                  <TableHead className="text-right">{t("usage.columnZeroResults")}</TableHead>
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
                      {t("usage.noQueries")}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>

          <div>
            <h3 className="mb-2 text-sm font-semibold">{t("usage.topRefs")}</h3>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("usage.columnRef")}</TableHead>
                  <TableHead className="text-right">{t("usage.columnViews")}</TableHead>
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
                      {t("usage.noRefs")}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>

          <div>
            <h3 className="mb-2 text-sm font-semibold">{t("usage.errorsTitle")}</h3>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("usage.columnMessage")}</TableHead>
                  <TableHead>{t("usage.columnSource")}</TableHead>
                  <TableHead className="text-right">{t("usage.columnCount")}</TableHead>
                  <TableHead>{t("usage.columnLast")}</TableHead>
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
                      {formatDateTime(e.last_ts)}
                    </TableCell>
                  </TableRow>
                ))}
                {s.errors.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={4} className="text-center text-muted-foreground">
                      {t("usage.noErrors")}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>

          <div>
            <h3 className="mb-2 text-sm font-semibold">{t("usage.countriesTitle")}</h3>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("usage.columnCountry")}</TableHead>
                  <TableHead className="text-right">{t("usage.columnEvents")}</TableHead>
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
                      {t("usage.noCountries")}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </div>
      )}

      <div>
        <h3 className="mb-2 text-sm font-semibold">{t("usage.recentEvents")}</h3>
        <div className="mb-2 flex flex-wrap items-center gap-4 text-sm">
          <div className="flex items-center gap-2">
            <label htmlFor="usage-event-type">{t("usage.typeLabel")}</label>
            <select
              id="usage-event-type"
              className="rounded-[var(--radius)] border border-input bg-[var(--card)] px-2 py-1"
              value={eventType}
              onChange={(event) => changeFilter(event.target.value)}
            >
              <option value="all">{t("all")}</option>
              {EVENT_TYPES.map((type) => (
                <option key={type} value={type}>
                  {t(EVENT_LABEL_KEYS[type])}
                </option>
              ))}
            </select>
          </div>
          <span className="text-muted-foreground" aria-live="polite">
            {events.loading
              ? t("loading")
              : total === 0
                ? t("usage.noEvents")
                : t("usage.eventsRange", {
                    from: offset + 1,
                    to: offset + items.length,
                    total: total.toLocaleString("en"),
                  })}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={offset === 0 || events.loading}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              {t("usage.prev")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={offset + PAGE_SIZE >= total || events.loading}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              {t("usage.next")}
            </Button>
          </div>
        </div>

        {events.error && <p className="mb-2 text-sm text-destructive">{events.error}</p>}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("usage.columnWhen")}</TableHead>
              <TableHead>{t("usage.columnType")}</TableHead>
              <TableHead>{t("usage.columnPath")}</TableHead>
              <TableHead>{t("usage.columnQuery")}</TableHead>
              <TableHead>{t("usage.columnRef")}</TableHead>
              <TableHead>{t("usage.columnSourceStatus")}</TableHead>
              <TableHead className="text-right">{t("usage.columnDuration")}</TableHead>
              <TableHead>{t("usage.columnCountry")}</TableHead>
              <TableHead>{t("usage.columnIp")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow key={item.id}>
                <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                  {formatDateTime(item.ts)}
                </TableCell>
                <TableCell className="text-xs">{item.event_type}</TableCell>
                <TableCell className="max-w-56 truncate font-mono text-xs" title={item.path}>
                  {item.path}
                </TableCell>
                <TableCell className="text-xs">
                  {item.event_type === "search" ? (
                    item.is_browse ? (
                      <Badge variant="muted">{t("usage.browseLoad")}</Badge>
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
                  {t("usage.noEventsMatch")}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
