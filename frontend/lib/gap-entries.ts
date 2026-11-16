import type { components } from "./api-types";

/**
 * Gap-list entries: the API groups flat gap work rows into singles and
 * parent-with-parts groups. The API boundary uses the generated schema;
 * rendering uses a display projection, because the generated work-row
 * models differ per surface (author rows omit venue fields).
 */

type Schemas = components["schemas"];

/** Discriminated entries exactly as the API serves them, across both
 * surface variants. */
export type ApiGapEntry =
  | Schemas["OpenalexOnlySingle"]
  | Schemas["OpenalexOnlyGroup"]
  | Schemas["AuthorOpenalexOnlySingle"]
  | Schemas["AuthorOpenalexOnlyGroup"];

/** Parent work of a group entry (the chapter host / main work). w_id and
 * name are null without a registry row (backfill pending). pure_registered:
 * true = registered in Pure, false = missing, null = not fetched yet. */
export type GapParent = Schemas["GapGroupParent"];

/** One OpenAlex-side gap work: the fields the gap renderers display. */
export type GapWorkRow = {
  title?: string | null;
  year?: number | null;
  doi?: string | null;
  oa_status?: string | null;
  work_type?: string | null;
  venue?: string | null;
  openalex_id?: string | null;
  openalex_url?: string | null;
  ut_authors?: Schemas["UtAuthorAttribution"][];
  journal_issn_l?: string | null;
  journal_title?: string | null;
  publisher_name?: string | null;
  parent_works?: Schemas["WorkParent"][];
  is_part?: boolean;
  pure_match?: ("doi_in_pure" | "parent_book_in_pure" | "same_title_in_pure") | null;
  pure_match_url?: string | null;
};

/** A gap work that stands on its own (not grouped under a parent). */
export type GapSingle = GapWorkRow & { kind: "single" };

/** A parent work with its gap parts grouped beneath it. */
export type GapGroup = {
  kind: "group";
  parent: GapParent;
  /** The group's parts, most-recent first. */
  parts?: GapWorkRow[];
  /** Total parts in the group, before the page's entry cap. */
  parts_total?: number;
};

export type GapEntry = GapSingle | GapGroup;

/**
 * Typed identity from the generated entry union to the display
 * projection: every generated row carries the projected fields, so the
 * assignment is checked, not cast.
 */
export function toGapEntries(items: readonly ApiGapEntry[]): GapEntry[] {
  return [...items];
}

/**
 * Entry count after grouping — the unit the page's entry cap applies
 * to. Falls back to the flat item count while `entries_total` is absent
 * from the payload.
 */
export function entriesTotal(payload: {
  entries_total?: number;
  items: readonly unknown[];
}): number {
  return payload.entries_total ?? payload.items.length;
}
