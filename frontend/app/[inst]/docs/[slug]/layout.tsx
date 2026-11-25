import type { Metadata } from "next";

import { type DocDetail } from "@/lib/docs";
import { docPage } from "@/lib/page-meta";
import { fetchForRender } from "@/lib/server-fetch";

type DocRoute = { params: Promise<{ inst: string; slug: string }> };

/** Each document gets its own title and canonical URL. */
export async function generateMetadata({ params }: DocRoute): Promise<Metadata> {
  const { inst, slug } = await params;
  const doc = await fetchForRender<DocDetail>({
    path: `/api/v1/docs/${encodeURIComponent(slug)}`,
  });
  return docPage(inst, `/docs/${encodeURIComponent(slug)}`, { title: doc?.title });
}

export default function DocLayout({ children }: { children: React.ReactNode }) {
  return children;
}
