"use client";

import { ArrowDown, ArrowUp } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";

import { useCollabLabels } from "@/components/collaborations/labels";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { CollaborationPartner, CollaborationSearchParams, CollaborationSort } from "@/lib/api";

export type Sorting = { sort: CollaborationSort; dir: "asc" | "desc" };

/** The sort in force: the one in the URL, or shared works from high to low. */
export function readSorting(p: CollaborationSearchParams): Sorting {
  if (!p.sort) return { sort: "works", dir: "desc" };
  return { sort: p.sort, dir: p.dir ?? (p.sort === "name" ? "asc" : "desc") };
}

type Column = { key: CollaborationSort; label: string; numeric?: boolean };

function SortHead({
  column,
  sorting,
  onSort,
}: {
  column: Column;
  sorting: Sorting;
  onSort: (next: Sorting) => void;
}) {
  const t = useTranslations("collaborations");
  const active = sorting.sort === column.key;
  // A column sorts first in its natural order; selecting it again reverses that.
  const next = active
    ? { sort: column.key, dir: sorting.dir === "asc" ? ("desc" as const) : ("asc" as const) }
    : { sort: column.key, dir: column.key === "name" ? ("asc" as const) : ("desc" as const) };
  const Icon = active ? (sorting.dir === "asc" ? ArrowUp : ArrowDown) : null;
  return (
    <TableHead
      aria-sort={active ? (sorting.dir === "asc" ? "ascending" : "descending") : "none"}
      className={column.numeric ? "text-right" : undefined}
    >
      <button
        type="button"
        onClick={() => onSort(next)}
        title={t("table.sort", { column: column.label })}
        className="inline-flex items-center gap-1 rounded-[var(--radius)] text-left hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
      >
        {column.label}
        {Icon && <Icon aria-hidden className="size-3.5" />}
      </button>
    </TableHead>
  );
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
  /** Query string of the list filters, "" when none is set. */
  query: string;
  /** A new page is loading and these rows are the previous result. */
  pending?: boolean;
}) {
  const t = useTranslations("collaborations");
  const labels = useCollabLabels();
  const linkClass =
    "font-medium underline decoration-dotted underline-offset-2 hover:decoration-solid";
  return (
    <Table className={pending ? "opacity-60" : undefined} aria-busy={pending || undefined}>
      <TableHeader>
        <TableRow>
          <SortHead
            column={{ key: "name", label: t("table.partner") }}
            sorting={sorting}
            onSort={onSort}
          />
          <TableHead>{t("table.type")}</TableHead>
          <TableHead>{t("table.country")}</TableHead>
          <SortHead
            column={{ key: "works", label: t("table.works"), numeric: true }}
            sorting={sorting}
            onSort={onSort}
          />
          <SortHead
            column={{ key: "corresponding_works", label: t("table.corresponding"), numeric: true }}
            sorting={sorting}
            onSort={onSort}
          />
          <TableHead className="text-right">{t("table.authorships")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.length === 0 ? (
          <TableRow>
            <TableCell colSpan={6} className="text-[var(--muted-foreground)]">
              {t("table.empty")}
            </TableCell>
          </TableRow>
        ) : (
          items.map((p) => (
            <TableRow key={p.ror}>
              <TableCell>
                <Link
                  href={`/${inst}/collaborations/${encodeURIComponent(p.ror)}${query}`}
                  className={linkClass}
                >
                  {p.name}
                </Link>
                {p.parent_name && (
                  <span className="block text-xs text-[var(--muted-foreground)]">
                    {t("table.partOf", { name: p.parent_name })}
                  </span>
                )}
                {p.sources.length === 1 && p.sources[0] === "openaire" && (
                  <span className="block text-xs text-[var(--muted-foreground)]">
                    {t("table.viaOpenaire")}
                  </span>
                )}
              </TableCell>
              <TableCell className="text-[var(--muted-foreground)]">
                {p.org_type ? labels.orgType(p.org_type) : "—"}
              </TableCell>
              <TableCell className="text-[var(--muted-foreground)]">
                {p.country_code ? labels.region(p.country_code) : "—"}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {p.works.toLocaleString("en")}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {p.corresponding_works.toLocaleString("en")}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {p.authorships.toLocaleString("en")}
              </TableCell>
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  );
}
