"use client";

import { ArrowDown, ArrowUp } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";

import { orgTypeCssVar, useCollabLabels } from "@/components/collaborations/labels";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useSiteMeta } from "@/hooks/use-site-meta";
import type { CollaborationPartner, CollaborationSearchParams, CollaborationSort } from "@/lib/api";
import { cn } from "@/lib/utils";

export type Sorting = { sort: CollaborationSort; dir: "asc" | "desc" };

/** The sort in force: the one in the URL, or shared works from high to low. */
export function readSorting(p: CollaborationSearchParams): Sorting {
  if (!p.sort) return { sort: "works", dir: "desc" };
  return { sort: p.sort, dir: p.dir ?? (p.sort === "name" ? "asc" : "desc") };
}

type Column = { key: CollaborationSort; label: string; numeric?: boolean };

function SortButton({
  column,
  sorting,
  onSort,
  chip = false,
}: {
  column: Column;
  sorting: Sorting;
  onSort: (next: Sorting) => void;
  /** Bordered look for the chip row above the stacked list on phones. */
  chip?: boolean;
}) {
  const t = useTranslations("collaborations");
  const active = sorting.sort === column.key;
  const next = active
    ? { sort: column.key, dir: sorting.dir === "asc" ? ("desc" as const) : ("asc" as const) }
    : { sort: column.key, dir: column.key === "name" ? ("asc" as const) : ("desc" as const) };
  const Icon = active ? (sorting.dir === "asc" ? ArrowUp : ArrowDown) : null;
  return (
    <button
      type="button"
      onClick={() => onSort(next)}
      title={t("table.sort", { column: column.label })}
      aria-pressed={chip ? active : undefined}
      className={cn(
        "inline-flex min-h-11 min-w-11 items-center gap-1 rounded-[var(--radius)] text-left hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] min-[1024px]:min-h-0 min-[1024px]:min-w-0",
        chip &&
          "border px-2.5 py-2 text-xs font-medium " +
            (active
              ? "border-[var(--primary)] bg-[var(--brand-tint-bg)] text-[var(--primary-text)]"
              : "border-[var(--input)] bg-[var(--card)] text-[var(--muted-foreground)]"),
      )}
    >
      {column.label}
      {Icon && <Icon aria-hidden className="size-3.5" />}
    </button>
  );
}

function SortHead({
  column,
  sorting,
  onSort,
}: {
  column: Column;
  sorting: Sorting;
  onSort: (next: Sorting) => void;
}) {
  const active = sorting.sort === column.key;
  return (
    <TableHead
      aria-sort={active ? (sorting.dir === "asc" ? "ascending" : "descending") : "none"}
      className={column.numeric ? "text-right" : undefined}
    >
      <SortButton column={column} sorting={sorting} onSort={onSort} />
    </TableHead>
  );
}

function fmtShare(share: number | null | undefined): string | null {
  if (share == null) return null;
  const pct = share * 100;
  return pct < 0.1 && pct > 0 ? "<0.1%" : `${pct.toFixed(1).replace(/\.0$/, "")}%`;
}

/** The paged partner list. Each row opens the partner, carrying the list
 * filters along in `query`. */
export function PartnerTable({
  items,
  sorting,
  onSort,
  inst,
  query,
  pending,
}: {
  items: CollaborationPartner[];
  sorting: Sorting;
  onSort: (next: Sorting) => void;
  inst: string;
  query: string;
  pending?: boolean;
}) {
  const t = useTranslations("collaborations");
  const labels = useCollabLabels();
  const site = useSiteMeta();
  const linkClass =
    "inline-flex min-h-11 items-center font-medium underline-offset-2 hover:text-[var(--primary-text)] hover:underline min-[1024px]:min-h-0";

  // The same five columns can be sorted from the table header and from the
  // chip row above the stacked list.
  const sortColumns: Column[] = [
    { key: "name", label: t("table.partner") },
    { key: "works", label: t("table.works"), numeric: true },
    { key: "oa_share", label: t("table.oa"), numeric: true },
    {
      key: "home_corresponding_works",
      label: t("table.homeCorr", { inst: site.short }),
      numeric: true,
    },
    { key: "corresponding_works", label: t("table.corresponding"), numeric: true },
  ];
  const empty = items.length === 0;

  return (
    <div className={pending ? "opacity-60" : undefined} aria-busy={pending || undefined}>
      {/* Stacked rows on narrow viewports: seven columns would push the
          counts off-screen behind horizontal scrolling. */}
      <div className="md:hidden">
        <div
          role="group"
          aria-label={t("table.sortGroup")}
          className="flex flex-wrap items-center gap-1.5 border-b border-[var(--border)] pb-3"
        >
          {sortColumns.map((column) => (
            <SortButton key={column.key} column={column} sorting={sorting} onSort={onSort} chip />
          ))}
        </div>
        {empty ? (
          <p className="py-6 text-[var(--muted-foreground)]">{t("table.empty")}</p>
        ) : (
          <ul aria-label={t("table.title")} className="pt-3">
            {items.map((p) => {
              const shareText = fmtShare(p.share);
              const oaPct = p.oa_share != null ? Math.round(p.oa_share * 100) : null;
              return (
                <li
                  key={p.ror}
                  className="border-b border-[var(--border)] py-3 first:pt-0 last:border-0 last:pb-0"
                >
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                    <Link
                      href={`/${inst}/collaborations/${encodeURIComponent(p.ror)}${query}`}
                      className={linkClass}
                    >
                      {p.name}
                    </Link>
                    {p.shares_deals && (
                      <Badge variant="muted" className="text-[10px] font-normal">
                        {t("table.sharesDeals")}
                      </Badge>
                    )}
                  </div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-[var(--muted-foreground)]">
                    {p.org_type && (
                      <span className="inline-flex items-center gap-1.5">
                        <span
                          aria-hidden
                          className="inline-block size-2.5 shrink-0 rounded-full"
                          style={{ backgroundColor: orgTypeCssVar(p.org_type) }}
                        />
                        {labels.orgType(p.org_type)}
                      </span>
                    )}
                    {p.country_code && <span>{labels.region(p.country_code)}</span>}
                    {p.city && <span>{p.city}</span>}
                    {p.merged_count > 0 && (
                      <span>{t("table.mergedSubunits", { count: p.merged_count })}</span>
                    )}
                    {p.parent_name && <span>{t("table.partOf", { name: p.parent_name })}</span>}
                    {p.sources.length === 1 && p.sources[0] === "openaire" && (
                      <span>{t("table.viaOpenaire")}</span>
                    )}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs tabular-nums text-[var(--muted-foreground)]">
                    <span className="font-medium text-[var(--foreground)]">
                      {t("map.point", { works: p.works })}
                      {shareText && ` (${shareText})`}
                    </span>
                    {oaPct != null && <span>{t("map.oaPct", { pct: oaPct })}</span>}
                    <span>
                      {t("map.corrMeta", {
                        home: (p.home_corresponding_works ?? 0).toLocaleString("en"),
                        inst: site.short,
                        partner: p.corresponding_works.toLocaleString("en"),
                      })}
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <SortHead column={sortColumns[0]} sorting={sorting} onSort={onSort} />
              <TableHead>{t("table.type")}</TableHead>
              <TableHead>{t("table.country")}</TableHead>
              {sortColumns.slice(1).map((column) => (
                <SortHead key={column.key} column={column} sorting={sorting} onSort={onSort} />
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {empty ? (
              <TableRow>
                <TableCell colSpan={7} className="text-[var(--muted-foreground)]">
                  {t("table.empty")}
                </TableCell>
              </TableRow>
            ) : (
              items.map((p) => {
                const shareText = fmtShare(p.share);
                const oaPct = p.oa_share != null ? `${Math.round(p.oa_share * 100)}%` : "—";
                return (
                  <TableRow key={p.ror}>
                    <TableCell>
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                        <Link
                          href={`/${inst}/collaborations/${encodeURIComponent(p.ror)}${query}`}
                          className={linkClass}
                        >
                          {p.name}
                        </Link>
                        {p.shares_deals && (
                          <Badge variant="muted" className="text-[10px] font-normal">
                            {t("table.sharesDeals")}
                          </Badge>
                        )}
                      </div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-[var(--muted-foreground)]">
                        {p.city && <span>{p.city}</span>}
                        {p.merged_count > 0 && (
                          <span>{t("table.mergedSubunits", { count: p.merged_count })}</span>
                        )}
                        {p.parent_name && <span>{t("table.partOf", { name: p.parent_name })}</span>}
                        {p.sources.length === 1 && p.sources[0] === "openaire" && (
                          <span>{t("table.viaOpenaire")}</span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-[var(--muted-foreground)]">
                      {p.org_type ? (
                        <span className="inline-flex items-center gap-1.5">
                          <span
                            aria-hidden
                            className="inline-block size-2.5 shrink-0 rounded-full"
                            style={{ backgroundColor: orgTypeCssVar(p.org_type) }}
                          />
                          {labels.orgType(p.org_type)}
                        </span>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-[var(--muted-foreground)]">
                      {p.country_code ? labels.region(p.country_code) : "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      <span className="font-medium">{p.works.toLocaleString("en")}</span>
                      {shareText && (
                        <span className="ml-1.5 text-xs text-[var(--muted-foreground)]">
                          ({shareText})
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{oaPct}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {(p.home_corresponding_works ?? 0).toLocaleString("en")}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {p.corresponding_works.toLocaleString("en")}
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
