"use client";

import { usePathname, useSearchParams } from "next/navigation";
import * as React from "react";

import {
  readCollabParams,
  writeCollabParams,
  type UpdateParams,
} from "@/components/collaborations/collab-params";
import { replaceSearchParams } from "@/lib/url-params";

/** `[params, update]`: the filters in the URL and their updater. */
export function useCollabParams() {
  const sp = useSearchParams();
  const pathname = usePathname();
  const params = React.useMemo(() => readCollabParams(sp), [sp]);
  const update: UpdateParams = React.useCallback(
    (patch) => {
      const current = readCollabParams(
        new URLSearchParams(typeof window !== "undefined" ? window.location.search : sp.toString()),
      );
      const qs = writeCollabParams({ ...current, ...patch });
      replaceSearchParams(pathname, new URLSearchParams(qs));
    },
    [pathname, sp],
  );
  return [params, update] as const;
}
