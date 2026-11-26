export default function InstLoading() {
  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10" aria-busy="true">
      <div className="mb-6 space-y-2.5">
        <div className="h-9 w-72 max-w-full animate-pulse rounded bg-[var(--muted)]" />
        <div className="h-4 w-[32rem] max-w-full animate-pulse rounded bg-[var(--muted)]" />
        <div className="mt-4 h-10 w-full max-w-2xl animate-pulse rounded-[var(--radius)] bg-[var(--muted)]" />
      </div>
      <div className="flex flex-col gap-4 min-[960px]:grid min-[960px]:grid-cols-[15rem_minmax(0,1fr)] min-[960px]:items-start min-[960px]:gap-6 min-[1280px]:grid-cols-[18rem_minmax(0,1fr)] min-[1280px]:gap-8">
        <div className="hidden space-y-3 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 min-[960px]:block">
          <div className="h-4 w-20 animate-pulse rounded bg-[var(--muted)]" />
          {[88, 72, 94, 65, 80, 76].map((w, i) => (
            <div
              key={i}
              className="h-7 animate-pulse rounded bg-[var(--muted)]"
              style={{ width: `${w}%` }}
            />
          ))}
        </div>
        <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-5">
          <div className="mb-4 flex items-center justify-between border-b border-[var(--border)] pb-3">
            <div className="h-4 w-32 animate-pulse rounded bg-[var(--muted)]" />
            <div className="h-8 w-40 animate-pulse rounded bg-[var(--muted)]" />
          </div>
          <div className="space-y-2.5 py-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="h-9 animate-pulse rounded bg-[var(--muted)]" />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
