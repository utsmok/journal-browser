import { cache } from "react";

import type { InstitutionDirectoryEntry } from "@/lib/admin";

const API = process.env.API_PROXY_URL || "http://localhost:8000";

/** Query-string values, as the client fetchers pass them: null, undefined and "" are dropped. */
export type RenderQuery = Record<string, string | number | boolean | null | undefined>;

/** Address of a backend document as the browser would request it. */
export type DocumentAddress = { path: string; query?: RenderQuery };

/** Seconds a fetched document stays in Next's data cache. */
const DOCUMENT_REVALIDATE = 300;

function withQuery({ path, query = {} }: DocumentAddress): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `${path}?${qs}` : path;
}

// React's per-request cache: a render that reads the same document twice
// (page title and page body) makes one backend call.
const loadDocument = cache(async (url: string, revalidate: number): Promise<unknown> => {
  try {
    const res = await fetch(`${API}${url}`, { next: { revalidate } });
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
});

/**
 * GET one backend document for a server render. The document stays in Next's
 * data cache for `revalidate` seconds. Returns null when the backend is
 * unreachable or answers with an error status: the render goes on without the
 * document, and the browser fetches it instead.
 */
export async function fetchForRender<T>(
  address: DocumentAddress,
  revalidate: number = DOCUMENT_REVALIDATE,
): Promise<T | null> {
  return (await loadDocument(withQuery(address), revalidate)) as T | null;
}

/** A directory row with the fields pages render. The backend always sends them. */
export type DirectoryInstitution = InstitutionDirectoryEntry & {
  data_window_start: number;
  data_window_end: number | null;
};

/** Hosted institutions, or null when the API is unreachable. */
export function fetchInstitutions(): Promise<DirectoryInstitution[] | null> {
  return fetchForRender<DirectoryInstitution[]>({ path: "/api/v1/institutions" });
}

/**
 * Short name of a hosted institution ("Twente") for page descriptions. Falls
 * back to the full name, then to the code, when the directory is unreachable.
 */
export async function institutionShortName(inst: string): Promise<string> {
  const row = (await fetchInstitutions())?.find((candidate) => candidate.code === inst);
  return row?.short_name || row?.name || inst.toUpperCase();
}
