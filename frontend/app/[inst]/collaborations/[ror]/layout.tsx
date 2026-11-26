import type { Metadata } from "next";

import type { CollaborationDetailResponse } from "@/lib/api";
import { docPage, pageContext } from "@/lib/page-meta";
import { fetchOrNotFound } from "@/lib/server-fetch";

type PartnerRoute = { params: Promise<{ inst: string; ror: string }> };

/** Partner title and description from the partner's overview document. */
export async function generateMetadata({ params }: PartnerRoute): Promise<Metadata> {
  const { inst, ror } = await params;
  const path = `/collaborations/${encodeURIComponent(ror)}`;
  const [{ t, short }, doc] = await Promise.all([
    pageContext(inst, "collaborations"),
    fetchOrNotFound<CollaborationDetailResponse>({
      path: `/${inst}${path}`,
      query: { include_works: "false" },
    }),
  ]);
  const name = doc?.name;
  return docPage(inst, path, {
    title: name,
    description: name ? t("meta.detailDescription", { name, inst: short }) : undefined,
  });
}

export default function PartnerLayout({ children }: { children: React.ReactNode }) {
  return children;
}
