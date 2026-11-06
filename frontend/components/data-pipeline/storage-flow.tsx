const HARVEST_STAGES: { title: string; detail: string }[] = [
  {
    title: "External inputs",
    detail: "11 network sources, 1 tracked CSV set, 1 read-only database connection",
  },
  { title: "download_to_landing", detail: "writes files to landing/ and rows to raw_files" },
  { title: "source_records", detail: "verbatim payloads, versioned by content hash" },
  {
    title: "normalized tables",
    detail: "journals, works, openalex_works, deals, pure_*, jisc_*, authors",
  },
  {
    title: "denormalized columns",
    detail:
      "journal_flags, works_2020_plus, latest_apc_euro, publisher_canonical, oa_status_observed, search_vector, embedding",
  },
  { title: "caches", detail: "24 hour lifetime, keyed on cache_epoch" },
  { title: "API responses", detail: "routers under /api/v1" },
];

const USER_WRITES: { title: string; detail: string }[] = [
  { title: "usage_events", detail: "page views, searches, errors" },
  { title: "feedback_items", detail: "the reporter's search state" },
  { title: "doc_edits", detail: "admin edits applied over the served documents" },
  { title: "manual_overrides", detail: "reapplied after every harvest" },
  { title: "status_changes", detail: "append-only audit log" },
];

function StageRow({ stages }: { stages: { title: string; detail: string }[] }) {
  return (
    <div className="flex flex-row flex-wrap items-stretch gap-2">
      {stages.map((stage, i) => (
        <div key={stage.title} className="contents">
          {i > 0 && (
            <span aria-hidden className="self-center text-[var(--muted-foreground)]">
              →
            </span>
          )}
          <div className="max-w-[13rem] min-w-[10rem] rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-3">
            <p className="text-sm font-semibold">{stage.title}</p>
            <p className="mt-1 text-xs text-[var(--muted-foreground)]">{stage.detail}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

export function StorageFlow() {
  return (
    <div className="space-y-3">
      <div>
        <p className="mb-2 text-xs font-medium tracking-wide text-[var(--muted-foreground)] uppercase">
          Harvest path
        </p>
        <StageRow stages={HARVEST_STAGES} />
      </div>
      <div>
        <p className="mb-2 text-xs font-medium tracking-wide text-[var(--muted-foreground)] uppercase">
          User writes (bypass the harvest path)
        </p>
        <StageRow stages={USER_WRITES} />
      </div>
    </div>
  );
}
