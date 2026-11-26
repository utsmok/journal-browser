export default function CollaborationsLoading() {
  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10" aria-busy="true">
      <div className="space-y-2">
        <div className="h-9 w-80 max-w-full animate-pulse rounded bg-[var(--muted)]" />
        <div className="h-4 w-[30rem] max-w-full animate-pulse rounded bg-[var(--muted)]" />
      </div>
      <div className="mt-5 h-12 w-full animate-pulse rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)]" />
      <div className="mt-5 flex flex-col gap-4 min-[960px]:grid min-[960px]:grid-cols-[15rem_minmax(0,1fr)] min-[960px]:items-start min-[960px]:gap-6 min-[1280px]:grid-cols-[18rem_minmax(0,1fr)] min-[1280px]:gap-8">
        <div className="hidden space-y-3 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 min-[960px]:block">
          <div className="h-9 w-full animate-pulse rounded bg-[var(--muted)]" />
          {[85, 70, 90, 60, 78].map((w, i) => (
            <div
              key={i}
              className="h-7 animate-pulse rounded bg-[var(--muted)]"
              style={{ width: `${w}%` }}
            />
          ))}
        </div>
        <div className="space-y-5">
          <div className="h-[22rem] animate-pulse rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)]" />
          <div className="space-y-2.5 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-5">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="h-9 animate-pulse rounded bg-[var(--muted)]" />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
