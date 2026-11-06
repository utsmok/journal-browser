import type { Metadata } from "next";

import { fetchEntityTitle } from "@/lib/entity-title";

/** Per-publisher document title; falls back to the layout default on failure. */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ inst: string; slug: string[] }>;
}): Promise<Metadata> {
  const { inst, slug } = await params;
  // Catch-all params may arrive still percent-encoded; normalize before encoding.
  const enc = (s: string) => {
    try {
      return encodeURIComponent(decodeURIComponent(s));
    } catch {
      return encodeURIComponent(s);
    }
  };
  return fetchEntityTitle<{ publisher?: { name?: string | null } }>(
    `/api/v1/${encodeURIComponent(inst)}/publishers/${slug.map(enc).join("/")}`,
    (d) => d.publisher?.name,
  );
}

export default function PublisherProfileLayout({ children }: { children: React.ReactNode }) {
  return children;
}
