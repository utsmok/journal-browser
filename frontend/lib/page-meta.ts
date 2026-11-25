import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { institutionShortName } from "@/lib/server-fetch";

/** Route props of a page nested under one institution segment. */
export type InstRoute = { params: Promise<{ inst: string }> };

/**
 * Messages of a page section and the short name of its institution, loaded
 * together for the page's title and description.
 */
export async function pageContext(inst: string, namespace: string) {
  const [t, short] = await Promise.all([getTranslations(namespace), institutionShortName(inst)]);
  return { t, short };
}

/**
 * Metadata of a page that belongs to one institution: its own description
 * (which names the institution) and a canonical link to the page's path. The
 * path carries no query string, so filter and paging variants of the page
 * share one indexed URL.
 */
export function instPage(inst: string, path: string, description: string | undefined): Metadata {
  return {
    ...(description && { description }),
    alternates: { canonical: `/${inst}${path}` },
  };
}

/**
 * Metadata of a detail page: the document's title and description. A value
 * that is missing (the backend did not deliver the document) is left out, so
 * the page keeps the section title and the site description. Next drops an
 * inherited field when a layout sets it to undefined.
 */
export function docPage(
  inst: string,
  path: string,
  doc: { title?: string; description?: string },
): Metadata {
  return { ...instPage(inst, path, doc.description), ...(doc.title && { title: doc.title }) };
}
