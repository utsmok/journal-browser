import type { MetadataRoute } from "next";

import { fetchForRender, fetchInstitutions } from "@/lib/server-fetch";
import { SITE_URL } from "@/lib/site-url";

/** Main pages of every institution; the journals are reached from each home page. */
const SECTIONS = [
  "",
  "/publisher",
  "/orgunit",
  "/author",
  "/funders",
  "/collaborations",
  "/deals",
  "/about",
  "/docs",
  "/guide",
] as const;

export const dynamic = "force-dynamic";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const institutions = (await fetchInstitutions()) ?? [];
  const docs = (await fetchForRender<{ slug: string }[]>({ path: "/api/v1/docs" }, 3600)) ?? [];
  return [
    { url: `${SITE_URL}/` },
    { url: `${SITE_URL}/data-pipeline` },
    ...institutions.flatMap((inst) => [
      ...SECTIONS.map((section) => ({ url: `${SITE_URL}/${inst.code}${section}` })),
      ...docs.map((doc) => ({
        url: `${SITE_URL}/${inst.code}/docs/${encodeURIComponent(doc.slug)}`,
      })),
    ]),
  ];
}
