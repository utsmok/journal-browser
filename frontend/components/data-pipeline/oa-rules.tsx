import { getTranslations } from "next-intl/server";

// The outcome values are the fixed oa_type vocabulary and stay raw.
const RULES: { ruleKey: string; outcome: string; chip: string }[] = [
  {
    ruleKey: "oaRules.ruleEvidenceAndCharge",
    outcome: "gold",
    chip: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  },
  {
    ruleKey: "oaRules.ruleInDoajNoApc",
    outcome: "diamond",
    chip: "bg-sky-500/15 text-sky-700 dark:text-sky-400",
  },
  {
    ruleKey: "oaRules.ruleObservedColor",
    outcome: "gold, diamond, or hybrid",
    chip: "border border-[var(--border)] text-[var(--muted-foreground)]",
  },
  {
    ruleKey: "oaRules.ruleDealCovered",
    outcome: "hybrid",
    chip: "bg-violet-500/15 text-violet-700 dark:text-violet-400",
  },
  {
    ruleKey: "oaRules.ruleOtherEvidence",
    outcome: "generic",
    chip: "bg-teal-500/15 text-teal-700 dark:text-teal-400",
  },
  {
    ruleKey: "oaRules.ruleFallback",
    outcome: "subscription",
    chip: "bg-slate-500/15 text-slate-700 dark:text-slate-400",
  },
];

export async function OaRules() {
  const t = await getTranslations("dataPipeline");
  return (
    <div>
      {RULES.map((entry, i) => (
        <div
          key={entry.ruleKey}
          className="flex items-center justify-between gap-4 border-b border-[var(--border)] py-2 last:border-0"
        >
          <p className="text-sm">
            <span className="mr-2 text-[var(--muted-foreground)]">{i + 1}.</span>
            {t(entry.ruleKey)}
          </p>
          <span
            className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${entry.chip}`}
          >
            {entry.outcome}
          </span>
        </div>
      ))}
    </div>
  );
}
