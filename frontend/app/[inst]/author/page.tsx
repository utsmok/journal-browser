"use client";

import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { CollapsibleCard } from "@/components/collapsible-card";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useInstitution } from "@/hooks/use-institution";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { errorMessage, fetchAuthors } from "@/lib/api";

const SEARCH_INPUT_ID = "author-search";

export default function AuthorSearchPage() {
  // useSearchParams needs a Suspense boundary during prerender.
  return (
    <React.Suspense fallback={null}>
      <AuthorsView />
    </React.Suspense>
  );
}

function AuthorsView() {
  const inst = useInstitution();
  const site = useSiteMeta();
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const q = sp.get("q") ?? "";
  const [input, setInput] = React.useState(q);

  const update = React.useCallback(
    (value: string) => {
      const next = new URLSearchParams(sp.toString());
      if (value) next.set("q", value);
      else next.delete("q");
      router.replace(`${pathname}?${next}`, { scroll: false });
    },
    [pathname, router, sp],
  );

  // Live search with debounce; keep the input in sync with back/forward nav.
  React.useEffect(() => {
    setInput(q);
  }, [q]);
  React.useEffect(() => {
    const t = setTimeout(() => {
      if (input !== q) update(input);
    }, 300);
    return () => clearTimeout(t);
  }, [input, q, update]);

  const { data, isPending, isFetching, isError, error, refetch } = useQuery({
    queryKey: ["authors", inst, q],
    queryFn: () => fetchAuthors(inst, q || undefined),
    placeholderData: keepPreviousData,
  });

  const rows = data?.items ?? [];
  const disabled = data != null && !data.enabled;

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <section className="mb-8">
        <h1 className="mb-3 text-3xl font-bold text-balance">Authors</h1>
        <p className="mb-6 max-w-2xl text-[var(--muted-foreground)]">
          Search researchers at {site.name} to find experts, co-authors, or
          reviewers, and see where they publish.
        </p>
        {!disabled && (
          <form
            className="flex max-w-2xl gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              update(input);
            }}
          >
            <div className="relative flex-1">
              <Input
                id={SEARCH_INPUT_ID}
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Escape") event.currentTarget.blur();
                }}
                placeholder="Search by author name"
                aria-label="Search authors"
              />
              {input === "" && (
                <kbd
                  aria-hidden
                  className="pointer-events-none absolute right-2.5 top-1/2 hidden -translate-y-1/2 rounded border border-[var(--border)] bg-[var(--muted)] px-1.5 py-0.5 text-[11px] text-[var(--muted-foreground)] [@media(hover:hover)_and_(pointer:fine)]:block"
                >
                  /
                </kbd>
              )}
            </div>
            <Button type="submit">Search</Button>
          </form>
        )}
      </section>

      {disabled ? (
        <CollapsibleCard
          id="authors-disabled"
          title="Author profiles"
          contentClassName="text-sm text-[var(--muted-foreground)]"
        >
          Author profiles are not available for this institution.
        </CollapsibleCard>
      ) : (
        <Card>
          <CardContent className="pt-6">
            <div className="mb-3">
              <p className="text-sm text-[var(--muted-foreground)]">
                {/* Announce only settled counts: while a fetch runs the live
                    region keeps its previous text, so typing never chatters. */}
                <span aria-live="polite">
                  {data
                    ? `${data.total.toLocaleString("en")} author${data.total === 1 ? "" : "s"}${q ? ` matching “${q}”` : ""}`
                    : ""}
                </span>
                {isFetching && data ? " · updating…" : ""}
              </p>
            </div>

            {isError ? (
              <div className="py-10 text-center">
                <p className="text-[var(--destructive)]">{errorMessage(error)}</p>
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-3"
                  onClick={() => refetch()}
                >
                  Retry
                </Button>
              </div>
            ) : isPending ? (
              <div className="space-y-2 py-4">
                {Array.from({ length: 8 }).map((_, i) => (
                  <div
                    key={i}
                    className="h-9 animate-pulse rounded bg-[var(--muted)]"
                  />
                ))}
              </div>
            ) : rows.length === 0 ? (
              <div className="py-10 text-center text-[var(--muted-foreground)]">
                {q ? (
                  <>
                    No authors match &ldquo;{q}&rdquo;.
                  </>
                ) : (
                  <>No authors found.</>
                )}
              </div>
            ) : (
              <>
                {/* Stacked cards on narrow viewports: five columns would push
                    the works count off-screen behind horizontal scrolling. */}
                <ul
                  className={
                    isFetching ? "opacity-60 md:hidden" : "md:hidden"
                  }
                  aria-label="Author results"
                >
                  {rows.map((a) => (
                    <li
                      key={a.pure_uuid}
                      className="border-b border-[var(--border)] py-3 first:pt-0 last:border-0 last:pb-0"
                    >
                      <Link
                        href={`/${inst}/author/${a.pure_uuid}`}
                        className="font-medium text-[var(--foreground)] underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                      >
                        {a.name}
                      </Link>
                      <div className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                        {[a.faculty, a.research_group]
                          .filter(Boolean)
                          .join(" · ") || "—"}
                      </div>
                      <div className="mt-1 flex items-center gap-3 text-xs tabular-nums text-[var(--muted-foreground)]">
                        <span>
                          {a.n_works.toLocaleString("en")}{" "}
                          {a.n_works === 1 ? "work" : "works"}
                        </span>
                        {a.orcid && <OrcidLink orcid={a.orcid} />}
                      </div>
                    </li>
                  ))}
                </ul>
                <div className={isFetching ? "hidden opacity-60 md:block" : "hidden md:block"}>
                  <Table>
                    <caption className="sr-only">Author search results</caption>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Name</TableHead>
                        <TableHead>Faculty</TableHead>
                        <TableHead>Research group</TableHead>
                        <TableHead className="text-right">Works</TableHead>
                        <TableHead>ORCID</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {rows.map((a) => (
                        <TableRow key={a.pure_uuid}>
                          <TableCell className="font-medium">
                            <Link
                              href={`/${inst}/author/${a.pure_uuid}`}
                              className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
                            >
                              {a.name}
                            </Link>
                          </TableCell>
                          <TableCell>
                            <span className="block max-w-44 truncate" title={a.faculty ?? undefined}>
                              {a.faculty || <span className="text-[var(--muted-foreground)]">—</span>}
                            </span>
                          </TableCell>
                          <TableCell>
                            <span className="block max-w-44 truncate" title={a.research_group ?? undefined}>
                              {a.research_group || <span className="text-[var(--muted-foreground)]">—</span>}
                            </span>
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {a.n_works.toLocaleString("en")}
                          </TableCell>
                          <TableCell>
                            {a.orcid ? <OrcidLink orcid={a.orcid} /> : null}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
                <p className="mt-4 text-xs text-[var(--muted-foreground)]">
                  Showing {rows.length.toLocaleString("en")} of{" "}
                  {(data?.total ?? 0).toLocaleString("en")}
                </p>
              </>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/** Small external-link affordance to the author's ORCID record. */
function OrcidLink({ orcid }: { orcid: string }) {
  return (
    <a
      href={`https://orcid.org/${orcid}`}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-[var(--primary-text)] underline-offset-2 hover:underline"
      title={orcid}
      aria-label={`ORCID profile ${orcid}`}
    >
      ORCID <ExternalLink aria-hidden className="size-3.5 shrink-0" />
    </a>
  );
}
