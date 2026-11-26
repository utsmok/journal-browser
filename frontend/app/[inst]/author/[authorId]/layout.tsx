import type { Metadata } from "next";

import { Seed } from "@/components/seed";
import type { AuthorProfile } from "@/lib/api";
import { docPage, pageContext } from "@/lib/page-meta";
import { qk } from "@/lib/query-keys";
import { fetchOrNotFound } from "@/lib/server-fetch";

type AuthorRoute = { params: Promise<{ inst: string; authorId: string }> };

/** The author document the page reads before a year lens is set. */
function loadAuthor(inst: string, authorId: string) {
  return fetchOrNotFound<AuthorProfile>({
    path: `/api/v1/${inst}/authors/${encodeURIComponent(authorId)}`,
  });
}

export async function generateMetadata({ params }: AuthorRoute): Promise<Metadata> {
  const { inst, authorId } = await params;
  const id = decodeURIComponent(authorId);
  const path = `/author/${encodeURIComponent(id)}`;
  const [{ t, short }, doc] = await Promise.all([
    pageContext(inst, "authors"),
    loadAuthor(inst, id),
  ]);
  const name = doc?.author?.name;
  return docPage(inst, path, {
    title: name,
    description: name ? t("meta.description", { name, inst: short }) : undefined,
  });
}

/** Seeds the cache, so the page renders its content on the server. */
export default async function AuthorProfileLayout({
  children,
  params,
}: AuthorRoute & { children: React.ReactNode }) {
  const { inst, authorId } = await params;
  const id = decodeURIComponent(authorId);
  return (
    <Seed queryKey={qk.author(inst, id)} data={await loadAuthor(inst, id)}>
      {children}
    </Seed>
  );
}
