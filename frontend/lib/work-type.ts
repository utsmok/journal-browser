/** Minimal translator shape shared by the label helpers. */
export type LabelT = (key: string) => string;

/** Plain-English work-type labels as message keys under common.workTypes.
 * Raw values come in two dialects: Pure
 * carries IRI-tagged types ('info:eu-repo/semantics/bookPart',
 * 'book-part'), OpenAlex bare hyphenated ones ('book-chapter',
 * 'article'). Normalization mirrors backend config.normalize_work_type:
 * strip the euro-repo prefix, drop hyphens, lower-case. */
const WORK_TYPE_LABEL_KEYS: Record<string, string> = {
  article: "workTypes.article",
  bookpart: "workTypes.bookChapter",
  bookchapter: "workTypes.bookChapter",
  book: "workTypes.book",
  monograph: "workTypes.book",
  conferenceobject: "workTypes.conferencePaper",
  conferencepaper: "workTypes.conferencePaper",
  conferenceproceedings: "workTypes.conferencePaper",
  conferenceabstract: "workTypes.conferenceAbstract",
  report: "workTypes.report",
  review: "workTypes.review",
  editorial: "workTypes.editorial",
  letter: "workTypes.letter",
  dissertation: "workTypes.thesis",
  doctoralthesis: "workTypes.thesis",
  contributiontoperiodical: "workTypes.magazineArticle",
};

/** Human label for a raw work type ('info:eu-repo/semantics/bookPart' ->
 * 'Book chapter'); unmapped values render title-cased, null/empty -> null. */
export function workTypeLabel(t: LabelT, raw: string | null | undefined): string | null {
  const key = (raw ?? "")
    .replace("info:eu-repo/semantics/", "")
    .replaceAll("-", "")
    .trim()
    .toLowerCase();
  if (!key) return null;
  const labelKey = WORK_TYPE_LABEL_KEYS[key];
  return labelKey ? t(labelKey) : key.charAt(0).toUpperCase() + key.slice(1);
}
