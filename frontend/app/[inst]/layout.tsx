import { notFound } from "next/navigation";

import { Seed } from "@/components/seed";
import { InstitutionProvider } from "@/hooks/use-institution";
import { type LimitationOut, limitationsRequest } from "@/lib/api";
import { GLOBAL_SEGMENTS } from "@/lib/global-segments";
import { qk } from "@/lib/query-keys";
import { fetchInstitutions, fetchForRender } from "@/lib/server-fetch";

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
  // The source-note limitations every institution page can show. The
  // directory and freshness the site chrome reads are seeded by the root
  // layout, above the header.
  const [institutions, limitations] = await Promise.all([
    fetchInstitutions(),
    fetchForRender<LimitationOut[]>(limitationsRequest(inst)),
  ]);
  const row = institutions?.find((candidate) => candidate.code === inst);
  if (institutions && !row) notFound();

  return (
    <InstitutionProvider code={inst} row={row ?? null}>
      <Seed queryKey={qk.limitations(inst)} data={limitations}>
        {children}
      </Seed>
    </InstitutionProvider>
  );
}
