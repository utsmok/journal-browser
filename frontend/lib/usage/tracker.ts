/**
 * Anonymous usage-event tracker: batches client activity and ships it to
 * POST /api/v1/usage/events (same-origin /api proxy). No cookies — one
 * localStorage session id (jb_usage_sid) that rotates after 30 idle
 * minutes. Skipped entirely under automation (navigator.webdriver) and
 * on the server; payloads are never logged.
 */

import { refForPath, type UsageRefType } from "./refs";

export type UsageScope = "journals" | "funders" | "authors" | "publishers" | "orgunits";

/** Hand-written to match the wire contract; do not import api-types here. */
type UsageEvent = {
  type: "page_view" | "search" | "error";
  session_id: string;
  path: string;
  duration_ms?: number;
  query?: string;
  is_browse?: boolean;
  results_count?: number;
  search_scope?: UsageScope;
  filters?: Record<string, unknown>;
  ref_type?: UsageRefType;
  ref_id?: string;
  referrer?: string;
  source?: "js_error" | "unhandled_rejection" | "api_status";
  message?: string;
  detail?: string;
  status?: number;
};

const ENDPOINT = "/api/v1/usage/events";
const SID_KEY = "jb_usage_sid";
const FLUSH_AT = 20;
const FLUSH_MS = 10_000;
const IDLE_MS = 30 * 60_000;
const DEDUP_MS = 30_000;

type SessionRecord = { sid: string; lastSeen: number; sent?: number };

let queue: UsageEvent[] = [];
let timer: ReturnType<typeof setInterval> | null = null;
let current: { path: string; startedAt: number } | null = null;
let installed = false;
let memorySession: SessionRecord | null = null;
const recentErrors = new Map<string, number>();

function active(): boolean {
  return typeof window !== "undefined" && !navigator.webdriver;
}

function loadSession(): SessionRecord | null {
  try {
    const raw = window.localStorage.getItem(SID_KEY);
    if (raw) return JSON.parse(raw) as SessionRecord;
  } catch {
    // private mode / storage disabled -> memory fallback below
  }
  return memorySession;
}

function saveSession(s: SessionRecord): void {
  memorySession = s;
  try {
    window.localStorage.setItem(SID_KEY, JSON.stringify(s));
  } catch {
    // memory fallback already set
  }
}

function currentSession(): { sid: string; firstEvent: boolean } {
  const now = Date.now();
  const stored = loadSession();
  if (stored && now - stored.lastSeen < IDLE_MS) {
    stored.lastSeen = now;
    saveSession(stored);
    return { sid: stored.sid, firstEvent: !stored.sent };
  }
  const fresh: SessionRecord = { sid: crypto.randomUUID(), lastSeen: now };
  saveSession(fresh);
  return { sid: fresh.sid, firstEvent: true };
}

function markSent(): void {
  const stored = loadSession();
  if (stored) {
    stored.sent = 1;
    saveSession(stored);
  }
}

function clientInfo(): { tz?: string; locale?: string } {
  try {
    return {
      tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
      locale: navigator.language,
    };
  } catch {
    return {};
  }
}

function flush(): void {
  if (!queue.length) return;
  const batch = queue;
  queue = [];
  const body = JSON.stringify({ client: clientInfo(), events: batch });
  try {
    if (navigator.sendBeacon) {
      navigator.sendBeacon(ENDPOINT, new Blob([body], { type: "application/json" }));
      return;
    }
  } catch {
    // fall through to fetch
  }
  fetch(ENDPOINT, {
    method: "POST",
    body,
    headers: { "content-type": "application/json" },
    keepalive: true,
  }).catch(() => {});
}

function ensureTimer(): void {
  if (timer !== null || document.hidden) return;
  timer = setInterval(() => {
    if (queue.length) flush();
  }, FLUSH_MS);
}

function stopTimer(): void {
  if (timer !== null) {
    clearInterval(timer);
    timer = null;
  }
}

function enqueue(ev: UsageEvent): void {
  if (!active()) return;
  queue.push(ev);
  ensureTimer();
  if (queue.length >= FLUSH_AT) flush();
}

function currentPath(): string {
  return current?.path ?? location.pathname;
}

/** Route change or initial view: opens (or re-opens) the dwell window. */
export function beginPageView(pathname: string): void {
  if (!active()) return;
  if (current) endPageView();
  current = { path: pathname, startedAt: Date.now() };
}

/** Emits one page_view for the open view (dwell included); no-op if none. */
export function endPageView(): void {
  if (!current || !active()) return;
  const { path, startedAt } = current;
  current = null;
  const { sid, firstEvent } = currentSession();
  const ref = refForPath(path);
  const ev: UsageEvent = {
    type: "page_view",
    session_id: sid,
    path,
    duration_ms: Date.now() - startedAt,
  };
  if (firstEvent && document.referrer) {
    ev.referrer = document.referrer;
    markSent();
  }
  if (ref) {
    ev.ref_type = ref.ref_type;
    ev.ref_id = ref.ref_id;
  }
  enqueue(ev);
}

export function trackSearch(input: {
  query: string;
  results_count?: number;
  search_scope: UsageScope;
  filters?: Record<string, unknown>;
}): void {
  if (!active()) return;
  const { sid } = currentSession();
  const query = input.query.trim();
  enqueue({
    type: "search",
    session_id: sid,
    path: currentPath(),
    // Empty query = a default browse load, never a query string.
    ...(query === "" ? { is_browse: true } : { query: query.slice(0, 512) }),
    results_count: input.results_count,
    search_scope: input.search_scope,
    filters: input.filters,
  });
}

function trackError(
  source: NonNullable<UsageEvent["source"]>,
  message: string | undefined,
  detail: string | undefined,
  status: number | undefined,
): void {
  if (!active()) return;
  const path = currentPath();
  const key = `${message ?? ""}|${path}`;
  const now = Date.now();
  for (const [k, ts] of recentErrors) {
    if (now - ts > DEDUP_MS) recentErrors.delete(k);
  }
  if (recentErrors.has(key)) return;
  recentErrors.set(key, now);
  const { sid } = currentSession();
  enqueue({
    type: "error",
    session_id: sid,
    path,
    source,
    message: message?.slice(0, 1024),
    detail: detail?.slice(0, 1024),
    status,
  });
}

/** API failures: called at the ApiError throw site in lib/api.ts. */
export function trackApiError(method: string, url: string, status: number): void {
  trackError("api_status", undefined, `${method} ${url} ${status}`, status);
}

function onWindowError(e: ErrorEvent): void {
  trackError("js_error", e.message || "unknown error", `${e.filename}:${e.lineno}`, undefined);
}

function onUnhandledRejection(e: PromiseRejectionEvent): void {
  const reason = e.reason as { message?: string; stack?: string } | undefined;
  trackError(
    "unhandled_rejection",
    String(reason?.message ?? reason ?? "unhandled rejection"),
    String(reason?.stack ?? ""),
    undefined,
  );
}

function onPageHide(): void {
  endPageView();
  flush();
}

function onVisibilityChange(): void {
  // A hidden tab only flushes; the page_view ends on route change or
  // pagehide, not on every tab switch.
  if (document.hidden) {
    stopTimer();
    flush();
  } else {
    ensureTimer();
  }
}

/** Idempotent install of the batch timer and global error listeners. */
export function initUsageTracking(): void {
  if (!active() || installed) return;
  installed = true;
  window.addEventListener("pagehide", onPageHide);
  document.addEventListener("visibilitychange", onVisibilityChange);
  window.addEventListener("error", onWindowError);
  window.addEventListener("unhandledrejection", onUnhandledRejection);
  ensureTimer();
}
