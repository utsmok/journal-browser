"use client";

import { useQueryClient } from "@tanstack/react-query";
import { MessageSquarePlus, X } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const CATEGORIES = [
  { value: "", label: "Category…" },
  { value: "bug", label: "Bug" },
  { value: "data", label: "Wrong data" },
  { value: "feature", label: "Feature request" },
  { value: "improvement", label: "Improvement" },
  { value: "other", label: "Other" },
] as const;

const MAX_DUMP_BYTES = 700_000;

type Phase = "idle" | "submitting" | "success" | "error";

/**
 * Snapshot of every TanStack Query cache entry with data, most recent first,
 * so a report carries the exact API responses the reporter saw. Entries past
 * the byte budget are skipped (largest impact: current page stays first).
 */
function buildPageDump(queries: { key: readonly unknown[]; updated: number; data: unknown }[]) {
  const kept: unknown[] = [];
  let budget = MAX_DUMP_BYTES;
  let omitted = 0;
  for (const q of queries) {
    const size = JSON.stringify(q).length;
    if (size > budget) {
      omitted += 1;
      continue;
    }
    budget -= size;
    kept.push(q);
  }
  return {
    url: window.location.href,
    user_agent: navigator.userAgent,
    viewport: `${window.innerWidth}x${window.innerHeight}`,
    submitted_at: new Date().toISOString(),
    queries_omitted_oversize: omitted,
    queries: kept,
  };
}

export function FeedbackWidget() {
  const queryClient = useQueryClient();
  const [open, setOpen] = React.useState(false);
  const [title, setTitle] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [category, setCategory] = React.useState("");
  const [phase, setPhase] = React.useState<Phase>("idle");

  React.useEffect(() => {
    if (phase !== "success") return;
    const t = setTimeout(() => {
      setOpen(false);
      setTitle("");
      setDescription("");
      setCategory("");
      setPhase("idle");
    }, 2000);
    return () => clearTimeout(t);
  }, [phase]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !description.trim() || phase === "submitting") return;
    setPhase("submitting");
    const cache = queryClient
      .getQueryCache()
      .getAll()
      .filter((q) => q.state.data !== undefined)
      .sort((a, b) => (b.state.dataUpdatedAt ?? 0) - (a.state.dataUpdatedAt ?? 0))
      .map((q) => ({ key: q.queryKey, updated: q.state.dataUpdatedAt, data: q.state.data }));
    try {
      const res = await fetch("/api/v1/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: title.trim(),
          description: description.trim(),
          category: category || null,
          page_url: window.location.pathname,
          page_data: buildPageDump(cache),
        }),
      });
      if (!res.ok) throw new Error(`${res.status}`);
      setPhase("success");
    } catch {
      setPhase("error");
    }
  }

  const field =
    "w-full rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-3 py-2 text-sm placeholder:text-[var(--muted-foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]";

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label="Report an issue"
        aria-expanded={open}
        className={`fixed right-4 bottom-4 z-50 flex size-12 items-center justify-center rounded-full bg-[var(--primary)] text-[var(--primary-foreground)] shadow-lg transition-opacity hover:opacity-90 sm:right-6 sm:bottom-6 ${
          open ? "pointer-events-none opacity-0" : ""
        }`}
      >
        <MessageSquarePlus className="size-6" aria-hidden="true" />
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Report an issue"
          className="fixed inset-x-4 bottom-20 z-50 max-h-[75dvh] overflow-y-auto rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 sm:inset-x-auto sm:right-6 sm:bottom-24 sm:w-96"
        >
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold">Report an issue</h2>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close"
              className="text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            >
              <X className="size-4" aria-hidden="true" />
            </button>
          </div>

          {phase === "success" ? (
            <p className="py-6 text-center text-sm">
              Thanks — your report is in, including the page data.
            </p>
          ) : (
            <form onSubmit={submit} className="space-y-3">
              <Input
                placeholder="Short title *"
                value={title}
                maxLength={255}
                onChange={(e) => setTitle(e.target.value)}
                required
              />
              <select
                className={field}
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                aria-label="Category"
              >
                {CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
              <textarea
                className={`${field} min-h-24`}
                placeholder="What did you see, and what did you expect? *"
                value={description}
                maxLength={8000}
                onChange={(e) => setDescription(e.target.value)}
                required
              />
              <p className="text-xs text-[var(--muted-foreground)]">
                The current URL and the data shown on this page are included automatically.
              </p>
              {phase === "error" && (
                <p className="text-sm text-[var(--destructive)]">
                  Something went wrong sending the report — try again.
                </p>
              )}
              <div className="flex justify-end gap-2">
                <Button type="button" variant="outline" size="sm" onClick={() => setOpen(false)}>
                  Cancel
                </Button>
                <Button type="submit" size="sm" disabled={phase === "submitting"}>
                  {phase === "submitting" ? "Sending…" : "Send report"}
                </Button>
              </div>
            </form>
          )}
        </div>
      )}
    </>
  );
}
