import { useCallback, useEffect, useState } from "react";

/**
 * Shared admin plumbing: bearer-token storage, authenticated fetch helpers,
 * and hand-written types for the admin payloads (api-types.ts only covers
 * the older generated contract).
 */
const TOKEN_KEY = "jb-admin-token";

/** Error with an HTTP status; message stays technical (console only). */
export class AdminError extends Error {
  status: number;
  constructor(status: number, path: string) {
    super(`${status} on ${path}`);
    this.name = "AdminError";
    this.status = status;
  }
}

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(TOKEN_KEY);
}

export async function adminLogin(password: string): Promise<string> {
  const res = await fetch("/api/v1/admin/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) throw new AdminError(res.status, "/login");
  const { token } = (await res.json()) as { token: string };
  return token;
}

async function adminFetch<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api/v1/admin${path}`, {
    ...init,
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}`, ...(init.headers ?? {}) },
  });
  if (!res.ok) throw new AdminError(res.status, path);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function adminGet<T>(path: string, token: string): Promise<T> {
  return adminFetch<T>(path, token);
}

export function adminPut<T>(path: string, token: string, body: unknown): Promise<T> {
  return adminFetch<T>(path, token, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function adminPost<T>(path: string, token: string, body: unknown): Promise<T> {
  return adminFetch<T>(path, token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function adminPatch<T>(path: string, token: string, body: unknown): Promise<T> {
  return adminFetch<T>(path, token, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function adminDelete(path: string, token: string): Promise<void> {
  return adminFetch<void>(path, token, { method: "DELETE" });
}

/** Session-cached admin token plus a setter that persists/removes it. */
export function useAdminToken(): [string | null, (token: string | null) => void] {
  const [token, setToken] = useState<string | null>(null);
  useEffect(() => {
    setToken(getStoredToken());
  }, []);
  const update = useCallback((t: string | null) => {
    if (t) sessionStorage.setItem(TOKEN_KEY, t);
    else sessionStorage.removeItem(TOKEN_KEY);
    setToken(t);
  }, []);
  return [token, update];
}

export type AdminRun = {
  id: number;
  source: string;
  entity_type: string;
  institution_id: number | null;
  institution_code: string | null;
  status: string;
  started_at: string;
  finished_at: string | null;
  stats: Record<string, unknown>;
};

export type FlaggedDeal = {
  id: number;
  publisher: string;
  esac_id: string | null;
  status: string;
  duration: string | null;
  journals: number;
  reason: string | null;
};

export type InstitutionDirectoryEntry = {
  code: string;
  name: string;
  short_name: string | null;
};

export type SettingType = "string" | "number" | "bool" | "secret" | "list";

export type SettingField = {
  key: string;
  section: "global" | "institution";
  type: SettingType;
  label: string;
  help?: string | null;
  default?: string | number | boolean | null;
};

/** GET /admin/settings: schema-driven global settings; secrets arrive masked. */
export type SettingsResponse = {
  schema: SettingField[];
  values: Record<string, string | number | boolean | null>;
};

/** GET/PUT /admin/institutions/{code}. */
export type InstitutionSettings = {
  code: string;
  name: string;
  short_name: string | null;
  ror: string | null;
  openalex_id: string | null;
  pure_oai_base_url: string | null;
  openaire_org_id: string | null;
  data_window_start: number | null;
  data_window_end: number | null;
  library_url: string | null;
  oa_guide_url: string | null;
  support_email: string | null;
  admin_contact: string | null;
  research_portal_url: string | null;
  active: boolean | null;
  /** Author search hides unconfirmed affiliations when true (backend default true). */
  require_confirmed_affiliation: boolean | null;
};

/** GET /admin/deals and the base of GET /admin/deals/{id}. */
export type AdminDeal = {
  id: number;
  publisher_id: number | null;
  publisher: string | null;
  esac_id: string | null;
  status: "current" | "archive";
  start_year: number | null;
  end_year: number | null;
  corresponding_authors_only: boolean;
  capped: boolean;
  cap_numbers: Record<string, number> | null;
  cap_text: string | null;
  summary: string | null;
  journal_count: number;
  participations: string[];
  needs_curation: boolean;
  needs_curation_reason: string | null;
};

export type AdminDealJournal = {
  issn: string;
  issn_l: string | null;
  journal_name: string | null;
  source: "jct" | "manual" | "publisher-pattern";
  excluded: boolean;
};

/** GET/PUT/POST /admin/deals…: a deal plus its journal membership list. */
export type AdminDealDetail = AdminDeal & { journals: AdminDealJournal[] };

/** GET /admin/feedback: one user report with its page-data dump. */
export type FeedbackAdmin = {
  id: number;
  title: string;
  description: string;
  category: string | null;
  status: "todo" | "in_progress" | "done" | "wontfix";
  priority: "low" | "normal" | "high" | "critical";
  page_url: string | null;
  page_data: {
    url?: string;
    user_agent?: string;
    viewport?: string;
    queries?: { key: unknown[]; data: unknown }[];
  } | null;
  resolution_notes: string | null;
  created_at: string;
  updated_at: string;
};
