"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import {
  readCollabParams,
  writeCollabParams,
  type UpdateParams,
} from "@/components/collaborations/collab-params";

/** `[params, update]`: the filters in the URL and their updater. */
export function useCollabParams() {
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const params = React.useMemo(() => readCollabParams(sp), [sp]);
  const update: UpdateParams = React.useCallback(
    (patch) => {
      const qs = writeCollabParams({ ...params, ...patch });
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [params, pathname, router],
  );
  return [params, update] as const;
}
