const RULES: {
  rule: string;
  outcome: string;
  chip: string;
}[] = [
  {
    rule: "OA evidence plus charge evidence",
    outcome: "gold",
    chip: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  },
  {
    rule: "DOAJ-listed with doaj_has_apc explicitly false",
    outcome: "diamond",
    chip: "bg-sky-500/15 text-sky-700 dark:text-sky-400",
  },
  {
    rule: "Observed work color",
    outcome: "gold, diamond, or hybrid",
    chip: "border border-[var(--border)] text-[var(--muted-foreground)]",
  },
  {
    rule: "Deal coverage",
    outcome: "hybrid",
    chip: "bg-violet-500/15 text-violet-700 dark:text-violet-400",
  },
  {
    rule: "Remaining OA evidence",
    outcome: "generic",
    chip: "bg-teal-500/15 text-teal-700 dark:text-teal-400",
  },
  {
    rule: "Everything else",
    outcome: "subscription",
    chip: "bg-slate-500/15 text-slate-700 dark:text-slate-400",
  },
];

export function OaRules() {
  return (
    <div>
      {RULES.map((entry, i) => (
        <div
          key={entry.rule}
          className="flex items-center justify-between gap-4 border-b border-[var(--border)] py-2 last:border-0"
        >
          <p className="text-sm">
            <span className="mr-2 text-[var(--muted-foreground)]">{i + 1}.</span>
            {entry.rule}
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
