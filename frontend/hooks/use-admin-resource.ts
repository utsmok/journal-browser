"use client";

import { useCallback, useEffect, useState } from "react";

import { AdminError, adminGet } from "@/lib/admin";

/**
 * One admin list resource: authenticated GET with loading/error state and a
 * manual refresh. This is the shared replacement for the per-component
 * loading/error useState machines the admin panels used to hand-roll.
 *
 * A 401 surfaces as the onUnauthorized callback (session expired or changed
 * password invalidates the HMAC token) instead of an error message; other
 * failures become a technical display message. Row-level mutation panels
 * (identity flips, feedback patches) add their own `busy`/draft state on
 * top. Form-style surfaces (deal editor, login) keep their own state
 * machines — their shapes differ enough that forcing them onto this hook
 * would trade duplication for indirection.
 */
export function useAdminResource<T>(
  path: string,
  token: string,
  onUnauthorized: () => void,
  label?: string,
) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      setData(await adminGet<T>(path, token));
      setError(null);
    } catch (err) {
      if (err instanceof AdminError && err.status === 401) {
        onUnauthorized();
        return;
      }
      setError(
        `Could not load ${label ?? path.split("?")[0]} (${err instanceof Error ? err.message : err}).`,
      );
    } finally {
      setLoading(false);
    }
  }, [path, token, onUnauthorized, label]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { data, setData, loading, error, setError, refresh };
}
