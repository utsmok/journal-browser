"use client";

import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Compass,
  Loader2,
  RotateCcw,
  Sparkles,
} from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useInstitution } from "@/hooks/use-institution";
import { useSiteMeta } from "@/hooks/use-site-meta";
import {
  errorMessage,
  recommendJournals,
  type RecommendRequest,
  type RecommendResponse,
} from "@/lib/api";
import { useGuidePrefs } from "@/lib/guide-prefs";

import { GuideResults } from "./guide-results";
import { GuideStepper, type WizardStep } from "./guide-stepper";
import { StepBudget } from "./step-budget";
import { StepFunder } from "./step-funder";
import { combinedManuscriptLength, MIN_MANUSCRIPT_CHARS, StepManuscript } from "./step-manuscript";
import { StepPreferences } from "./step-preferences";

/** Four-step Guided Journal Finder wizard + podium results surface. */
export function GuideWizard({ embedded = false }: { embedded?: boolean }) {
  const t = useTranslations("guide");
  const tc = useTranslations("common");
  const inst = useInstitution();
  const site = useSiteMeta();
  const instLabel = site.short || site.name;

  const { prefs, funder, setFunder, updatePrefs, resetPrefs, hasSavedData } = useGuidePrefs();

  const [step, setStep] = React.useState<WizardStep>(1);
  const [maxReached, setMaxReached] = React.useState<WizardStep>(1);
  const [result, setResult] = React.useState<RecommendResponse | null>(null);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const manuscriptReady =
    combinedManuscriptLength(prefs.title, prefs.abstract) >= MIN_MANUSCRIPT_CHARS;

  const goToStep = (next: WizardStep) => {
    setResult(null);
    setError(null);
    setStep(next);
    setMaxReached((prev) => (next > prev ? next : prev));
  };

  const handleSubmit = async () => {
    if (!manuscriptReady || submitting) return;
    setSubmitting(true);
    setError(null);

    const payload: RecommendRequest = {
      title: prefs.title.trim(),
      abstract: prefs.abstract.trim(),
      funder_id: prefs.hasFunder && funder ? funder.id : null,
      budget_mode: prefs.budgetMode,
      max_apc_eur: prefs.budgetMode === "capped" ? prefs.maxApcEur : null,
      prefer_institution_history: prefs.preferInstitutionHistory,
      prefer_established: prefs.preferEstablished,
      include_non_journals: prefs.includeNonJournals,
      limit: 8,
    };

    try {
      const data = await recommendJournals(inst, payload);
      setResult(data);
    } catch (err) {
      setError(errorMessage(tc, err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleStartOver = () => {
    resetPrefs();
    setResult(null);
    setError(null);
    setStep(1);
    setMaxReached(1);
  };

  const body = (
    <>
      {!embedded && (
        <header className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-[var(--primary-text)]">
              <Compass aria-hidden className="size-3.5" />
              {t("header.eyebrow")}
            </p>
            <h1 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">
              {t("header.heading")}
            </h1>
            <p className="mt-1.5 max-w-2xl text-sm text-[var(--muted-foreground)]">
              {t("header.intro", { institution: instLabel })}
            </p>
          </div>

          {hasSavedData && !result && (
            <div className="flex shrink-0 items-center gap-2 text-xs text-[var(--muted-foreground)]">
              <span>{t("header.savedNote")}</span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={t("header.resetAria")}
                onClick={handleStartOver}
              >
                <RotateCcw aria-hidden className="size-3.5" />
                {t("header.reset")}
              </Button>
            </div>
          )}
        </header>
      )}

      {embedded && hasSavedData && !result && (
        <div className="mb-4 flex max-w-4xl items-center justify-end gap-2 text-xs text-[var(--muted-foreground)]">
          <span>{t("header.savedNote")}</span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label={t("header.resetAria")}
            onClick={handleStartOver}
          >
            <RotateCcw aria-hidden className="size-3.5" />
            {t("header.reset")}
          </Button>
        </div>
      )}

      {result ? (
        <div className={embedded ? "max-w-5xl" : undefined}>
          <GuideResults
            response={result}
            prefs={prefs}
            funder={funder}
            inst={inst}
            instLabel={instLabel}
            onAdjustStep={(target) => goToStep(target)}
            onStartOver={handleStartOver}
          />
        </div>
      ) : (
        <div className={embedded ? "max-w-4xl" : undefined}>
          <GuideStepper
            current={step}
            maxReached={maxReached}
            canAdvanceFrom1={manuscriptReady}
            onSelectStep={goToStep}
          />

          <Card>
            <CardContent className="p-5 sm:p-6">
              {step === 1 && (
                <StepManuscript
                  title={prefs.title}
                  abstract={prefs.abstract}
                  onChangeTitle={(title) => updatePrefs({ title })}
                  onChangeAbstract={(abstract) => updatePrefs({ abstract })}
                  onSelectExample={(title, abstract) => updatePrefs({ title, abstract })}
                />
              )}

              {step === 2 && (
                <StepFunder
                  hasFunder={prefs.hasFunder}
                  funder={funder}
                  instLabel={instLabel}
                  onSetHasFunder={(yes) => {
                    updatePrefs({ hasFunder: yes });
                    if (!yes) setFunder(null);
                  }}
                  onSelectFunder={setFunder}
                />
              )}

              {step === 3 && (
                <StepBudget
                  budgetMode={prefs.budgetMode}
                  maxApcEur={prefs.maxApcEur}
                  instLabel={instLabel}
                  onChangeBudgetMode={(budgetMode) => updatePrefs({ budgetMode })}
                  onChangeMaxApc={(maxApcEur) => updatePrefs({ maxApcEur })}
                />
              )}

              {step === 4 && (
                <StepPreferences
                  preferInstitutionHistory={prefs.preferInstitutionHistory}
                  preferEstablished={prefs.preferEstablished}
                  includeNonJournals={prefs.includeNonJournals}
                  instLabel={instLabel}
                  hasFunder={prefs.hasFunder}
                  funder={funder}
                  budgetMode={prefs.budgetMode}
                  maxApcEur={prefs.maxApcEur}
                  onToggleHistory={(preferInstitutionHistory) =>
                    updatePrefs({ preferInstitutionHistory })
                  }
                  onToggleEstablished={(preferEstablished) => updatePrefs({ preferEstablished })}
                  onToggleNonJournals={(includeNonJournals) => updatePrefs({ includeNonJournals })}
                />
              )}

              {/* API error banner */}
              {error && (
                <div
                  role="alert"
                  className="mt-5 flex items-start gap-2.5 rounded-[var(--radius)] border border-[var(--destructive)]/40 bg-[var(--destructive)]/10 px-4 py-3 text-sm"
                >
                  <AlertCircle
                    aria-hidden
                    className="mt-0.5 size-4 shrink-0 text-[var(--destructive)]"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold text-[var(--foreground)]">
                      {t("preferences.errorHeading")}
                    </p>
                    <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">{error}</p>
                  </div>
                  <Button type="button" variant="outline" size="sm" onClick={handleSubmit}>
                    {t("preferences.retry")}
                  </Button>
                </div>
              )}

              {/* Wizard footer navigation */}
              <div className="mt-6 flex items-center justify-between gap-3 border-t border-[var(--border)] pt-5">
                {step > 1 ? (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={submitting}
                    onClick={() => goToStep((step - 1) as WizardStep)}
                  >
                    <ArrowLeft aria-hidden className="size-4" />
                    {t("steps.back")}
                  </Button>
                ) : (
                  <span />
                )}

                {step < 4 ? (
                  <Button
                    type="button"
                    variant="default"
                    disabled={step === 1 && !manuscriptReady}
                    onClick={() => goToStep((step + 1) as WizardStep)}
                  >
                    {t("steps.next")}
                    <ArrowRight aria-hidden className="size-4" />
                  </Button>
                ) : (
                  <Button
                    type="button"
                    variant="default"
                    size="lg"
                    disabled={!manuscriptReady || submitting}
                    onClick={handleSubmit}
                  >
                    {submitting ? (
                      <>
                        <Loader2 aria-hidden className="size-4 animate-spin" />
                        {t("steps.submitting")}
                      </>
                    ) : (
                      <>
                        <Sparkles aria-hidden className="size-4" />
                        {t("steps.submit")}
                      </>
                    )}
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </>
  );

  if (embedded) return body;

  return <div className="mx-auto max-w-4xl px-4 py-8 sm:py-10">{body}</div>;
}
