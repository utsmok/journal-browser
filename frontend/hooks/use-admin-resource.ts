"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

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
 *
 * `onUnauthorized` is read through a ref on purpose: callers pass inline
 * arrows, and putting it in refresh's dependency list made every fetch's
 * state update mint a new callback, re-run the effect, and refetch — an
 * unbounded request loop (223 calls in 4s on the old page).
 */
export function useAdminResource<T>(
  path: string,
  token: string,
  onUnauthorized: () => void,
  label?: string,
) {
  const t = useTranslations("admin");
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const unauthorizedRef = useRef(onUnauthorized);
  useEffect(() => {
    unauthorizedRef.current = onUnauthorized;
  });

  const refresh = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      setData(await adminGet<T>(path, token));
      setError(null);
    } catch (err) {
      if (err instanceof AdminError && err.status === 401) {
        unauthorizedRef.current();
        return;
      }
      setError(
        t("loadFailed", {
          label: label ?? path.split("?")[0],
          message: err instanceof Error ? err.message : String(err),
        }),
      );
    } finally {
      setLoading(false);
    }
  }, [path, token, label, t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { data, setData, loading, error, setError, refresh };
}
