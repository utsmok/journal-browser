import type { DealLink } from "@/lib/api";
import type { LabelT } from "@/lib/work-type";

/** Fixed rendering order and message keys (common.dealLinks) for deal link
 * categories. */
const DEAL_LINK_ORDER: { category: string; labelKey: string }[] = [
  { category: "workflow", labelKey: "dealLinks.workflow" },
  { category: "contract", labelKey: "dealLinks.contract" },
  { category: "contact", labelKey: "dealLinks.contact" },
  { category: "publisher_site", labelKey: "dealLinks.publisherPage" },
  { category: "publisher_page", labelKey: "dealLinks.publisherPage" },
  { category: "journal_browser", labelKey: "dealLinks.journalBrowser" },
  { category: "openaccessnl_doc", labelKey: "dealLinks.openAccessInfo" },
  { category: "flyer", labelKey: "dealLinks.flyer" },
  { category: "other", labelKey: "dealLinks.information" },
];

const DEAL_LINK_KEYS = Object.fromEntries(
  DEAL_LINK_ORDER.map(({ category, labelKey }) => [category, labelKey]),
) as Record<string, string>;

/** Scraped text sometimes leaks the raw category token ("workflow", "info"). */
const TEXT_ALIASES: Record<string, string> = {
  workflow: "dealLinks.workflow",
  contract: "dealLinks.contract",
  contact: "dealLinks.contact",
  info: "dealLinks.information",
  other: "dealLinks.information",
};

function cleanLabel(t: LabelT, link: DealLink) {
  const text = link.text?.trim().replace(/[.:\s]+$/, "");
  if (!text) return t(DEAL_LINK_KEYS[link.category ?? ""] ?? "dealLinks.information");
  if (/[^\s@]+@[^\s@]+\.[^\s@]+/.test(text)) return t("dealLinks.contact");
  const aliased = TEXT_ALIASES[text.toLowerCase()];
  if (aliased) return t(aliased);
  // Scraped single-word labels sometimes arrive lowercase ("documentation").
  return /^[a-z][a-z\s]*$/.test(text) ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

/** Publisher names scraped in full caps ("WOLTERS KLUWER") read as shouting;
 * title-case those for display. Short strings stay as-is so acronyms
 * ("ACS", "AIPP", "MDPI") survive, as do two-letter suffixes ("Elsevier BV"). */
export function displayPublisherName(name: string | null | undefined): string {
  if (!name || !/^[A-Z0-9 .&'\-/]+$/.test(name) || name.length <= 5) return name ?? "";
  return name
    .split(/\s+/)
    .map((word) => (word.length <= 2 ? word : word.charAt(0) + word.slice(1).toLowerCase()))
    .join(" ");
}

/** Last path segment; identifies the same document mirrored on two hosts. */
function docKey(url: string) {
  try {
    return new URL(url).pathname.split("/").pop() ?? url;
  } catch {
    return url;
  }
}

export function orderedDealLinks(links: DealLink[]) {
  const rank = new Map<string, number>(DEAL_LINK_ORDER.map((e, i) => [e.category, i]));
  const seen = new Set<string>();
  return [...links]
    .sort((a, b) => (rank.get(a.category ?? "") ?? 99) - (rank.get(b.category ?? "") ?? 99))
    .filter((link) => {
      // Same URL, or the same document re-hosted under a different domain,
      // is listed once.
      const key = `${docKey(link.url ?? "").toLowerCase()}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

export function dealLinkLabel(t: LabelT, link: DealLink) {
  return cleanLabel(t, link);
}
