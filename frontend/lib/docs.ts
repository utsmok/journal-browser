import type { components } from "./api-types";
import { getRequest, type ApiRequest } from "./api";

type Schemas = components["schemas"];

/**
 * Docs surface (markdown served by the backend as parsed blocks).
 * Code against the contract: GET /api/v1/docs and /api/v1/docs/{slug},
 * edits under /api/v1/admin/docs/{slug}/edits.
 */
export type DocGroup = "overview" | "pitch" | "sources";

/** Reference-book reading order for the index and the prev/next pager. */
export const DOC_GROUPS: DocGroup[] = ["overview", "pitch", "sources"];

export const GROUP_LABEL: Record<string, string> = {
  overview: "Overview",
  pitch: "Pitch",
  sources: "Sources",
};

export type DocsListItem = Schemas["DocMetaOut"];

export type DocBlock = Schemas["DocBlock"];

export type DocDetail = Schemas["DocDetailOut"];

/** The request builders behind fetchDocs and fetchDoc; the server render
 * sends the same requests to seed the React Query cache. */
export function docsRequest(): ApiRequest {
  return { path: "/docs" };
}

export function docRequest(slug: string): ApiRequest {
  return { path: `/docs/${encodeURIComponent(slug)}` };
}

export function fetchDocs(): Promise<DocsListItem[]> {
  return getRequest<DocsListItem[]>(docsRequest());
}

export function fetchDoc(slug: string): Promise<DocDetail> {
  return getRequest<DocDetail>(docRequest(slug));
}

/** Sort into group order (overview, pitch, sources), then doc order. */
export function sortDocs(docs: DocsListItem[]): DocsListItem[] {
  return [...docs].sort(
    (a, b) =>
      DOC_GROUPS.findIndex((g) => g === a.group) - DOC_GROUPS.findIndex((g) => g === b.group) ||
      a.order - b.order ||
      a.title.localeCompare(b.title),
  );
}

/** sha256 hex of the block text the editor saw; sent as original_hash on PUT. */
export async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Heading anchor id: slugified heading text ("Open data & sources" → "open-data-sources"). */
export function slugifyHeading(text: string): string {
  return text
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function truncate(text: string, max = 140): string {
  if (text.length <= max) return text;
  return `${text.slice(0, text.lastIndexOf(" ", max))}…`;
}

// --- Markdown tables -------------------------------------------------------

export type TableRow = { cells: string[]; raw: string; align: boolean };

/** Parse the pipe-lines of a markdown table; alignment rows keep their raw line. */
export function parseTable(text: string): TableRow[] {
  return text
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => {
      const raw = line.trim();
      const cells = raw
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split(/(?<!\\)\|/)
        .map((c) => c.trim().replace(/\\\|/g, "|"));
      return { raw, cells, align: cells.every((c) => /^:?-{3,}:?$/.test(c)) };
    });
}

/** Serialize rows back to markdown, swapping in one edited cell. */
export function replaceCell(rows: TableRow[], row: number, col: number, value: string): string {
  return rows
    .map((r, i) => {
      const cells = i === row ? r.cells.map((c, j) => (j === col ? value : c)) : r.cells;
      return r.align ? r.raw : `| ${cells.map((c) => c.replace(/\|/g, "\\|")).join(" | ")} |`;
    })
    .join("\n");
}
