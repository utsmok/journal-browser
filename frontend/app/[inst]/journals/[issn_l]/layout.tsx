import type { Metadata } from "next";

import { fetchEntityTitle } from "@/lib/entity-title";

/** Per-journal document title; falls back to the layout default on failure. */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ inst: string; issn_l: string }>;
}): Promise<Metadata> {
  const { inst, issn_l } = await params;
  return fetchEntityTitle<{ journal?: { title?: string | null } }>(
    `/api/v1/${encodeURIComponent(inst)}/journals/${encodeURIComponent(issn_l)}`,
    (d) => d.journal?.title,
  );
}

export default function JournalLayout({ children }: { children: React.ReactNode }) {
  return children;
}
