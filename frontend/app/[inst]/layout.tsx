import { notFound } from "next/navigation";

import { InstitutionProvider } from "@/hooks/use-institution";
import { GLOBAL_SEGMENTS } from "@/lib/global-segments";

const API = process.env.API_PROXY_URL || "http://localhost:8000";

/** Valid institution codes with their first statistics year, cached
 * briefly; null when the API is unreachable so an outage never 404s the
 * whole institution tree. */
async function institutionWindows(): Promise<Map<string, number | undefined> | null> {
  try {
    const res = await fetch(`${API}/api/v1/institutions`, { next: { revalidate: 300 } });
    if (!res.ok) return null;
    const rows = (await res.json()) as { code?: string; data_window_start?: number }[];
    return new Map(
      rows
        .filter((r): r is { code: string; data_window_start?: number } => Boolean(r.code))
        .map((r) => [r.code, r.data_window_start ?? undefined]),
    );
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
  const windows = await institutionWindows();
  if (windows && !windows.has(inst)) notFound();
  return (
    <InstitutionProvider code={inst} windowStart={windows?.get(inst)}>
      {children}
    </InstitutionProvider>
  );
}
