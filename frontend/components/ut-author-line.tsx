import * as React from "react";

import type { UtAuthorAttribution } from "@/lib/api";

/** Muted "UT authors:" line under a gap-list item: semicolon-joined roster
 * matches, each with its best-known affiliation. Nothing renders when the
 * work matched no roster author. */
export function UtAuthorLine({ authors }: { authors: UtAuthorAttribution[] }) {
  if (authors.length === 0) return null;
  return (
    <p className="mt-1 w-full text-xs font-normal text-[var(--muted-foreground)]">
      UT authors:{" "}
      {authors.map((a, i) => {
        const aff = a.research_group ?? a.faculty ?? a.institute;
        return (
          <React.Fragment key={`${a.name}-${i}`}>
            {i > 0 && "; "}
            {a.name}
            {aff ? ` — ${aff}` : ""}
          </React.Fragment>
        );
      })}
    </p>
  );
}
