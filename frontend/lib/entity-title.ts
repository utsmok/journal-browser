import type { Metadata } from "next";

const API = process.env.API_PROXY_URL || "http://localhost:8000";

/**
 * Best-effort fetch of an entity display name for the document title.
 * Any failure yields no title, so the layout/institution default applies.
 */
export async function fetchEntityTitle<T>(
  path: string,
  pick: (data: T) => string | null | undefined,
): Promise<Metadata> {
  try {
    const res = await fetch(`${API}${path}`, { cache: "no-store" });
    if (res.ok) {
      const name = pick((await res.json()) as T);
      if (name) return { title: name };
    }
  } catch {
    // Document title is cosmetic; the page still renders.
  }
  return {};
}
