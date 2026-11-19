import { notFound } from "next/navigation";

import { InstitutionProvider } from "@/hooks/use-institution";
import { GLOBAL_SEGMENTS } from "@/lib/global-segments";

const API = process.env.API_PROXY_URL || "http://localhost:8000";

/** Valid institution codes, cached briefly; null when the API is
 * unreachable so an outage never 404s the whole institution tree. */
async function institutionCodes(): Promise<Set<string> | null> {
  try {
    const res = await fetch(`${API}/api/v1/institutions`, { next: { revalidate: 300 } });
    if (!res.ok) return null;
    const rows = (await res.json()) as { code?: string }[];
    return new Set(rows.map((r) => r.code).filter((c): c is string => Boolean(c)));
  } catch {
    return null;
  }
}

export default async function InstLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ inst: string }>;
}) {
  const { inst } = await params;
  // Global routes (admin, data-pipeline) would shadow this dynamic segment
  // only if their static routes were removed; unknown codes are a real 404
  // instead of a shell that fires phantom API calls.
  if (GLOBAL_SEGMENTS[inst]) notFound();
  const codes = await institutionCodes();
  if (codes && !codes.has(inst)) notFound();
  return <InstitutionProvider code={inst}>{children}</InstitutionProvider>;
}
