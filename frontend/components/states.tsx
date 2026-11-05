import { BackLink } from "@/components/back-link";

/** Detail-page loading state: title bar plus a content block. */
export function DetailSkeleton() {
  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <div className="h-8 w-2/3 animate-pulse rounded bg-[var(--muted)]" />
      <div className="mt-4 h-40 animate-pulse rounded bg-[var(--muted)]" />
    </div>
  );
}

/**
 * Full-page skeleton for the journal detail. Mirrors the real layout
 * (header, key-stats grid, chart, publications list) so sections pop in
 * without the page reflowing underneath the reader.
 */
export function JournalDetailSkeleton() {
  return (
    <div
      className="mx-auto max-w-5xl px-4 py-10"
      aria-busy="true"
      aria-live="polite"
    >
      <span className="sr-only">Loading journal details…</span>
      <div className="flex flex-wrap items-center gap-2">
        <div className="h-8 w-72 max-w-full animate-pulse rounded bg-[var(--muted)]" />
        <div className="h-6 w-24 animate-pulse rounded bg-[var(--muted)]" />
        <div className="h-6 w-16 animate-pulse rounded bg-[var(--muted)]" />
      </div>
      <div className="mt-2 h-4 w-44 animate-pulse rounded bg-[var(--muted)]" />
      <div className="mt-8 space-y-6">
        <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
          <div className="h-5 w-28 animate-pulse rounded bg-[var(--muted)]" />
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <div key={i}>
                <div className="h-7 w-14 animate-pulse rounded bg-[var(--muted)]" />
                <div className="mt-1.5 h-3 w-24 animate-pulse rounded bg-[var(--muted)]" />
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
          <div className="h-5 w-44 animate-pulse rounded bg-[var(--muted)]" />
          <div className="mt-4 h-36 animate-pulse rounded bg-[var(--muted)]" />
        </div>
        <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
          <div className="h-5 w-40 animate-pulse rounded bg-[var(--muted)]" />
          <div className="mt-4 space-y-2.5">
            {[92, 75, 84, 60].map((w, i) => (
              <div
                key={i}
                className="h-4 animate-pulse rounded bg-[var(--muted)]"
                style={{ width: `${w}%` }}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Detail-page error state: message plus a way back. Defaults match the
 * search-backed detail pages; callers with other labels or margins override.
 */
export function ErrorPanel({
  message,
  backHref,
  backLabel = "Back to search",
  backClassName = "mt-2",
}: {
  message: string;
  backHref: string;
  backLabel?: string;
  backClassName?: string;
}) {
  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <p className="text-[var(--destructive)]">{message}</p>
      <BackLink href={backHref} label={backLabel} className={backClassName} />
    </div>
  );
}

/** List-page loading state: `rows` placeholder bars. */
export function ListSkeletonRows({ rows }: { rows: number }) {
  return (
    <div className="space-y-2 py-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-9 animate-pulse rounded bg-[var(--muted)]" />
      ))}
    </div>
  );
}
