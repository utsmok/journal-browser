export default function JournalDetailLoading() {
  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10" aria-busy="true">
      <div className="flex flex-wrap items-center gap-2">
        <div className="h-8 w-80 max-w-full animate-pulse rounded bg-[var(--muted)]" />
        <div className="h-6 w-24 animate-pulse rounded bg-[var(--muted)]" />
        <div className="h-6 w-16 animate-pulse rounded bg-[var(--muted)]" />
      </div>
      <div className="mt-2 h-4 w-48 animate-pulse rounded bg-[var(--muted)]" />
      <div className="mt-8 space-y-4">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm"
          >
            <div className="h-5 w-44 animate-pulse rounded bg-[var(--muted)]" />
            <div className="mt-3 h-24 animate-pulse rounded bg-[var(--muted)]" />
          </div>
        ))}
      </div>
    </div>
  );
}
