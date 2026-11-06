const STAGES: { title: string; detail: string }[] = [
  { title: "External APIs and files", detail: "13 services + 1 DSN" },
  { title: "download_to_landing", detail: "landing/ + raw_files" },
  { title: "source_records", detail: "verbatim payloads, SHA-256 content hash versions" },
  {
    title: "normalized tables",
    detail: "journals, works, openalex_works, deals, pure_*, jisc_*, authors",
  },
  {
    title: "denormalized columns",
    detail:
      "journal_flags, works_2020_plus, latest_apc_euro, publisher_canonical, oa_status_observed, search_vector, embedding",
  },
  { title: "caches", detail: "FACET_CACHE, SNAPSHOT_CACHE, 24 h TTL, keyed on cache_epoch" },
  { title: "API responses", detail: "routers under /api/v1" },
];

export function StorageFlow() {
  return (
    <div>
      <div className="flex flex-row flex-wrap items-stretch gap-2">
        {STAGES.map((stage, i) => (
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
      <p className="mt-3 text-sm text-[var(--muted-foreground)]">
        User writes bypass this strip entirely: usage_events, feedback_items, doc_edits,
        manual_overrides, and status_changes are filled by the site itself.
      </p>
    </div>
  );
}
