/** Euro amounts for APC displays: rounded, locale-grouped, no decimals. */
export function formatEur(n: number): string {
  return Math.round(n).toLocaleString("en");
}
