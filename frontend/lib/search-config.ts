import type { OrgUnitSearchSort, PublisherSearchSort, SearchIn, SortKey } from "@/lib/api";

export const SORTS: { value: SortKey; labelKey: string }[] = [
  { value: "relevance", labelKey: "sorts.relevance" },
  { value: "title", labelKey: "sorts.title" },
  { value: "publisher", labelKey: "sorts.publisher" },
  { value: "institution_works", labelKey: "sorts.institutionWorks" },
  { value: "quartile", labelKey: "sorts.quartile" },
  { value: "topic", labelKey: "sorts.topic" },
  { value: "apc", labelKey: "sorts.apc" },
  { value: "2yr_mean_citedness", labelKey: "sorts.meanCitedness" },
];

// Sortable columns: backend key + natural direction. The header button
// cycles natural → reversed → off (back to the mode's default sort).
export const COLUMN_SORTS: Record<string, { key: SortKey; natural: "asc" | "desc" }> = {
  title: { key: "title", natural: "asc" },
  publisher: { key: "publisher", natural: "asc" },
  works: { key: "institution_works", natural: "desc" },
  citedness: { key: "2yr_mean_citedness", natural: "desc" },
  quartile: { key: "quartile", natural: "asc" },
  apc: { key: "apc", natural: "desc" },
  topic: { key: "topic", natural: "asc" },
};

// Publisher directory columns: same tri-state header convention as the
// journal search table (natural → reversed → off).
export const PUBLISHER_COLUMN_SORTS: Record<
  string,
  { key: PublisherSearchSort; natural: "asc" | "desc" }
> = {
  name: { key: "name", natural: "asc" },
  journals: { key: "journals", natural: "desc" },
  works: { key: "works", natural: "desc" },
  deals: { key: "deals", natural: "desc" },
  apc: { key: "apc", natural: "desc" },
};

// Org-unit directory columns: same convention; the backend has no APC sort.
export const ORGUNIT_COLUMN_SORTS: Record<
  string,
  { key: OrgUnitSearchSort; natural: "asc" | "desc" }
> = {
  name: { key: "name", natural: "asc" },
  authors: { key: "authors", natural: "desc" },
  works: { key: "works", natural: "desc" },
  deal_works: { key: "deal_works", natural: "desc" },
};

export const SEARCH_IN_OPTIONS: { value: SearchIn; labelKey: string }[] = [
  { value: "all", labelKey: "searchIn.all" },
  { value: "title", labelKey: "searchIn.title" },
  { value: "publisher", labelKey: "searchIn.publisher" },
  { value: "topic", labelKey: "searchIn.topic" },
];

/** Message keys (search.pubTypes) for OpenAlex venue types (pub_type);
 * unmapped values (future OpenAlex types) show raw. */
export const PUB_TYPE_LABELS: Record<string, string> = {
  journal: "pubTypes.journal",
  "book series": "pubTypes.bookSeries",
  conference: "pubTypes.conference",
  "ebook platform": "pubTypes.ebookPlatform",
  repository: "pubTypes.repository",
};
