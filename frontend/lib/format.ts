import type { JournalListItem } from "@/lib/api";

/** Euro amounts for APC displays: rounded, locale-grouped, no decimals. */
export function formatEur(n: number): string {
  return Math.round(n).toLocaleString("en");
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
      return `${s.period}: ${range} EUR · ${s.article_count} article${s.article_count === 1 ? "" : "s"} · mean ${formatApc(s.euro_mean ?? 0)}`;
    })
    .join("\n");
}

/** APC display for one journal: OpenAlex list price, else OpenAPC range. */
export function journalApcText(j: JournalListItem): string | null {
  if (j.apc_source === "openalex" && j.apc_price != null) return `${formatEur(j.apc_price)} €`;
  if (j.apc_source === "openapc" && j.apc_low != null)
    return j.apc_high != null && j.apc_high !== j.apc_low
      ? `${formatEur(j.apc_low)}–${formatEur(j.apc_high)} €`
      : `${formatEur(j.apc_low)} €`;
  return null;
}
