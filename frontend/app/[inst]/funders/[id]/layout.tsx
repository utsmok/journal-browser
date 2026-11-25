import type { Metadata } from "next";

import { Seed } from "@/components/seed";
import type { FunderDetailResponse } from "@/lib/api";
import { docPage, pageContext } from "@/lib/page-meta";
import { qk } from "@/lib/query-keys";
import { fetchForRender } from "@/lib/server-fetch";

type FunderRoute = { params: Promise<{ inst: string; id: string }> };

/** The funder document the page reads before a year lens is set. */
function loadFunder(inst: string, id: number) {
  return fetchForRender<FunderDetailResponse>({ path: `/api/v1/${inst}/funders/${id}` });
}

export async function generateMetadata({ params }: FunderRoute): Promise<Metadata> {
  const { inst, id } = await params;
  const numericId = Number(id);
  const [{ t, short }, doc] = await Promise.all([
    pageContext(inst, "funders"),
    Number.isFinite(numericId) ? loadFunder(inst, numericId) : null,
  ]);
  const name = doc?.name ?? undefined;
  return docPage(inst, `/funders/${numericId}`, {
    title: name,
    description: name ? t("meta.description", { name, inst: short }) : undefined,
  });
}

/** Seeds the cache, so the page renders its content on the server. */
export default async function FunderLayout({
  children,
  params,
}: FunderRoute & { children: React.ReactNode }) {
  const { inst, id } = await params;
  const numericId = Number(id);
  // The page disables its query for a non-numeric id and keys it with 0.
  const idForKey = Number.isFinite(numericId) ? numericId : 0;
  const data = Number.isFinite(numericId) ? await loadFunder(inst, numericId) : null;
  return (
    <Seed queryKey={qk.funder(inst, idForKey)} data={data}>
      {children}
    </Seed>
  );
}
