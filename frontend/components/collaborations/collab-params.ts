import {
  COLLAB_MULTI_KEYS,
  type CollaborationLead,
  type CollaborationLevel,
  type CollaborationSearchParams,
  type CollaborationSize,
  type CollaborationSort,
} from "@/lib/api";

const LEVELS: readonly CollaborationLevel[] = ["faculty", "group", "institute"];
const SIZES: readonly CollaborationSize[] = ["standard", "small", "all"];
const LEADS: readonly CollaborationLead[] = ["all", "home", "partner"];
const SORTS: readonly CollaborationSort[] = [
  "works",
  "name",
  "corresponding_works",
  "home_corresponding_works",
  "oa_share",
];

/** Rows per page in the partner detail's shared-works table. */
export const PAGE_SIZE = 10;

/** Replaces the given filter keys and keeps the rest. A key set to `undefined`
 * returns to its default. */
export type UpdateParams = (patch: Partial<CollaborationSearchParams>) => void;

/** Every filter kept in the page URL (including search query `q` and mode
 * switches), so filtered views survive refresh, Back nav, and sharing. */
export function readCollabParams(sp: URLSearchParams): CollaborationSearchParams {
  const out: CollaborationSearchParams = {};
  const q = sp.get("q")?.trim();
  if (q) out.q = q;
  for (const key of COLLAB_MULTI_KEYS) {
    const values = (sp.get(key) ?? "").split("|").filter(Boolean);
    if (values.length) out[key] = values;
  }
  const level = sp.get("level");
  if (level && LEVELS.includes(level as CollaborationLevel)) {
    out.level = level as CollaborationLevel;
  }
  const size = sp.get("size");
  if (size && SIZES.includes(size as CollaborationSize) && size !== "standard") {
    out.size = size as CollaborationSize;
  }
  const rollup = sp.get("rollup");
  if (rollup === "0" || rollup === "false") {
    out.rollup = false;
  }
  const lead = sp.get("lead");
  if (lead && LEADS.includes(lead as CollaborationLead) && lead !== "all") {
    out.lead = lead as CollaborationLead;
  }
  const minRaw = sp.get("min_works");
  if (minRaw) {
    const parsed = Number.parseInt(minRaw, 10);
    if (Number.isFinite(parsed) && parsed > 1) out.min_works = parsed;
  }
  if (sp.get("shares_deals") === "1" || sp.get("shares_deals") === "true") {
    out.shares_deals = true;
  }
  const sort = sp.get("sort");
  if (sort && SORTS.includes(sort as CollaborationSort)) {
    out.sort = sort as CollaborationSort;
  }
  const dir = sp.get("dir");
  if (dir === "asc" || dir === "desc") out.dir = dir;
  return out;
}

export function writeCollabParams(p: CollaborationSearchParams): string {
  const sp = new URLSearchParams();
  if (p.q?.trim()) sp.set("q", p.q.trim());
  for (const key of COLLAB_MULTI_KEYS) {
    if (p[key]?.length) sp.set(key, p[key].join("|"));
  }
  if (p.level) sp.set("level", p.level);
  if (p.size && p.size !== "standard") sp.set("size", p.size);
  if (p.rollup === false) sp.set("rollup", "0");
  if (p.lead && p.lead !== "all") sp.set("lead", p.lead);
  if (p.min_works && p.min_works > 1) sp.set("min_works", String(p.min_works));
  if (p.shares_deals) sp.set("shares_deals", "1");
  if (p.sort) sp.set("sort", p.sort);
  if (p.dir) sp.set("dir", p.dir);
  return sp.toString();
}

export function hasActiveCollabFilters(p: CollaborationSearchParams): boolean {
  return Boolean(
    p.q ||
      p.level ||
      (p.size && p.size !== "standard") ||
      p.rollup === false ||
      (p.lead && p.lead !== "all") ||
      (p.min_works && p.min_works > 1) ||
      p.shares_deals ||
      COLLAB_MULTI_KEYS.some((key) => p[key]?.length),
  );
}

export const EMPTY_COLLAB_FILTERS: Partial<CollaborationSearchParams> = {
  q: undefined,
  type: undefined,
  country: undefined,
  faculty: undefined,
  oa_status: undefined,
  topic: undefined,
  funder: undefined,
  project: undefined,
  source: undefined,
  level: undefined,
  size: undefined,
  rollup: undefined,
  lead: undefined,
  min_works: undefined,
  shares_deals: undefined,
};
