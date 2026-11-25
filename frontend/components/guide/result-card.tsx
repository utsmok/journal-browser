"use client";

import { AlertTriangle, ArrowRight, CheckCircle2, ChevronDown, Info } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import * as React from "react";

import { DealBadge, FunderFitBadge, OaTypeBadge, QuartileBadge } from "@/components/badges";
import { ShortlistToggle } from "@/components/shortlist/shortlist-toggle";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { encodeNamePath, type RecommendedJournal, type RecommendReason } from "@/lib/api";
import { formatInt } from "@/lib/format";
import { cn } from "@/lib/utils";

function ReasonIcon({ tone }: { tone: RecommendReason["tone"] }) {
  if (tone === "positive") {
    return (
      <CheckCircle2
        aria-hidden
        className="mt-0.5 size-4 shrink-0 text-emerald-700 dark:text-emerald-400"
      />
    );
  }
  if (tone === "warning") {
    return (
      <AlertTriangle
        aria-hidden
        className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400"
      />
    );
  }
  return <Info aria-hidden className="mt-0.5 size-4 shrink-0 text-[var(--muted-foreground)]" />;
}

function SimilarityMeter({ similarity }: { similarity: number }) {
  const t = useTranslations("guide");
  const pct = Math.max(1, Math.min(100, Math.round(similarity * 100)));
  return (
    <div className="flex items-center gap-2.5">
      <div aria-hidden className="h-2 w-24 overflow-hidden rounded-full bg-[var(--muted)] sm:w-28">
        <div
          className="guide-bar-fill h-full rounded-full bg-[var(--primary)]"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs font-semibold tabular-nums text-[var(--foreground)]">
        {t("results.topicMatch", { percent: pct })}
      </span>
    </div>
  );
}

/** Spotlight card for the Top 3 podium and relaxed alternatives.
 * #1 receives a Contract Navy accent strip + Signal Orange #1 Top match badge. */
export function PodiumJournalCard({
  journal,
  inst,
  instLabel,
  featured = false,
  staggerIndex = 0,
  isAlternative = false,
}: {
  journal: RecommendedJournal;
  inst: string;
  instLabel: string;
  featured?: boolean;
  staggerIndex?: number;
  isAlternative?: boolean;
}) {
  const t = useTranslations("guide");
  const journalHref = `/${inst}/journals/${encodeURIComponent(journal.issn_l)}`;
  const dealCapped = Boolean(journal.deal_summary?.cap_reached);

  return (
    <Card
      className={cn("guide-card-enter overflow-hidden", featured && "border-[var(--secondary)]")}
      style={{ "--stagger": `${staggerIndex * 70}ms` } as React.CSSProperties}
    >
      {/* Top accent strip on #1 top match */}
      {featured && (
        <div className="flex flex-wrap items-center justify-between gap-2 bg-[var(--secondary)] px-5 py-2 text-xs font-semibold text-[var(--secondary-foreground)]">
          <div className="flex items-center gap-2">
            <Badge variant="default">{t("results.topMatchBadge")}</Badge>
            <span className="opacity-90">{journal.estimated_cost_label}</span>
          </div>
          <span className="tabular-nums opacity-90">
            {t("results.topicMatch", { percent: Math.round(journal.similarity * 100) })}
          </span>
        </div>
      )}

      <CardContent className={cn("p-5 sm:p-6", featured && "pt-5")}>
        {/* Relaxed constraint banner for fallback alternatives */}
        {isAlternative && journal.relaxed_note && (
          <div className="mb-3 flex items-start gap-2 rounded-[var(--radius)] border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-[var(--foreground)]">
            <AlertTriangle
              aria-hidden
              className="mt-0.5 size-3.5 shrink-0 text-amber-600 dark:text-amber-400"
            />
            <span>
              <strong className="font-semibold">{t("results.relaxedBadge")}: </strong>
              {journal.relaxed_note}
            </span>
          </div>
        )}

        {/* Header row: rank + title + publisher + estimated cost */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              {!featured && (
                <Badge variant={isAlternative ? "muted" : "secondary"}>
                  {t("results.rankBadge", { rank: journal.rank })}
                </Badge>
              )}
              <ShortlistToggle
                inst={inst}
                issnL={journal.issn_l}
                title={journal.title ?? journal.issn_l}
              />
              <Link
                href={journalHref}
                className="text-lg font-bold tracking-tight text-[var(--foreground)] underline-offset-4 hover:text-[var(--primary-text)] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2"
              >
                {journal.title ?? journal.issn_l}
              </Link>
            </div>
            {journal.publisher && (
              <p className="mt-0.5 text-sm text-[var(--muted-foreground)]">
                <Link
                  href={`/${inst}/publisher/${encodeNamePath(journal.publisher)}`}
                  className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                >
                  {journal.publisher}
                </Link>
              </p>
            )}
          </div>

          {/* Cost highlight box */}
          <div className="shrink-0 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--muted)] px-3 py-1.5 text-xs font-semibold text-[var(--foreground)] sm:text-right">
            {journal.estimated_cost_label}
          </div>
        </div>

        {/* Bare SVG lockups row (never wrapped in pills!) + topic match bar */}
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] pb-3.5">
          <div className="flex flex-wrap items-center gap-3">
            <OaTypeBadge oaType={journal.oa_type} />
            <DealBadge covered={journal.deal_covered} capped={dealCapped} />
            <QuartileBadge quartile={journal.quartile ?? null} />
            {journal.funder_fit && (
              <FunderFitBadge
                status={journal.funder_fit.status}
                reasons={journal.funder_fit.reasons ?? []}
              />
            )}
          </div>
          <SimilarityMeter similarity={journal.similarity} />
        </div>

        {/* Plain-language summary */}
        <div className="mt-3.5">
          <p className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("results.whyHeading")}
          </p>
          <p className="mt-1 text-sm leading-relaxed text-[var(--foreground)]">{journal.summary}</p>
        </div>

        {/* Structured reasons list */}
        {(journal.reasons?.length ?? 0) > 0 && (
          <ul className="mt-3 grid gap-2 sm:grid-cols-2">
            {journal.reasons?.map((reason, idx) => (
              <li
                key={`${reason.kind}-${idx}`}
                className="flex items-start gap-2 rounded-[var(--radius)] bg-[var(--muted)]/60 px-3 py-2 text-xs"
              >
                <ReasonIcon tone={reason.tone} />
                <div className="min-w-0">
                  <p className="font-semibold text-[var(--foreground)]">{reason.label}</p>
                  <p className="mt-0.5 text-[var(--muted-foreground)]">{reason.detail}</p>
                </div>
              </li>
            ))}
          </ul>
        )}

        {/* Metadata strip + CTA */}
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 pt-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--muted-foreground)] tabular-nums">
            {(journal.works ?? 0) > 0 && (
              <span>
                {t("results.worksLabel", {
                  count: formatInt(journal.works ?? 0),
                  institution: instLabel,
                })}
              </span>
            )}
            {journal.twoyr_mean_citedness != null && (
              <span>
                {t("results.citednessLabel", {
                  value: journal.twoyr_mean_citedness.toFixed(1),
                })}
              </span>
            )}
            {journal.h_index != null && (
              <span>{t("results.hIndexLabel", { value: formatInt(journal.h_index) })}</span>
            )}
            {journal.topics?.slice(0, 3).map((topic) => (
              <Link
                key={topic}
                href={`/${inst}/?topic=${encodeURIComponent(topic)}`}
                className="rounded-md border border-[var(--border)] bg-[var(--muted)] px-2 py-0.5 text-[11px] text-[var(--foreground)] hover:border-[var(--primary)] hover:text-[var(--primary-text)]"
              >
                {topic}
              </Link>
            ))}
          </div>

          <Link href={journalHref}>
            <Button variant={featured ? "default" : "outline"} size="sm">
              {t("results.viewDetails")}
              <ArrowRight aria-hidden className="size-3.5" />
            </Button>
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}

/** Compact expandable row for ranks 4..N ("More strong matches"). */
export function RunnerUpJournalRow({
  journal,
  inst,
  instLabel,
}: {
  journal: RecommendedJournal;
  inst: string;
  instLabel: string;
}) {
  const t = useTranslations("guide");
  const [open, setOpen] = React.useState(false);
  const journalHref = `/${inst}/journals/${encodeURIComponent(journal.issn_l)}`;
  const dealCapped = Boolean(journal.deal_summary?.cap_reached);
  const pct = Math.round(journal.similarity * 100);

  return (
    <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="muted">{t("results.rankBadge", { rank: journal.rank })}</Badge>
            <ShortlistToggle
              inst={inst}
              issnL={journal.issn_l}
              title={journal.title ?? journal.issn_l}
            />
            <Link
              href={journalHref}
              className="font-semibold text-[var(--foreground)] underline-offset-4 hover:text-[var(--primary-text)] hover:underline"
            >
              {journal.title ?? journal.issn_l}
            </Link>
            {journal.publisher && (
              <span className="text-xs text-[var(--muted-foreground)]">
                ·{" "}
                <Link
                  href={`/${inst}/publisher/${encodeNamePath(journal.publisher)}`}
                  className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                >
                  {journal.publisher}
                </Link>
              </span>
            )}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs">
            <OaTypeBadge oaType={journal.oa_type} />
            <DealBadge covered={journal.deal_covered} capped={dealCapped} />
            <QuartileBadge quartile={journal.quartile ?? null} />
            {journal.funder_fit && (
              <FunderFitBadge
                status={journal.funder_fit.status}
                reasons={journal.funder_fit.reasons ?? []}
              />
            )}
            <span className="font-medium text-[var(--foreground)]">
              {journal.estimated_cost_label}
            </span>
            <span className="tabular-nums text-[var(--muted-foreground)]">
              {t("results.topicMatch", { percent: pct })}
            </span>
            {(journal.works ?? 0) > 0 && (
              <span className="tabular-nums text-[var(--muted-foreground)]">
                {t("results.worksLabel", {
                  count: formatInt(journal.works ?? 0),
                  institution: instLabel,
                })}
              </span>
            )}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-expanded={open}
            onClick={() => setOpen((prev) => !prev)}
          >
            {open ? t("results.collapseReasons") : t("results.expandReasons")}
            <ChevronDown
              aria-hidden
              className={cn("size-3.5 transition-transform", open && "rotate-180")}
            />
          </Button>
          <Link href={journalHref}>
            <Button variant="outline" size="sm">
              {t("results.viewDetails")}
              <ArrowRight aria-hidden className="size-3.5" />
            </Button>
          </Link>
        </div>
      </div>

      {open && (
        <div className="mt-3 border-t border-[var(--border)] pt-3">
          <p className="text-sm text-[var(--foreground)]">{journal.summary}</p>
          {(journal.reasons?.length ?? 0) > 0 && (
            <ul className="mt-2.5 grid gap-2 sm:grid-cols-2">
              {journal.reasons?.map((reason, idx) => (
                <li
                  key={`${reason.kind}-${idx}`}
                  className="flex items-start gap-2 rounded-[var(--radius)] bg-[var(--muted)]/60 px-3 py-2 text-xs"
                >
                  <ReasonIcon tone={reason.tone} />
                  <div className="min-w-0">
                    <p className="font-semibold text-[var(--foreground)]">{reason.label}</p>
                    <p className="mt-0.5 text-[var(--muted-foreground)]">{reason.detail}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
