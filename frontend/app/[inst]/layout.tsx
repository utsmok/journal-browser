import { notFound } from "next/navigation";

import { InstitutionProvider } from "@/hooks/use-institution";
import { GLOBAL_SEGMENTS } from "@/lib/global-segments";
import { fetchInstitutions } from "@/lib/server-fetch";

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
  // instead of a shell that fires phantom API calls. An API outage never
  // 404s the whole institution tree.
  if (GLOBAL_SEGMENTS[inst]) notFound();
  const institutions = await fetchInstitutions();
  const row = institutions?.find((candidate) => candidate.code === inst);
  if (institutions && !row) notFound();

  return (
    <InstitutionProvider code={inst} row={row ?? null}>
      {children}
    </InstitutionProvider>
  );
}
