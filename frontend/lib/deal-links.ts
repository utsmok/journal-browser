import type { DealLink } from "@/lib/api";

/** Fixed rendering order and fallback labels for deal link categories. */
const DEAL_LINK_ORDER: { category: string; label: string }[] = [
  { category: "workflow", label: "Workflow" },
  { category: "contract", label: "Contract" },
  { category: "contact", label: "Contact" },
  { category: "publisher_site", label: "Publisher page" },
  { category: "publisher_page", label: "Publisher page" },
  { category: "journal_browser", label: "Journal browser" },
  { category: "openaccessnl_doc", label: "Open Access info" },
  { category: "flyer", label: "Flyer" },
  { category: "other", label: "Information" },
];

const DEAL_LINK_LABEL = Object.fromEntries(
  DEAL_LINK_ORDER.map(({ category, label }) => [category, label]),
) as Record<string, string>;

/** Scraped text sometimes leaks the raw category token ("workflow", "info"). */
const TEXT_ALIASES: Record<string, string> = {
  workflow: "Workflow",
  contract: "Contract",
  contact: "Contact",
  info: "Information",
  other: "Information",
};

function cleanLabel(link: DealLink) {
  const text = link.text?.trim().replace(/[.:\s]+$/, "");
  if (!text) return DEAL_LINK_LABEL[link.category ?? ""] ?? "Information";
  if (/[^\s@]+@[^\s@]+\.[^\s@]+/.test(text)) return "Contact";
  const aliased = TEXT_ALIASES[text.toLowerCase()];
  if (aliased) return aliased;
  // Scraped single-word labels sometimes arrive lowercase ("documentation").
  return /^[a-z][a-z\s]*$/.test(text)
    ? text.charAt(0).toUpperCase() + text.slice(1)
    : text;
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
  const rank = new Map<string, number>(
    DEAL_LINK_ORDER.map((e, i) => [e.category, i]),
  );
  const seen = new Set<string>();
  return [...links]
    .sort(
      (a, b) => (rank.get(a.category ?? "") ?? 99) - (rank.get(b.category ?? "") ?? 99),
    )
    .filter((link) => {
      // Same URL, or the same document re-hosted under a different domain,
      // is listed once.
      const key = `${docKey(link.url ?? "").toLowerCase()}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

export function dealLinkLabel(link: DealLink) {
  return cleanLabel(link);
}
