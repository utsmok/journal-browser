/**
 * Synchronous client-side URLSearchParams updates via `window.history.replaceState`.
 *
 * Next.js 16 patches `window.history.replaceState` to copy its internal history
 * state and immediately sync `useSearchParams()`/`usePathname()` without firing a
 * blocking RSC server round-trip. Reading from `window.location.search` ensures
 * rapid sequential calls compose without stale React closures.
 */

export function replaceSearchParams(pathname: string, next: URLSearchParams): void {
  if (typeof window === "undefined") return;
  const qs = next.toString();
  const url = qs ? `${pathname}?${qs}` : pathname;
  window.history.replaceState(null, "", url);
}

export function patchSearchParams(
  pathname: string,
  patch: Record<string, string | undefined>,
  options?: { drop?: readonly string[] },
): void {
  if (typeof window === "undefined") return;
  const next = new URLSearchParams(window.location.search);
  for (const key of options?.drop ?? []) {
    next.delete(key);
  }
  for (const [key, value] of Object.entries(patch)) {
    if (!value) next.delete(key);
    else next.set(key, value);
  }
  replaceSearchParams(pathname, next);
}
