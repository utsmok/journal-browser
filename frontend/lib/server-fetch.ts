import { notFound } from "next/navigation";
import { cache } from "react";

import type { InstitutionDirectoryEntry } from "@/lib/admin";
import { type ApiRequest, institutionsRequest } from "@/lib/api";

const API = process.env.API_PROXY_URL || "http://localhost:8000";

/** Seconds a fetched document stays in Next's data cache. */
const DOCUMENT_REVALIDATE = 300;

/** The backend URL path of a request: the same one the browser's apiGet builds. */
function urlOf({ path, query = {} }: ApiRequest): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  return `/api/v1${path}${qs ? `?${qs}` : ""}`;
}

type LoadedDocument = { status: number; body: unknown };

// React's per-request cache: a render that reads the same document twice
// (page title and page body) makes one backend call. Status 0 means the
// backend was unreachable.
const loadDocument = cache(async (url: string, revalidate: number): Promise<LoadedDocument> => {
  try {
    const res = await fetch(`${API}${url}`, { next: { revalidate } });
    return { status: res.status, body: res.ok ? await res.json() : null };
  } catch {
    return { status: 0, body: null };
  }
});

/**
 * GET one backend document for a server render. `request` is the one the
 * page's browser hook sends (a lib/api `*Request` builder, path after
 * /api/v1), so a seeded cache entry matches what the browser would fetch.
 * The document stays in Next's data cache for `revalidate` seconds. Returns
 * null when the backend is unreachable or answers with an error status: the
 * render goes on without the document, and the browser fetches it instead.
 */
export async function fetchForRender<T>(
  request: ApiRequest,
  revalidate: number = DOCUMENT_REVALIDATE,
): Promise<T | null> {
  return (await loadDocument(urlOf(request), revalidate)).body as T | null;
}

/**
 * fetchForRender for the document a detail route is about. When the backend
 * answers 404 the entity does not exist, so the route renders the not-found
 * page with HTTP 404 instead of an empty 200 shell (a "soft 404" to crawlers).
 * Other failures still return null and leave the fetch to the browser.
 */
export async function fetchOrNotFound<T>(
  request: ApiRequest,
  revalidate: number = DOCUMENT_REVALIDATE,
): Promise<T | null> {
  const doc = await loadDocument(urlOf(request), revalidate);
  if (doc.status === 404) notFound();
  return doc.body as T | null;
}

/** A directory row with the fields pages render. The backend always sends them. */
export type DirectoryInstitution = InstitutionDirectoryEntry & {
  data_window_start: number;
  data_window_end: number | null;
};

/** Hosted institutions, or null when the API is unreachable. */
export function fetchInstitutions(): Promise<DirectoryInstitution[] | null> {
  return fetchForRender<DirectoryInstitution[]>(institutionsRequest());
}

/**
 * Short name of a hosted institution ("Twente") for page descriptions. Falls
 * back to the full name, then to the code, when the directory is unreachable.
 */
export async function institutionShortName(inst: string): Promise<string> {
  const row = (await fetchInstitutions())?.find((candidate) => candidate.code === inst);
  return row?.short_name || row?.name || inst.toUpperCase();
}
