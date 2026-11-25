"use client";

import {
  ArrowRight,
  ExternalLink,
  RotateCcw,
  Search,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { CollapsibleCard } from "@/components/collapsible-card";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { RecommendResponse } from "@/lib/api";
import type { FunderPrefs } from "@/lib/funder-prefs";
import { formatEur } from "@/lib/format";
import type { GuidePrefs } from "@/lib/guide-prefs";

import type { WizardStep } from "./guide-stepper";
import { PodiumJournalCard, RunnerUpJournalRow } from "./result-card";

/** Results view: active criteria bar, Top 3 podium, runner-ups, relaxed
 * alternatives, transparent methodology card, and semantic-search handoff. */
export function GuideResults({
  response,
  prefs,
  funder,
  inst,
  instLabel,
  onAdjustStep,
  onStartOver,
}: {
  response: RecommendResponse;
  prefs: GuidePrefs;
  funder: FunderPrefs;
  inst: string;
  instLabel: string;
  onAdjustStep: (step: WizardStep) => void;
  onStartOver: () => void;
}) {
  const t = useTranslations("guide");

  const podium = response.recommendations.slice(0, 3);
  const runnerUps = response.recommendations.slice(3);
  const hasAnyMatches = podium.length > 0 || response.alternatives.length > 0;

  const budgetChip =
    prefs.budgetMode === "none"
      ? t("preferences.budgetSummaryNone")
      : prefs.budgetMode === "capped"
        ? t("preferences.budgetSummaryCapped", { amount: formatEur(prefs.maxApcEur) })
        : prefs.budgetMode === "funder_pays"
          ? t("preferences.budgetSummaryFunderPays")
          : t("preferences.budgetSummaryAny");

  // Compact semantic handoff query (max 512 chars on GET /semantic-search).
  const semanticQuery = (prefs.title.trim() || prefs.abstract.trim()).slice(0, 260);
  const semanticHref = `/${inst}/?q=${encodeURIComponent(semanticQuery)}&mode=semantic`;

  // Structured browse handoff carrying deal/OA/funder filters cleanly.
  const browseQs = new URLSearchParams();
  if (prefs.budgetMode === "none") browseQs.set("deal", "covered");
  else if (prefs.budgetMode === "capped" || prefs.budgetMode === "funder_pays")
    browseQs.set("oa_type", "diamond,gold,hybrid");
  if (prefs.hasFunder && funder && response.funder_policy_structured)
    browseQs.set("funder_fit", "compliant");
  if (!prefs.includeNonJournals) browseQs.set("pub_type", "journal");
  const browseHref = `/${inst}/${browseQs.toString() ? `?${browseQs.toString()}` : ""}`;

  return (
    <div className="guide-step-enter space-y-8">
      {/* Results header + editable criteria chips */}
      <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className="text-2xl font-bold tracking-tight">{t("results.heading")}</h2>
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">
              {t("results.subheading", {
                pool: response.candidate_pool_size,
                strict: response.strict_match_count,
              })}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => onAdjustStep(1)}>
              <SlidersHorizontal aria-hidden className="size-3.5" />
              {t("results.adjustAnswers")}
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={onStartOver}>
              <RotateCcw aria-hidden className="size-3.5" />
              {t("results.startOver")}
            </Button>
          </div>
        </div>

        {/* Clickable criteria chips jump right to the matching step */}
        <div
          aria-label={t("results.criteriaAria")}
          className="mt-4 flex flex-wrap items-center gap-1.5 border-t border-[var(--border)] pt-3.5 text-xs"
        >
          <button
            type="button"
            onClick={() => onAdjustStep(1)}
            className="max-w-xs truncate rounded-md border border-[var(--brand-tint-border)] bg-[var(--brand-tint-bg)] px-2.5 py-1 font-medium text-[var(--primary-text)] transition-colors hover:border-[var(--primary)]"
          >
            {prefs.title.trim() || prefs.abstract.trim().slice(0, 60)}
          </button>
          <button
            type="button"
            onClick={() => onAdjustStep(2)}
            className="rounded-md border border-[var(--border)] bg-[var(--muted)] px-2.5 py-1 font-medium text-[var(--foreground)] transition-colors hover:border-[var(--primary)]"
          >
            {prefs.hasFunder && funder ? funder.name : t("preferences.funderSummaryNone")}
          </button>
          <button
            type="button"
            onClick={() => onAdjustStep(3)}
            className="rounded-md border border-[var(--border)] bg-[var(--muted)] px-2.5 py-1 font-medium text-[var(--foreground)] transition-colors hover:border-[var(--primary)]"
          >
            {budgetChip}
          </button>
          {prefs.preferInstitutionHistory && (
            <button
              type="button"
              onClick={() => onAdjustStep(4)}
              className="rounded-md border border-[var(--border)] bg-[var(--muted)] px-2.5 py-1 font-medium text-[var(--foreground)] transition-colors hover:border-[var(--primary)]"
            >
              {instLabel} history
            </button>
          )}
          {prefs.preferEstablished && (
            <button
              type="button"
              onClick={() => onAdjustStep(4)}
              className="rounded-md border border-[var(--border)] bg-[var(--muted)] px-2.5 py-1 font-medium text-[var(--foreground)] transition-colors hover:border-[var(--primary)]"
            >
              Q1–Q2 nudge
            </button>
          )}
          {prefs.includeNonJournals && (
            <button
              type="button"
              onClick={() => onAdjustStep(4)}
              className="rounded-md border border-[var(--border)] bg-[var(--muted)] px-2.5 py-1 font-medium text-[var(--foreground)] transition-colors hover:border-[var(--primary)]"
            >
              + Book &amp; conf. series
            </button>
          )}
        </div>
      </div>

      {/* Empty state if candidate pool returned nothing */}
      {!hasAnyMatches && (
        <Card>
          <CardContent className="p-6 text-center">
            <Sparkles aria-hidden className="mx-auto size-8 text-[var(--muted-foreground)]" />
            <h3 className="mt-3 text-lg font-semibold">{t("results.noResultsHeading")}</h3>
            <p className="mx-auto mt-1 max-w-md text-sm text-[var(--muted-foreground)]">
              {t("results.noResultsBody")}
            </p>
            <Button
              type="button"
              variant="default"
              className="mt-4"
              onClick={() => onAdjustStep(1)}
            >
              {t("results.editManuscript")}
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Top 3 podium */}
      {podium.length > 0 && (
        <section aria-label={t("results.heading")} className="space-y-4">
          {podium.map((journal, idx) => (
            <PodiumJournalCard
              key={journal.issn_l}
              journal={journal}
              inst={inst}
              instLabel={instLabel}
              featured={idx === 0}
              staggerIndex={idx}
            />
          ))}
        </section>
      )}

      {/* Runner-ups (ranks 4..N) */}
      {runnerUps.length > 0 && (
        <section className="space-y-3">
          <div>
            <h3 className="text-lg font-bold tracking-tight">{t("results.moreMatchesHeading")}</h3>
            <p className="text-sm text-[var(--muted-foreground)]">
              {t("results.moreMatchesIntro")}
            </p>
          </div>
          <div className="space-y-2.5">
            {runnerUps.map((journal) => (
              <RunnerUpJournalRow
                key={journal.issn_l}
                journal={journal}
                inst={inst}
                instLabel={instLabel}
              />
            ))}
          </div>
        </section>
      )}

      {/* Relaxed fallback alternatives (only when strict matches < 3) */}
      {response.alternatives.length > 0 && (
        <section className="space-y-3">
          <div>
            <h3 className="text-lg font-bold tracking-tight">{t("results.alternativesHeading")}</h3>
            <p className="text-sm text-[var(--muted-foreground)]">
              {t("results.alternativesIntro")}
            </p>
          </div>
          <div className="space-y-3">
            {response.alternatives.map((alt, idx) => (
              <PodiumJournalCard
                key={alt.issn_l}
                journal={alt}
                inst={inst}
                instLabel={instLabel}
                staggerIndex={idx}
                isAlternative
              />
            ))}
          </div>
        </section>
      )}

      {/* Collapsible transparency card */}
      <CollapsibleCard
        id="how-recommendations-work"
        title={t("results.transparencyTitle")}
        defaultOpen={false}
      >
        <p className="text-sm leading-relaxed text-[var(--muted-foreground)]">
          {t("results.transparencyLead")}
        </p>
        <p className="mt-2 text-xs font-semibold tabular-nums text-[var(--foreground)]">
          {t("results.transparencyStats", {
            pool: response.candidate_pool_size,
            strict: response.strict_match_count,
          })}
        </p>
        <ul className="mt-3 list-disc space-y-1.5 pl-5 text-sm text-[var(--foreground)]">
          {response.ranking_factors.map((factor) => (
            <li key={factor}>{factor}</li>
          ))}
        </ul>
        <div className="mt-4">
          <Link
            href="/data-pipeline#how-guided-finder"
            className="inline-flex items-center gap-1.5 text-sm font-medium text-[var(--primary-text)] underline-offset-4 hover:underline"
          >
            {t("results.transparencyPipelineLink")}
            <ExternalLink aria-hidden className="size-3.5" />
          </Link>
        </div>
      </CollapsibleCard>

      {/* Browse & semantic search handoff */}
      {semanticQuery.length >= 2 && (
        <div className="flex flex-col items-start justify-between gap-3 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] px-5 py-4 sm:flex-row sm:items-center">
          <div className="flex items-center gap-2.5 text-sm text-[var(--muted-foreground)]">
            <Search aria-hidden className="size-4 shrink-0 text-[var(--primary-text)]" />
            <span>{t("results.handoffLead")}</span>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Link
              href={browseHref}
              className="inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-xs font-semibold text-[var(--foreground)] hover:border-[var(--primary)] hover:text-[var(--primary-text)] min-[1024px]:min-h-0"
            >
              {t("results.browseWithFilters")}
            </Link>
            <Link
              href={semanticHref}
              className="inline-flex shrink-0 items-center gap-1.5 text-sm font-semibold text-[var(--primary-text)] underline-offset-4 hover:underline"
            >
              {t("results.handoffCta")}
              <ArrowRight aria-hidden className="size-4" />
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
