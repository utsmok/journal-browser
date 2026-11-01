import type { PublisherSearchSort, SearchIn, SortKey } from "@/lib/api";

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

export const SEARCH_IN_OPTIONS: { value: SearchIn; label: string }[] = [
  { value: "all", label: "Everything" },
  { value: "title", label: "Title" },
  { value: "publisher", label: "Publisher" },
  { value: "topic", label: "Topic" },
];
