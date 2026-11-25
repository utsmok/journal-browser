import type { Metadata } from "next";

import { Seed } from "@/components/seed";
import { encodeNamePath, type OrgUnitDetailResponse, type OrgUnitLevel } from "@/lib/api";
import { docPage, pageContext } from "@/lib/page-meta";
import { qk } from "@/lib/query-keys";
import { fetchForRender } from "@/lib/server-fetch";

const LEVELS: OrgUnitLevel[] = ["faculty", "group", "institute"];

type OrgUnitRoute = { params: Promise<{ inst: string; slug: string[] }> };

function splitSlug(slug: string[]): { level: OrgUnitLevel | undefined; name: string } {
  const [levelSeg, ...nameSegs] = slug;
  return {
    level: LEVELS.find((level) => level === levelSeg),
    name: nameSegs.map(decodeURIComponent).join("/"),
  };
}

/** The unit document the page reads before a year lens or author sort is set. */
function loadOrgUnit(inst: string, level: OrgUnitLevel, name: string) {
  return fetchForRender<OrgUnitDetailResponse>({
    path: `/api/v1/${inst}/orgunits/${level}/${encodeNamePath(name)}`,
    query: { include_gaps: "false", sort: "share" },
  });
}

export async function generateMetadata({ params }: OrgUnitRoute): Promise<Metadata> {
  const { inst, slug } = await params;
  const { level, name } = splitSlug(slug);
  const [{ t, short }, doc] = await Promise.all([
    pageContext(inst, "orgunits"),
    level ? loadOrgUnit(inst, level, name) : null,
  ]);
  const unit = doc?.unit?.name ?? undefined;
  return docPage(inst, level ? `/orgunit/${level}/${encodeNamePath(name)}` : "/orgunit", {
    title: unit,
    description: unit ? t("meta.description", { name: unit, inst: short }) : undefined,
  });
}

/** Seeds the cache, so the page renders its content on the server. */
export default async function OrgUnitLayout({
  children,
  params,
}: OrgUnitRoute & { children: React.ReactNode }) {
  const { inst, slug } = await params;
  const { level, name } = splitSlug(slug);
  // Any other level renders the page's unknown-type notice.
  if (!level) return children;
  return (
    <Seed queryKey={qk.orgunit(inst, level, name)} data={await loadOrgUnit(inst, level, name)}>
      {children}
    </Seed>
  );
}
