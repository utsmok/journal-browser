import { notFound } from "next/navigation";

import type { InstitutionDirectoryEntry } from "@/lib/admin";
import { InstitutionProvider } from "@/hooks/use-institution";
import { GLOBAL_SEGMENTS } from "@/lib/global-segments";

const API = process.env.API_PROXY_URL || "http://localhost:8000";

/** Valid institution codes with their full directory rows, cached briefly;
 * null when the API is unreachable so an outage never 404s the whole
 * institution tree. */
async function institutionDirectory(): Promise<Map<string, InstitutionDirectoryEntry> | null> {
  try {
    const res = await fetch(`${API}/api/v1/institutions`, { next: { revalidate: 300 } });
    if (!res.ok) return null;
    const rows = (await res.json()) as InstitutionDirectoryEntry[];
    return new Map(
      rows
        .filter((r): r is InstitutionDirectoryEntry & { code: string } => Boolean(r.code))
        .map((r) => [r.code, r]),
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
  const directory = await institutionDirectory();
  if (directory && !directory.has(inst)) notFound();
  return (
    <InstitutionProvider
      code={inst}
      windowStart={directory?.get(inst)?.data_window_start}
      directory={directory?.get(inst)}
    >
      {children}
    </InstitutionProvider>
  );
}
