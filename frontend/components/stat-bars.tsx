/** Pure-CSS per-year bar chart (no chart library). */
export function StatBars({
  data,
}: {
  data: { year: number; value: number }[];
}) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <div className="flex h-44 items-end gap-2" role="img" aria-label="Publications per year">
      {data.map((d) => (
        <div key={d.year} className="flex h-full flex-1 flex-col items-center justify-end gap-1">
          <span className="text-[11px] tabular-nums text-[var(--muted-foreground)]">
            {d.value > 0 ? d.value : ""}
          </span>
          <div
            className="w-full max-w-12 rounded-t bg-[var(--primary)] transition-[height]"
            style={{ height: `${Math.max((d.value / max) * 100, d.value > 0 ? 2 : 0)}%` }}
            title={`${d.year}: ${d.value} works`}
          />
          <span className="text-[11px] tabular-nums text-[var(--muted-foreground)]">
            {d.year}
          </span>
        </div>
      ))}
    </div>
  );
}

type SplitSegment = { key: string; label: string; count: number };

const SEGMENT_COLORS: Record<string, { bg: string; opacity: number }> = {
  gold: { bg: "var(--primary)", opacity: 1 },
  hybrid: { bg: "var(--primary)", opacity: 0.6 },
  diamond: { bg: "var(--primary)", opacity: 0.35 },
  green: { bg: "var(--secondary)", opacity: 1 },
  bronze: { bg: "var(--secondary)", opacity: 0.55 },
  closed: { bg: "var(--muted)", opacity: 1 },
};

/** Stacked horizontal OA-status split with legend (token colors only). */
export function OaSplit({ segments }: { segments: SplitSegment[] }) {
  const total = segments.reduce((sum, s) => sum + s.count, 0);
  if (total === 0) return null;
  return (
    <div>
      <div className="flex h-5 w-full overflow-hidden rounded-[var(--radius)]">
        {segments
          .filter((s) => s.count > 0)
          .map((s) => {
            const color = SEGMENT_COLORS[s.key] ?? SEGMENT_COLORS.closed;
            return (
              <div
                key={s.key}
                title={`${s.label}: ${s.count} (${Math.round((s.count / total) * 100)}%)`}
                style={{ backgroundColor: color.bg, opacity: color.opacity, width: `${(s.count / total) * 100}%` }}
              />
            );
          })}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--muted-foreground)]">
        {segments.map((s) => (
          <li key={s.key} className="flex items-center gap-1.5">
            <span
              aria-hidden
              className="inline-block size-2.5 rounded-full"
              style={{
                backgroundColor: (SEGMENT_COLORS[s.key] ?? SEGMENT_COLORS.closed).bg,
                opacity: (SEGMENT_COLORS[s.key] ?? SEGMENT_COLORS.closed).opacity,
              }}
            />
            {s.label} <span className="tabular-nums">{s.count}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
