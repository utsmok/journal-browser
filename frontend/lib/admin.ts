import type { components } from "./api-types";
import { useCallback, useEffect, useState } from "react";

/**
 * Shared admin plumbing: bearer-token storage, authenticated fetch helpers,
 * and the admin payload types, derived from the generated contract.
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

type Schemas = components["schemas"];

export type AdminRun = Schemas["AdminRunOut"];

export type FlaggedDeal = Schemas["FlaggedDealOut"];

export type InstitutionDirectoryEntry = Schemas["InstitutionOut"];

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
export type InstitutionSettings = Schemas["AdminInstitutionOut"];

/** GET /admin/deals and the base of GET /admin/deals/{id}. */
export type AdminDeal = Schemas["AdminDealOut"];

export type AdminDealJournal = Schemas["AdminDealJournal"];

/** GET/PUT/POST /admin/deals…: a deal plus its journal membership list. */
export type AdminDealDetail = Schemas["AdminDealDetail"];

/** GET /admin/feedback: one user report with its page-data dump. */
export type FeedbackAdmin = Schemas["FeedbackAdminOut"];
