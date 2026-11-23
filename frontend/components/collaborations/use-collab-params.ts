"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import {
  COLLAB_MULTI_KEYS,
  type CollaborationLevel,
  type CollaborationSearchParams,
  type CollaborationSort,
} from "@/lib/api";

const LEVELS: readonly CollaborationLevel[] = ["faculty", "group", "institute"];
const SORTS: readonly CollaborationSort[] = ["works", "name", "corresponding_works"];

/** Replaces the given filter keys and keeps the rest. A key set to `undefined`
 * returns to its default. */
export type UpdateParams = (patch: Partial<CollaborationSearchParams>) => void;

/** The filters kept in the page URL, so that a filtered view reloads and can
 * be shared. The name search and the years live elsewhere: the search in page
 * state, the years in the header's year control. */
export function readCollabParams(sp: URLSearchParams): CollaborationSearchParams {
  const out: CollaborationSearchParams = {};
  for (const key of COLLAB_MULTI_KEYS) {
    const values = (sp.get(key) ?? "").split("|").filter(Boolean);
    if (values.length) out[key] = values;
  }
  const level = sp.get("level");
  if (level && LEVELS.includes(level as CollaborationLevel)) {
    out.level = level as CollaborationLevel;
  }
  const sort = sp.get("sort");
  if (sort && SORTS.includes(sort as CollaborationSort)) {
    out.sort = sort as CollaborationSort;
  }
  const dir = sp.get("dir");
  if (dir === "asc" || dir === "desc") out.dir = dir;
  return out;
}

export function writeCollabParams(p: CollaborationSearchParams): string {
  const sp = new URLSearchParams();
  for (const key of COLLAB_MULTI_KEYS) {
    if (p[key]?.length) sp.set(key, p[key].join("|"));
  }
  if (p.level) sp.set("level", p.level);
  if (p.sort) sp.set("sort", p.sort);
  if (p.dir) sp.set("dir", p.dir);
  return sp.toString();
}

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
