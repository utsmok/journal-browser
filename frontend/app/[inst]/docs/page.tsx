"use client";

import Link from "next/link";
import { useQueries, useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { useInstitution } from "@/hooks/use-institution";
import {
  DOC_GROUPS,
  GROUP_LABEL,
  docDescription,
  fetchDoc,
  fetchDocs,
  sortDocs,
  truncate,
  type DocsListItem,
} from "@/lib/docs";

/** One-line pitch for each real surface, linked from the top of the index. */
const LIVE_SURFACES = [
  { path: "journals/0027-8424", label: "Journal pages", blurb: "deals, APCs, and statistics for one title" },
  { path: "author", label: "Author profiles", blurb: "where colleagues publish and what covers them" },
  { path: "publisher", label: "Publishers", blurb: "agreements and output per publisher" },
  { path: "", label: "Journal search", blurb: "the main search over all titles" },
] as const;

export default function DocsIndexPage() {
  const inst = useInstitution();
  const list = useQuery({ queryKey: ["docs", inst], queryFn: fetchDocs });
  const slugs = (list.data ?? []).map((d) => d.slug);
  // Detail docs feed the index one-liners; results align with slugs.
  const details = useQueries({
    queries: slugs.map((slug) => ({
      queryKey: ["docs", inst, slug],
      queryFn: () => fetchDoc(slug),
    })),
  });
  const describe = (item: DocsListItem) => {
    const i = slugs.indexOf(item.slug);
    const d = i >= 0 ? details[i]?.data : undefined;
    const text = d ? docDescription(d) : null;
    return text ? truncate(text) : null;
  };

  const groups = DOC_GROUPS.map((group) => ({
    group,
    docs: sortDocs(list.data ?? []).filter((d) => d.group === group),
  })).filter((g) => g.docs.length > 0);

  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <h1 className="text-3xl font-bold">Documentation</h1>
      <p className="mt-2 text-[var(--muted-foreground)]">
        What this browser shows, where the data comes from, and how to argue
        for open access with it.
      </p>

      <div className="mt-6 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4">
        <p className="text-sm font-semibold">See it live</p>
        <ul className="mt-2 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
          {LIVE_SURFACES.map((s) => (
            <li key={s.label}>
              <Link
                href={`/${inst}/${s.path}`}
                className="text-[var(--primary-text)] underline-offset-2 hover:underline"
              >
                {s.label}
              </Link>{" "}
              <span className="text-[var(--muted-foreground)]">— {s.blurb}</span>
            </li>
          ))}
        </ul>
      </div>

      {list.isPending && (
        <p className="mt-10 text-sm text-[var(--muted-foreground)]">Loading…</p>
      )}
      {list.isError && (
        <p className="mt-10 text-sm text-destructive">
          Could not load the docs list.
        </p>
      )}

      {groups.map(({ group, docs }) => (
        <section key={group} className="mt-10">
          <h2 className="text-xs font-bold uppercase tracking-wide text-[var(--muted-foreground)]">
            {GROUP_LABEL[group]}
          </h2>
          <ul className="mt-2 divide-y divide-[var(--border)] rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)]">
            {docs.map((d) => (
              <li key={d.slug}>
                <Link
                  href={`/${inst}/docs/${d.slug}`}
                  className="flex items-start justify-between gap-4 px-4 py-3 hover:bg-[var(--muted)]"
                >
                  <span>
                    <span className="font-semibold">{d.title}</span>
                    {describe(d) && (
                      <span className="mt-0.5 block text-sm text-[var(--muted-foreground)]">
                        {describe(d)}
                      </span>
                    )}
                  </span>
                  {d.edits > 0 && (
                    <Badge variant="muted" className="mt-0.5 shrink-0">
                      {d.edits} {d.edits === 1 ? "edit" : "edits"}
                    </Badge>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
