import type { Metadata } from "next";

import { Seed } from "@/components/seed";
import { encodeNamePath, type PublisherDetailResponse } from "@/lib/api";
import { docPage, pageContext } from "@/lib/page-meta";
import { qk } from "@/lib/query-keys";
import { fetchForRender } from "@/lib/server-fetch";

type PublisherRoute = { params: Promise<{ inst: string; slug: string[] }> };

/** The publisher document the page reads before a year lens is set. */
function loadPublisher(inst: string, name: string) {
  return fetchForRender<PublisherDetailResponse>({
    path: `/api/v1/${inst}/publishers/${encodeNamePath(name)}`,
    query: { include_gaps: "false" },
  });
}

export async function generateMetadata({ params }: PublisherRoute): Promise<Metadata> {
  const { inst, slug } = await params;
  const name = slug.map(decodeURIComponent).join("/");
  const path = `/publisher/${encodeNamePath(name)}`;
  const [{ t, short }, doc] = await Promise.all([
    pageContext(inst, "publishers"),
    loadPublisher(inst, name),
  ]);
  const publisher = doc?.publisher?.name ?? undefined;
  return docPage(inst, path, {
    title: publisher,
    description: publisher ? t("meta.description", { name: publisher, inst: short }) : undefined,
  });
}

/** Seeds the cache, so the page renders its content on the server. */
export default async function PublisherProfileLayout({
  children,
  params,
}: PublisherRoute & { children: React.ReactNode }) {
  const { inst, slug } = await params;
  const name = slug.map(decodeURIComponent).join("/");
  return (
    <Seed queryKey={qk.publisher(inst, name)} data={await loadPublisher(inst, name)}>
      {children}
    </Seed>
  );
}
