import type { Metadata } from "next";

import { fetchEntityTitle } from "@/lib/entity-title";

/** Per-author document title; falls back to the layout default on failure. */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ inst: string; authorId: string }>;
}): Promise<Metadata> {
  const { inst, authorId } = await params;
  return fetchEntityTitle<{ author?: { name?: string | null; display_name?: string | null } }>(
    `/api/v1/${encodeURIComponent(inst)}/authors/${encodeURIComponent(authorId)}`,
    (d) => d.author?.name ?? d.author?.display_name,
  );
}

export default function AuthorProfileLayout({ children }: { children: React.ReactNode }) {
  return children;
}
