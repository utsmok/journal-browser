import type { JournalListItem } from "@/lib/api";

/** Euro amounts for APC displays: rounded, locale-grouped, no decimals. */
export function formatEur(n: number): string {
  return Math.round(n).toLocaleString("en");
}

/** Grouped integer for table cells and counts ("1,269"). */
export function formatInt(n: number): string {
  return n.toLocaleString("en");
}

const regionNames =
  typeof Intl !== "undefined" && typeof Intl.DisplayNames === "function"
    ? new Intl.DisplayNames(["en"], { type: "region" })
    : null;

/** Human-readable English country name for an ISO-3166-1 alpha-2 code. */
export function countryName(code: string | null | undefined): string {
  const clean = (code ?? "").trim().toUpperCase();
  if (!clean) return "—";
  try {
    return regionNames?.of(clean) ?? clean;
  } catch {
    return clean;
  }
}

/** Admin/list datetimes: "2 Nov 2026, 18:34". Naive timestamps (no zone)
 * parse as local — same semantics every existing caller relied on. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}

/** Date only: "2 Nov 2026". */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-GB", { dateStyle: "medium" });
}

/** Round a displayed APC sensibly: nearest 10 euros at realistic prices. */
export function formatApc(euro: number) {
  const rounded = Math.abs(euro) >= 100 ? Math.round(euro / 10) * 10 : Math.round(euro);
  return rounded.toLocaleString("en");
}

/** Symbol for OpenAlex list-price currencies; ISO-code fallback for the rest. */
const APC_SYMBOLS: Record<string, string> = { EUR: "€", USD: "$", GBP: "£" };

export function apcAmount(currency: string | null | undefined, price: number): string {
  return `${(currency && APC_SYMBOLS[currency]) || `${currency ?? ""} `}${formatApc(price)}`;
}

/** Per-period OpenAPC detail lines for the ? tooltip. */
export function apcStatsText(stats: JournalListItem["apc_stats"]): string {
  return stats
    .map((s) => {
      const low = s.euro_min ?? s.euro_max;
      const range =
        low != null && low !== s.euro_max
          ? `${formatApc(low)}–${formatApc(s.euro_max ?? 0)}`
          : formatApc(s.euro_max ?? 0);
      // Figures stored before the paid/€0 split still count €0 articles.
      const paid = s.paid_count != null ? `${s.paid_count} paid` : "paid count not stored";
      const mean = `${s.paid_count != null ? "" : "approx. "}mean €${formatApc(s.euro_mean ?? 0)}`;
      return `${s.period}: €${range} · ${paid} · ${mean}`;
    })
    .join("\n");
}

/** The price fields of a list row: the shown price and the OpenAPC paid block. */
export type ApcFields = Pick<
  JournalListItem,
  | "apc_source"
  | "apc_currency"
  | "apc_price"
  | "apc_year"
  | "apc_original_currency"
  | "apc_original_price"
  | "apc_low"
  | "apc_high"
  | "apc_stats"
>;

const LIST_SOURCE_NAMES: Record<string, string> = { openalex: "OpenAlex", doaj: "DOAJ" };

/** Name of the dataset a list price comes from. */
export function apcSourceName(source: string): string {
  return LIST_SOURCE_NAMES[source] ?? source;
}

/** What a journal's APC display shows. `amount` is the price to show: a
 * publisher list price, or else the range of amounts paid. `paid` is the
 * mean of the newest OpenAPC period with an article paid above €0. */
export type ApcSummary = {
  kind: "list" | "paid" | "none";
  /** The dataset a list price comes from; null for a paid range. */
  source: string | null;
  /** The year the list price source was last harvested, or the paid period. */
  year: number | null;
  currency: string | null;
  amount: string | null;
  /** The list price as published, when it was converted to euros. */
  original: string | null;
  /** The mean of the newest period with an article paid above €0. `count`
   * is the paid articles of that period, or null when the stored figures
   * predate the paid/€0 split. */
  paid: { amount: string; period: number; count: number | null } | null;
};

export function apcSummary(apc: ApcFields): ApcSummary {
  // The newest OpenAPC period with an article paid above €0 comes first.
  const newest = apc.apc_stats[0];
  // With the shown price from OpenAPC, apc_price and apc_year are the mean
  // and the period of that newest period.
  const fromOpenapc = apc.apc_source === "openapc";
  const mean = (fromOpenapc ? apc.apc_price : null) ?? newest?.euro_mean ?? null;
  const period = (fromOpenapc ? apc.apc_year : null) ?? newest?.period ?? null;
  const paid =
    mean != null && period != null
      ? { amount: `€${formatApc(mean)}`, period, count: newest?.paid_count ?? null }
      : null;
  const { apc_source: source, apc_price: price } = apc;
  if (source != null && source !== "openapc" && price != null) {
    const originalCurrency = apc.apc_original_currency;
    const originalPrice = apc.apc_original_price;
    return {
      kind: "list",
      source: apcSourceName(source),
      year: apc.apc_year ?? null,
      currency: apc.apc_currency ?? null,
      amount: apcAmount(apc.apc_currency, price),
      original:
        originalCurrency != null && originalPrice != null && originalCurrency !== apc.apc_currency
          ? apcAmount(originalCurrency, originalPrice)
          : null,
      paid,
    };
  }
  const range =
    apc.apc_low != null ? `€${formatApcRange(apc.apc_low, apc.apc_high)}` : (paid?.amount ?? null);
  return {
    kind: range != null ? "paid" : "none",
    source: null,
    year: period ?? null,
    currency: "EUR",
    amount: range,
    original: null,
    paid,
  };
}

/** Range of two euro amounts: "2,000 to 2,500", or "2,000" when they are equal. */
export function formatApcRange(low: number, high: number | null | undefined): string {
  return high != null && high !== low ? `${formatApc(low)} to ${formatApc(high)}` : formatApc(low);
}

/** Why an OpenAPC period lacks exact paid figures; null when they are exact. */
export type ApcRowGap =
  | "legacyMean"
  | "noneAboveZero"
  | "noAmount"
  | "allDealPaid"
  | "partDealPaid";

export function apcRowGap(a: JournalListItem["apc_stats"][number]): ApcRowGap | null {
  // paid_count and zero_count are missing until migration 0005 and the OpenAPC job have run.
  const count = a.paid_count ?? null;
  if (a.euro_mean != null) return count == null ? "legacyMean" : null;
  if (count !== 0) return null;
  const zero = a.zero_count ?? null;
  if (zero == null) return "noneAboveZero";
  if (zero === 0) return "noAmount";
  return zero === a.article_count ? "allDealPaid" : "partDealPaid";
}
