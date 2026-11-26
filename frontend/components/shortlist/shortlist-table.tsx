"use client";

import { X } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import * as React from "react";

import { DealBadge, OaTypeBadge, QuartileBadge } from "@/components/badges";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { useYearRange } from "@/hooks/use-year-filter";
import type { JournalBatchItem } from "@/lib/api";
import { displayPublisherName } from "@/lib/deal-links";
import { apcAmount, formatApc, formatDate, formatInt } from "@/lib/format";
import { csvText, type CsvValue } from "@/lib/shortlist";
import { cn } from "@/lib/utils";

/** One listed journal: a fresh API row, or a saved ISSN-L that the
 * institution's list no longer holds (then `item` is null). */
export type ShortlistRow = {
  issnL: string;
  /** Title as saved in the browser; used when the API has no title or row. */
  savedTitle: string;
  /** Save date from the browser's shortlist; null on a list opened from a share link. */
  addedAt: string | null;
  item: JournalBatchItem | null;
};

const OA_TYPE_KEYS = {
  gold: "facets.oaTypeGold",
  diamond: "facets.oaTypeDiamond",
  generic: "facets.oaTypeGeneric",
  hybrid: "facets.oaTypeHybrid",
  subscription: "facets.oaTypeSubscription",
} as const;
type OaTypeKey = keyof typeof OA_TYPE_KEYS;

const GREEN_OA_KEYS = {
  submitted: "facets.greenOaSubmitted",
  accepted: "facets.greenOaAccepted",
  published: "facets.greenOaPublished",
  none: "facets.greenOaNone",
} as const;
type GreenOaKey = keyof typeof GREEN_OA_KEYS;

const MUTED = "text-[var(--muted-foreground)]";

/** APC as the browse table shows it: an OpenAlex or DOAJ list price, else the
 * range institutions reported to OpenAPC, else nothing. */
export function apcText(item: JournalBatchItem): string | null {
  if ((item.apc_source === "openalex" || item.apc_source === "doaj") && item.apc_price != null) {
    return apcAmount(item.apc_currency, item.apc_price);
  }
  if (item.apc_source === "openapc" && item.apc_low != null) {
    return item.apc_high != null && item.apc_high !== item.apc_low
      ? `€${formatApc(item.apc_low)} to €${formatApc(item.apc_high)}`
      : `€${formatApc(item.apc_low)}`;
  }
  return null;
}

function apcCsvText(item: JournalBatchItem, none: string, paidLabel: string): string {
  const base = apcText(item);
  if (!base) return none;
  return item.apc_source === "openapc" ? `${base} (${paidLabel})` : base;
}

/** Column names and cell wording, shared by the table and the CSV export. */
export interface ShortlistLabels {
  columns: {
    journal: string;
    issnL: string;
    remove: string;
    publisher: string;
    deal: string;
    dealName: string;
    oaType: string;
    apc: string;
    quartile: string;
    works: string;
    doaj: string;
    greenOa: string;
    added: string;
  };
  yes: string;
  no: string;
  none: string;
  paid: string;
  noDeal: string;
  unknownPublisher: string;
  dealFallback: (id: number) => string;
  oaType: (type: string) => string;
  /** A null route means the journal is not in the Jisc Open Policy Finder. */
  greenOa: (route: string | null | undefined) => string;
}

export function useShortlistLabels(): ShortlistLabels {
  const t = useTranslations("shortlist");
  const tc = useTranslations("common");
  const site = useSiteMeta();
  return {
    columns: {
      journal: t("columns.journal"),
      issnL: t("columns.issnL"),
      remove: t("columns.remove"),
      publisher: t("columns.publisher"),
      deal: t("columns.deal"),
      dealName: t("columns.dealName"),
      oaType: t("columns.oaType"),
      apc: t("columns.apc"),
      quartile: t("columns.quartile"),
      works: t("columns.works", { short: site.short || site.name }),
      doaj: t("columns.doaj"),
      greenOa: t("columns.greenOa"),
      added: t("columns.added"),
    },
    yes: t("cells.yes"),
    no: t("cells.no"),
    none: t("cells.none"),
    paid: tc("apc.paidLabel"),
    noDeal: t("cells.noDeal"),
    unknownPublisher: t("cells.unknownPublisher"),
    dealFallback: (id: number) => t("cells.dealFallback", { id }),
    oaType: (type: string) => (type in OA_TYPE_KEYS ? tc(OA_TYPE_KEYS[type as OaTypeKey]) : ""),
    greenOa: (route) =>
      route && route in GREEN_OA_KEYS
        ? tc(GREEN_OA_KEYS[route as GreenOaKey])
        : t("cells.noGreenRouteData"),
  };
}

/** CSV export of the list, in table column order. A journal without an API
 * row carries only its title and ISSN-L. */
export function shortlistCsv(rows: ShortlistRow[], text: ShortlistLabels): string {
  const { columns: c } = text;
  const withAdded = rows.some((row) => row.addedAt !== null);
  const body: CsvValue[][] = rows.map((row) => {
    const { item } = row;
    const title = item?.title ?? row.savedTitle;
    const tail = row.addedAt ? formatDate(row.addedAt) : "";
    if (!item) {
      return [
        title,
        row.issnL,
        text.none,
        text.none,
        "",
        text.none,
        text.none,
        text.none,
        text.none,
        text.none,
        text.none,
        ...(withAdded ? [tail] : []),
      ];
    }
    return [
      title,
      row.issnL,
      displayPublisherName(item.publisher_canonical ?? item.publisher_name) ||
        text.unknownPublisher,
      item.deal_covered ? text.yes : text.no,
      item.deals
        .map((deal) => displayPublisherName(deal.publisher_name) || text.dealFallback(deal.id))
        .join("; "),
      text.oaType(item.oa_type),
      apcCsvText(item, text.none, text.paid),
      item.quartile ?? text.none,
      item.works,
      item.is_in_doaj ? text.yes : text.no,
      text.greenOa(item.green_oa),
      ...(withAdded ? [tail] : []),
    ];
  });
  const header = [
    c.journal,
    c.issnL,
    c.publisher,
    c.deal,
    c.dealName,
    c.oaType,
    c.apc,
    c.quartile,
    c.works,
    c.doaj,
    c.greenOa,
    ...(withAdded ? [c.added] : []),
  ];
  return csvText(header, body);
}

/** Table cell that names its column below `md`, where every row stacks into
 * one card per journal. */
function Cell({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <td
      data-label={label}
      className={cn(
        "grid grid-cols-[6.5rem_minmax(0,1fr)] items-baseline gap-x-3 gap-y-1 border-b border-[var(--border)] px-4 py-2.5 last:border-b-0 md:table-cell md:border-0 md:px-3 md:py-2.5",
        "before:content-[attr(data-label)] before:text-xs before:font-medium before:text-[var(--muted-foreground)] md:before:hidden",
        className,
      )}
    >
      {children}
    </td>
  );
}

export function ShortlistTable({
  rows,
  inst,
  onRemove,
}: {
  rows: ShortlistRow[];
  inst: string;
  /** Present on the reader's own shortlist only. */
  onRemove?: (row: ShortlistRow) => void;
}) {
  const th = useTranslations("home");
  const site = useSiteMeta();
  const { year_from, year_to } = useYearRange();
  const text = useShortlistLabels();
  const { columns: c } = text;
  const withAdded = rows.some((row) => row.addedAt !== null);
  const head =
    "h-10 whitespace-nowrap px-3 text-left align-middle text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]";

  return (
    <div className="md:overflow-x-auto">
      <table className="shortlist-table w-full text-sm">
        {/* Visually hidden below md: the cells carry their own column names. */}
        <thead className="sr-only md:not-sr-only">
          <tr className="border-b border-[var(--border)]">
            <th scope="col" className={cn(head, "min-w-56")}>
              {c.journal}
            </th>
            <th scope="col" className={head}>
              {c.publisher}
            </th>
            <th scope="col" className={head}>
              {c.deal}
            </th>
            <th scope="col" className={head}>
              {c.oaType}
            </th>
            <th scope="col" className={head} title={th("table.apcTooltip")}>
              {c.apc}
            </th>
            <th scope="col" className={head}>
              {c.quartile}
            </th>
            <th
              scope="col"
              className={head}
              title={th("table.worksTitle", {
                inst: site.short,
                windowStart: site.windowStart === undefined ? "none" : String(site.windowStart),
                yearRange: year_from === undefined ? "none" : `${year_from} to ${year_to}`,
              })}
            >
              {c.works}
            </th>
            <th scope="col" className={head}>
              {c.doaj}
            </th>
            <th scope="col" className={head}>
              {c.greenOa}
            </th>
            {withAdded && (
              <th scope="col" className={head}>
                {c.added}
              </th>
            )}
            {onRemove && (
              <th scope="col" className={cn(head, "shortlist-screen w-10")}>
                <span className="sr-only">{c.remove}</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody className="flex flex-col gap-3 md:table-row-group">
          {rows.map((row) => (
            <JournalRow
              key={row.issnL}
              row={row}
              inst={inst}
              text={text}
              withAdded={withAdded}
              onRemove={onRemove}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function JournalRow({
  row,
  inst,
  text,
  withAdded,
  onRemove,
}: {
  row: ShortlistRow;
  inst: string;
  text: ShortlistLabels;
  withAdded: boolean;
  onRemove?: (row: ShortlistRow) => void;
}) {
  const t = useTranslations("shortlist");
  const tc = useTranslations("common");
  const th = useTranslations("home");
  const site = useSiteMeta();
  const { columns: c } = text;
  const { item } = row;
  const title = item?.title ?? row.savedTitle;
  const apc = item ? apcText(item) : null;
  const greenRoute = item?.green_oa;
  const greenTitle =
    greenRoute && greenRoute in GREEN_OA_KEYS
      ? tc(`facets.titleGreenOa${greenRoute[0].toUpperCase()}${greenRoute.slice(1)}`)
      : undefined;

  return (
    <tr className="relative block rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] md:table-row md:border-x-0 md:border-t-0 md:bg-transparent md:last:border-b-0">
      <Cell
        label={c.journal}
        className={cn(
          "block bg-[var(--muted)]/60 px-4 py-3 before:hidden md:bg-transparent md:py-2.5",
          onRemove && "pr-12",
        )}
      >
        {item ? (
          <Link
            href={`/${inst}/journals/${encodeURIComponent(item.issn_l)}`}
            className="font-medium text-[var(--foreground)] underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
          >
            {title}
          </Link>
        ) : (
          <span
            className={cn("font-medium", MUTED)}
            title={t("cells.unavailableTitle", { institution: site.name })}
          >
            {title}
          </span>
        )}
        {title !== row.issnL && <span className={cn("block text-xs", MUTED)}>{row.issnL}</span>}
        {!item && (
          <span className="block text-xs font-medium text-[var(--primary-text)]">
            {t("cells.unavailable")}
          </span>
        )}
      </Cell>
      <Cell label={c.publisher}>
        <span>
          {item
            ? (displayPublisherName(item.publisher_canonical ?? item.publisher_name) ??
              text.unknownPublisher)
            : text.none}
        </span>
      </Cell>
      <Cell label={c.deal}>
        {!item ? (
          <span className={MUTED}>{text.none}</span>
        ) : !item.deal_covered ? (
          <span className={MUTED}>{text.noDeal}</span>
        ) : (
          <span className="inline-flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 align-middle">
            <DealBadge covered capped={item.deal_cap_reached} />
            {item.deals.length > 0 ? (
              item.deals.map((deal) => (
                <Link
                  key={deal.id}
                  href={`/${inst}/deals#deal-${deal.id}`}
                  className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                  title={deal.duration_text ?? undefined}
                >
                  {displayPublisherName(deal.publisher_name) || text.dealFallback(deal.id)}
                </Link>
              ))
            ) : (
              <span>{tc("facets.dealCovered")}</span>
            )}
          </span>
        )}
      </Cell>
      <Cell label={c.oaType}>
        {item ? (
          <OaTypeBadge oaType={item.oa_type} isOa={item.is_oa} />
        ) : (
          <span className={MUTED}>{text.none}</span>
        )}
      </Cell>
      <Cell label={c.apc} className="whitespace-nowrap">
        {apc ? (
          <span
            className="inline-flex items-center gap-1"
            title={
              item?.apc_source === "openalex" || item?.apc_source === "doaj"
                ? th("table.listPriceTitle")
                : th("table.apcTooltip")
            }
          >
            <span className="tabular-nums">{apc}</span>
            {item?.apc_source === "openapc" && (
              <span className="text-[11px] text-[var(--muted-foreground)]">
                {tc("apc.paidLabel")}
              </span>
            )}
          </span>
        ) : (
          <span className={cn("tabular-nums", MUTED)}>{text.none}</span>
        )}
      </Cell>
      <Cell label={c.quartile} className="whitespace-nowrap">
        {item?.quartile ? (
          <QuartileBadge quartile={item.quartile} />
        ) : (
          <span className={MUTED}>{text.none}</span>
        )}
      </Cell>
      <Cell label={c.works} className="whitespace-nowrap">
        <span className="tabular-nums">{item ? formatInt(item.works) : text.none}</span>
      </Cell>
      <Cell label={c.doaj} className="whitespace-nowrap">
        <span
          title={
            item ? tc(item.is_in_doaj ? "facets.titleDoajYes" : "facets.titleDoajNo") : undefined
          }
        >
          {item ? (item.is_in_doaj ? text.yes : text.no) : text.none}
        </span>
      </Cell>
      <Cell label={c.greenOa} className="whitespace-nowrap">
        <span title={greenTitle}>
          {item ? text.greenOa(greenRoute) : <span className={MUTED}>{text.none}</span>}
        </span>
      </Cell>
      {withAdded && (
        <Cell label={c.added} className="whitespace-nowrap">
          <span>{row.addedAt ? formatDate(row.addedAt) : text.none}</span>
        </Cell>
      )}
      {onRemove && (
        <Cell
          label=""
          className="shortlist-screen absolute top-2.5 right-4 grid-cols-1 gap-0 border-b-0 px-0 py-0 before:hidden md:static md:table-cell md:justify-items-end md:text-right"
        >
          <button
            type="button"
            onClick={() => onRemove(row)}
            aria-label={t("actions.remove", { title })}
            title={t("actions.remove", { title })}
            className="relative inline-flex size-6 items-center justify-center rounded-[var(--radius)] text-[var(--muted-foreground)] before:absolute before:-inset-[10px] hover:bg-[var(--muted)] hover:text-[var(--destructive)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
          >
            <X aria-hidden className="size-4" />
          </button>
        </Cell>
      )}
    </tr>
  );
}
