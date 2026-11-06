const RULES: {
  rule: string;
  outcome: string;
  chip: string;
}[] = [
  {
    rule: "Open-access evidence and charge evidence both present",
    outcome: "gold",
    chip: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  },
  {
    rule: "In DOAJ, with doaj_has_apc explicitly false",
    outcome: "diamond",
    chip: "bg-sky-500/15 text-sky-700 dark:text-sky-400",
  },
  {
    rule: "An observed work color exists",
    outcome: "gold, diamond, or hybrid",
    chip: "border border-[var(--border)] text-[var(--muted-foreground)]",
  },
  {
    rule: "The journal is covered by a deal",
    outcome: "hybrid",
    chip: "bg-violet-500/15 text-violet-700 dark:text-violet-400",
  },
  {
    rule: "Any other open-access evidence exists",
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
