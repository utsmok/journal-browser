/** Plain-English work-type labels. Raw values come in two dialects: Pure
 * carries IRI-tagged types ('info:eu-repo/semantics/bookPart',
 * 'book-part'), OpenAlex bare hyphenated ones ('book-chapter',
 * 'article'). Normalization mirrors backend config.normalize_work_type:
 * strip the euro-repo prefix, drop hyphens, lower-case. */
const WORK_TYPE_LABELS: Record<string, string> = {
  article: "Article",
  bookpart: "Book chapter",
  bookchapter: "Book chapter",
  book: "Book",
  monograph: "Book",
  conferenceobject: "Conference paper",
  conferencepaper: "Conference paper",
  conferenceproceedings: "Conference paper",
  conferenceabstract: "Conference abstract",
  report: "Report",
  review: "Review",
  editorial: "Editorial",
  letter: "Letter",
  dissertation: "Thesis",
  doctoralthesis: "Thesis",
  contributiontoperiodical: "Magazine article",
};

/** Human label for a raw work type ('info:eu-repo/semantics/bookPart' ->
 * 'Book chapter'); unmapped values render title-cased, null/empty -> null. */
export function workTypeLabel(raw: string | null | undefined): string | null {
  const key = (raw ?? "")
    .replace("info:eu-repo/semantics/", "")
    .replaceAll("-", "")
    .trim()
    .toLowerCase();
  if (!key) return null;
  return WORK_TYPE_LABELS[key] ?? key.charAt(0).toUpperCase() + key.slice(1);
}
