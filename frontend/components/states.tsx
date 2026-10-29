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
