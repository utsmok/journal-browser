import type { Metadata } from "next";

import { fetchEntityTitle } from "@/lib/entity-title";

/** Per-funder document title; falls back to the layout default on failure. */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ inst: string; id: string }>;
}): Promise<Metadata> {
  const { inst, id } = await params;
  return fetchEntityTitle<{ name?: string | null }>(
    `/api/v1/${encodeURIComponent(inst)}/funders/${encodeURIComponent(id)}`,
    (d) => d.name,
  );
}

export default function FunderLayout({ children }: { children: React.ReactNode }) {
  return children;
}
