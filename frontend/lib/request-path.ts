import { headers } from "next/headers";

import { instFromSegment } from "@/lib/global-segments";

/**
 * Request header that proxy.ts sets to the page path. Next does not pass the
 * path to layouts, but the root layout renders the site header and footer
 * and seeds their documents for the institution in the first URL segment.
 */
export const PATH_HEADER = "x-jb-path";

/** Institution code of the page being rendered: "" on global pages. */
export async function requestInst(): Promise<string> {
  const path = (await headers()).get(PATH_HEADER) ?? "/";
  return instFromSegment(path.split("/")[1] ?? "");
}
