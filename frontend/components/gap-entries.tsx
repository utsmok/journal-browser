"use client";

import { ChevronDown, ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import * as React from "react";

import { OaStatusChip, PartChip, PureMatchBadge, PureRegisteredBadge } from "@/components/badges";
import { UtAuthorLine } from "@/components/ut-author-line";
import { Badge } from "@/components/ui/badge";
import { External } from "@/components/journal/shared";
import { TableCell, TableRow } from "@/components/ui/table";
import { encodeNamePath } from "@/lib/api";
import type { GapEntry, GapGroup, GapWorkRow } from "@/lib/gap-entries";
import { cn } from "@/lib/utils";
import { workTypeLabel } from "@/lib/work-type";

/**
 * Renderers for grouped CRIS-gap entries (GapSingle | GapGroup): the
 * `<ul>` list used by the publisher, journal and orgunit gap cards, and
 * the row set used by the author not-in-Pure table. Groups render their
 * parent with a Pure-status badge and an "N parts" foldout; parts lose
 * the PartChip because the group hierarchy already says "part of".
 *
 * The work-row cells below (doiHref, WorkLinks, WorkTypeCell) are shared
 * with the author page's other tables.
 */

export function doiHref(doi: string | null): string | null {
  if (!doi) return null;
  return /^https?:\/\//.test(doi) ? doi : `https://doi.org/${doi}`;
}

/** Small per-row verification links: DOI, OpenAlex, Pure — whichever
 * exist; an empty row (no DOI, no portal record) shows a dash. */
export function WorkLinks({
  doi,
  openalexUrl,
  pureUrl,
}: {
  doi: string | null;
  openalexUrl?: string | null;
  pureUrl?: string | null;
}) {
  const links = [
    doi ? { label: "DOI", href: doiHref(doi) ?? "" } : null,
    openalexUrl ? { label: "OpenAlex", href: openalexUrl } : null,
    pureUrl ? { label: "Pure", href: pureUrl } : null,
  ].filter((l): l is { label: string; href: string } => l !== null);
  if (links.length === 0) return <span className="text-[var(--muted-foreground)]">—</span>;
  return (
    <span className="flex flex-wrap gap-x-2 gap-y-0.5 text-xs">
      {links.map((l) => (
        <a
          key={l.label}
          href={l.href}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[var(--primary-text)] underline-offset-2 hover:underline"
        >
          {l.label}
        </a>
      ))}
    </span>
  );
}

/** Neutral small type badge; null renders a dash so columns stay aligned. */
export function WorkTypeCell({ workType }: { workType?: string | null }) {
  const tc = useTranslations("common");
  if (!workType) return <span className="text-[var(--muted-foreground)]">—</span>;
  return (
    <Badge variant="outline" className="font-normal text-[11px] text-[var(--muted-foreground)]">
      {workTypeLabel(tc, workType)}
    </Badge>
  );
}

/** "N parts" disclosure for a group entry: the collapsed state shows the
 * part count, expanding reveals the part rows beneath the header. */
export function PartsToggle({
  open,
  onToggle,
  count,
  controlsId,
  className,
}: {
  open: boolean;
  onToggle: () => void;
  count: number;
  /** id of the revealed region, for aria-controls in list layouts. */
  controlsId?: string;
  className?: string;
}) {
  const t = useTranslations("common");
  return (
    <button
      type="button"
      aria-expanded={open}
      aria-controls={controlsId}
      onClick={onToggle}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-[var(--radius)] border border-[var(--input)] px-2 py-0.5 text-xs font-normal text-[var(--muted-foreground)] hover:text-[var(--primary-text)]",
        className,
      )}
    >
      {t("workParts.partsCount", { count })}
      <ChevronDown
        aria-hidden
        className={cn("size-3.5 transition-transform", !open && "-rotate-90")}
      />
    </button>
  );
}

/** Title line shared by singles and group parents: DOI link when known,
 * plain text otherwise. */
function GapTitle({ name, doi }: { name: string; doi?: string | null }) {
  const href = doi ? `https://doi.org/${doi}` : null;
  return href ? (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex min-w-0 w-full min-[480px]:w-auto min-[480px]:flex-1 items-center gap-1 font-medium text-[var(--primary-text)] underline-offset-2 hover:underline"
    >
      {name} <ExternalLink aria-hidden className="size-3.5 shrink-0" />
    </a>
  ) : (
    <span className="min-w-0 w-full min-[480px]:w-auto min-[480px]:flex-1 font-medium">{name}</span>
  );
}

/** One gap work as a flex list row: title, year, venue, and the badge
 * run. Group parts pass `withPartChip={false}` — the group hierarchy
 * already says "part of". */
function GapWorkRowBody({
  w,
  inst,
  untitledLabel,
  showJournalLink = false,
  showUtAuthors = false,
  withPartChip = true,
}: {
  w: GapWorkRow;
  inst: string;
  untitledLabel: string;
  showJournalLink?: boolean;
  showUtAuthors?: boolean;
  withPartChip?: boolean;
}) {
  const tc = useTranslations("common");
  return (
    <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
      <GapTitle name={w.title ?? w.doi ?? untitledLabel} doi={w.doi} />
      {w.year != null && (
        <span className="tabular-nums text-[var(--muted-foreground)]">{w.year}</span>
      )}
      {w.venue && <span className="min-w-0 text-xs text-[var(--muted-foreground)]">{w.venue}</span>}
      {showJournalLink && w.journal_issn_l && (
        <Link
          href={`/${inst}/journals/${w.journal_issn_l}`}
          className="text-xs underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
        >
          {w.journal_title ?? w.journal_issn_l}
        </Link>
      )}
      {w.work_type && <span className="text-xs">{workTypeLabel(tc, w.work_type)}</span>}
      {withPartChip && <PartChip isPart={w.is_part ?? false} parents={w.parent_works ?? []} />}
      <PureMatchBadge match={w.pure_match} url={w.pure_match_url} />
      <OaStatusChip status={w.oa_status} />
      {showUtAuthors && <UtAuthorLine authors={w.ut_authors ?? []} />}
    </div>
  );
}

/** One group entry: parent header with Pure-status badge and parts
 * foldout; parts keep most-recent-first order without the PartChip.
 * Parent name and id can be absent while the parent backfill is
 * pending, so both fall back. */
function GapGroupItem({
  entry,
  inst,
  untitledLabel,
  showJournalLinks,
  showUtAuthors,
}: {
  entry: GapGroup;
  inst: string;
  untitledLabel: string;
  showJournalLinks: boolean;
  showUtAuthors: boolean;
}) {
  const [open, setOpen] = React.useState(false);
  const tc = useTranslations("common");
  const parts = entry.parts ?? [];
  const partsId = `gap-parts-${entry.parent.w_id ?? entry.parent.name ?? "unknown"}`;
  return (
    <li className="py-2 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
        <GapTitle name={entry.parent.name ?? untitledLabel} doi={entry.parent.doi} />
        {entry.parent.work_type && (
          <span className="text-xs">{workTypeLabel(tc, entry.parent.work_type)}</span>
        )}
        <PureRegisteredBadge registered={entry.parent.pure_registered ?? null} />
        <PartsToggle
          open={open}
          onToggle={() => setOpen((o) => !o)}
          count={entry.parts_total ?? parts.length}
          controlsId={partsId}
        />
      </div>
      {open && (
        <ul id={partsId} className="mt-1 space-y-1.5 border-l border-[var(--border)] pl-3">
          {parts.map((p, i) => (
            <li key={p.openalex_id ?? p.doi ?? `part-${i}`}>
              <GapWorkRowBody
                w={p}
                inst={inst}
                untitledLabel={untitledLabel}
                showJournalLink={showJournalLinks}
                showUtAuthors={showUtAuthors}
                withPartChip={false}
              />
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

/** Grouped gap list for the publisher, journal and orgunit gap cards:
 * singles and parent groups in the server's newest-year order. The
 * surface flags keep each card's previous row content. */
export function GapEntryList({
  entries,
  inst,
  untitledLabel,
  showJournalLinks = false,
  showUtAuthors = false,
}: {
  entries: GapEntry[];
  inst: string;
  untitledLabel: string;
  showJournalLinks?: boolean;
  showUtAuthors?: boolean;
}) {
  return (
    <ul className="divide-y divide-[var(--border)]">
      {entries.map((entry, i) =>
        entry.kind === "group" ? (
          <GapGroupItem
            key={entry.parent.w_id ?? entry.parent.name ?? `group-${i}`}
            entry={entry}
            inst={inst}
            untitledLabel={untitledLabel}
            showJournalLinks={showJournalLinks}
            showUtAuthors={showUtAuthors}
          />
        ) : (
          <li
            key={entry.openalex_id ?? entry.doi ?? `single-${i}`}
            className="py-2 first:pt-0 last:pb-0"
          >
            <GapWorkRowBody
              w={entry}
              inst={inst}
              untitledLabel={untitledLabel}
              showJournalLink={showJournalLinks}
              showUtAuthors={showUtAuthors}
              withPartChip
            />
          </li>
        ),
      )}
    </ul>
  );
}

/** One gap work as an author-table row. Group parts pass
 * `inGroup` — they drop the PartChip and indent under the parent. */
function GapTableRow({
  w,
  inst,
  inGroup = false,
}: {
  w: GapWorkRow;
  inst: string;
  inGroup?: boolean;
}) {
  const t = useTranslations("authors");
  const href = doiHref(w.doi ?? null) ?? w.openalex_url ?? null;
  return (
    <TableRow>
      <TableCell className="whitespace-nowrap tabular-nums">{w.year}</TableCell>
      <TableCell className={cn("min-w-0 font-medium", inGroup && "pl-6")}>
        {href ? (
          <External href={href}>{w.title ?? w.doi ?? w.openalex_id}</External>
        ) : (
          (w.title ?? t("detail.untitled"))
        )}
        <Badge
          variant="outline"
          className="ml-2 font-normal text-[11px] text-[var(--muted-foreground)]"
          title={t("detail.oaOnlyTitle")}
        >
          {t("detail.oaOnlyBadge")}
        </Badge>
        <PureMatchBadge match={w.pure_match} url={w.pure_match_url} />
        <UtAuthorLine authors={w.ut_authors ?? []} />
      </TableCell>
      <TableCell>
        {w.journal_issn_l ? (
          <Link
            href={`/${inst}/journals/${w.journal_issn_l}`}
            className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
          >
            {w.journal_title || w.journal_issn_l}
          </Link>
        ) : w.journal_title ? (
          <span>{w.journal_title}</span>
        ) : (
          <span className="text-[var(--muted-foreground)]">—</span>
        )}
      </TableCell>
      <TableCell>
        {w.publisher_name ? (
          <Link
            href={`/${inst}/publisher/${encodeNamePath(w.publisher_name)}`}
            className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
          >
            {w.publisher_name}
          </Link>
        ) : (
          <span className="text-[var(--muted-foreground)]">—</span>
        )}
      </TableCell>
      <TableCell>
        <WorkTypeCell workType={w.work_type} />
        {!inGroup && <PartChip isPart={w.is_part ?? false} parents={w.parent_works ?? []} />}
      </TableCell>
      <TableCell>
        <OaStatusChip status={w.oa_status} />
      </TableCell>
      <TableCell>
        <WorkLinks doi={w.doi ?? null} openalexUrl={w.openalex_url} />
      </TableCell>
    </TableRow>
  );
}

/** A group as an expandable row set: one parent row (newest part year in
 * the year column, Pure-status badge and foldout in the title column,
 * dashes where the parent carries no data), then the part rows while
 * expanded. Stays inside the surrounding TableBody. */
function GapGroupRows({ entry, inst }: { entry: GapGroup; inst: string }) {
  const t = useTranslations("authors");
  const [open, setOpen] = React.useState(false);
  const parent = entry.parent;
  const href = doiHref(parent.doi ?? null);
  const parts = entry.parts ?? [];
  // Parts are most-recent first, so the first part carries the year the
  // group sorts under.
  const newestYear = parts[0]?.year;
  return (
    <>
      <TableRow>
        <TableCell className="whitespace-nowrap tabular-nums">{newestYear}</TableCell>
        <TableCell className="min-w-0 font-medium">
          {href ? (
            <External href={href}>{parent.name ?? t("detail.untitled")}</External>
          ) : (
            (parent.name ?? t("detail.untitled"))
          )}
          <PureRegisteredBadge registered={parent.pure_registered ?? null} className="ml-2" />
          <PartsToggle
            open={open}
            onToggle={() => setOpen((o) => !o)}
            count={entry.parts_total ?? parts.length}
            className="ml-2"
          />
        </TableCell>
        <TableCell>
          <span className="text-[var(--muted-foreground)]">—</span>
        </TableCell>
        <TableCell>
          <span className="text-[var(--muted-foreground)]">—</span>
        </TableCell>
        <TableCell>
          <WorkTypeCell workType={parent.work_type} />
        </TableCell>
        <TableCell>
          <span className="text-[var(--muted-foreground)]">—</span>
        </TableCell>
        <TableCell>
          <WorkLinks doi={parent.doi ?? null} />
        </TableCell>
      </TableRow>
      {open &&
        parts.map((p, i) => (
          <GapTableRow key={p.openalex_id ?? p.doi ?? `part-${i}`} w={p} inst={inst} inGroup />
        ))}
    </>
  );
}

/** Row set for the author not-in-Pure table: singles as plain rows,
 * groups as a parent row with expandable part rows. Render inside the
 * existing <TableBody>. */
export function GapEntryTableRows({ entries, inst }: { entries: GapEntry[]; inst: string }) {
  return (
    <>
      {entries.map((entry, i) =>
        entry.kind === "group" ? (
          <GapGroupRows
            key={entry.parent.w_id ?? entry.parent.name ?? `group-${i}`}
            entry={entry}
            inst={inst}
          />
        ) : (
          <GapTableRow
            key={entry.openalex_id ?? entry.doi ?? `single-${i}`}
            w={entry}
            inst={inst}
          />
        ),
      )}
    </>
  );
}
