import type { OrgUnitSearchSort, PublisherSearchSort, SearchIn, SortKey } from "@/lib/api";

export const SORTS: { value: SortKey; label: string }[] = [
  { value: "relevance", label: "Relevance" },
  { value: "title", label: "Title A–Z" },
  { value: "publisher", label: "Publisher A–Z" },
  { value: "institution_works", label: "Institution works" },
  { value: "quartile", label: "Quartile" },
  { value: "topic", label: "Topic A–Z" },
  { value: "apc", label: "APC (high–low)" },
  { value: "2yr_mean_citedness", label: "2-year mean citedness" },
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

export const SEARCH_IN_OPTIONS: { value: SearchIn; label: string }[] = [
  { value: "all", label: "Everything" },
  { value: "title", label: "Title" },
  { value: "publisher", label: "Publisher" },
  { value: "topic", label: "Topic" },
];

/** Display labels for OpenAlex venue types (pub_type); unmapped values
 * (future OpenAlex types) show raw. */
export const PUB_TYPE_LABELS: Record<string, string> = {
  journal: "Journal",
  "book series": "Book series",
  conference: "Conference",
  "ebook platform": "E-book platform",
  repository: "Repository",
};

/** Display labels for the modal journal language (ISO 639-1); codes
 * outside this list show raw. */
export const LANGUAGE_LABELS: Record<string, string> = {
  en: "English",
  nl: "Dutch",
  de: "German",
  fr: "French",
  es: "Spanish",
  it: "Italian",
  pt: "Portuguese",
  ru: "Russian",
  zh: "Chinese",
  ja: "Japanese",
  ko: "Korean",
  ar: "Arabic",
  la: "Latin",
  sv: "Swedish",
  no: "Norwegian",
  da: "Danish",
  fi: "Finnish",
  pl: "Polish",
  tr: "Turkish",
};
