/**
 * Ordered registry mapping app pathnames to the entity a page view is
 * about, so usage events can join onto journals/funders/authors/etc.
 * A path matching no pattern (landing, docs, admin, ...) has no ref.
 */

export type UsageRefType = "journal" | "funder" | "author" | "orgunit" | "publisher";

export type UsageRef = { ref_type: UsageRefType; ref_id: string };

type Pattern = {
  pattern: RegExp;
  extract: (m: RegExpMatchArray) => UsageRef;
};

const decode = (seg: string): string => {
  try {
    return decodeURIComponent(seg);
  } catch {
    return seg;
  }
};

/** Catch-all name paths (/orgunit/[level]/[...name], /publisher/[...slug])
 * join their decoded segments back into one id. */
const REGISTRY: Pattern[] = [
  {
    pattern: /^\/[^/]+\/journals\/([^/]+)/,
    extract: (m) => ({ ref_type: "journal", ref_id: decode(m[1]) }),
  },
  {
    pattern: /^\/[^/]+\/funders\/([^/]+)/,
    extract: (m) => ({ ref_type: "funder", ref_id: decode(m[1]) }),
  },
  {
    pattern: /^\/[^/]+\/author\/([^/]+)/,
    extract: (m) => ({ ref_type: "author", ref_id: decode(m[1]) }),
  },
  {
    pattern: /^\/[^/]+\/orgunit\/[^/]+\/(.+)/,
    extract: (m) => ({
      ref_type: "orgunit",
      ref_id: m[1].split("/").map(decode).join("/"),
    }),
  },
  {
    pattern: /^\/[^/]+\/publisher\/(.+)/,
    extract: (m) => ({
      ref_type: "publisher",
      ref_id: m[1].split("/").map(decode).join("/"),
    }),
  },
];

export function refForPath(pathname: string): UsageRef | null {
  for (const { pattern, extract } of REGISTRY) {
    const m = pathname.match(pattern);
    if (m) return extract(m);
  }
  return null;
}
