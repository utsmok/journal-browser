import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Seed } from "@/components/seed";
import type { FunderDetailResponse } from "@/lib/api";
import { docPage, pageContext } from "@/lib/page-meta";
import { qk } from "@/lib/query-keys";
import { fetchOrNotFound } from "@/lib/server-fetch";

type FunderRoute = { params: Promise<{ inst: string; id: string }> };

/** The funder document the page reads before a year lens is set. */
function loadFunder(inst: string, id: number) {
  return fetchOrNotFound<FunderDetailResponse>({ path: `/${inst}/funders/${id}` });
}

/** Funder ids are positive integers; anything else names no funder. */
function funderId(id: string): number {
  if (!/^\d+$/.test(id)) notFound();
  return Number(id);
}

export async function generateMetadata({ params }: FunderRoute): Promise<Metadata> {
  const { inst, id } = await params;
  const numericId = funderId(id);
  const [{ t, short }, doc] = await Promise.all([
    pageContext(inst, "funders"),
    loadFunder(inst, numericId),
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
  const numericId = funderId(id);
  return (
    <Seed queryKey={qk.funder(inst, numericId)} data={await loadFunder(inst, numericId)}>
      {children}
    </Seed>
  );
}
