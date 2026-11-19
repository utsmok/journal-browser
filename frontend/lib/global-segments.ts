/**
 * Top-level path segments that are global routes, not institution codes.
 * Nav, footer, and hooks must never treat these as an institution scope;
 * unknown institution codes are rejected in app/[inst]/layout.tsx against
 * the institutions directory instead of by a blacklist here.
 */
export const GLOBAL_SEGMENTS: Record<string, true> = {
  admin: true,
  "data-pipeline": true,
};

/** Institution segment for a top-level path segment: "" when global. */
export function instFromSegment(seg: string): string {
  return seg && !GLOBAL_SEGMENTS[seg] ? seg : "";
}
