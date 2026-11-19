import { redirect } from "next/navigation";

/** `/{inst}/journals` is a URL shape visitors plausibly guess, but the
 * search UI lives at `/{inst}`. Redirect there and keep the query string,
 * so shared or bookmarked `/ut/journals?q=…` links still land on results. */
export default async function JournalsRedirectPage({
  params,
  searchParams,
}: {
  params: Promise<{ inst: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { inst } = await params;
  const sp = await searchParams;
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(sp)) {
    if (typeof value === "string") qs.set(key, value);
    else if (Array.isArray(value)) for (const v of value) qs.append(key, v);
  }
  const query = qs.toString();
  redirect(`/${inst}${query ? `?${query}` : ""}`);
}
