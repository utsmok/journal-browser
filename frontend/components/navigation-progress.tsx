"use client";

import { usePathname, useSearchParams } from "next/navigation";
import * as React from "react";

const NAV_START_EVENT = "jb-nav-start";
const SAFETY_TIMEOUT_MS = 15_000;

/**
 * Signals that a programmatic route navigation (`router.push`) has started so
 * the global top progress bar activates immediately.
 */
export function startNavigationProgress(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(NAV_START_EVENT));
  }
}

function NavigationProgressInner() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [active, setActive] = React.useState(false);
  const routeKey = `${pathname ?? ""}?${searchParams?.toString() ?? ""}`;

  // Clear as soon as Next.js commits the new route.
  React.useEffect(() => {
    setActive(false);
  }, [routeKey]);

  React.useEffect(() => {
    if (!active) return;
    const timer = window.setTimeout(() => setActive(false), SAFETY_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, [active]);

  React.useEffect(() => {
    const start = () => setActive(true);
    const onClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const anchor = (event.target as HTMLElement | null)?.closest("a");
      if (!anchor) return;
      if (anchor.target && anchor.target !== "_self") return;
      if (anchor.hasAttribute("download")) return;
      const rawHref = anchor.getAttribute("href");
      if (!rawHref || rawHref.startsWith("#")) return;
      try {
        const dest = new URL(anchor.href, window.location.href);
        if (dest.origin !== window.location.origin) return;
        const currentUrl = `${window.location.pathname}${window.location.search}`;
        const nextUrl = `${dest.pathname}${dest.search}`;
        if (nextUrl === currentUrl) return;
        setActive(true);
      } catch {
        // Ignore malformed URLs
      }
    };

    window.addEventListener(NAV_START_EVENT, start);
    document.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener(NAV_START_EVENT, start);
      document.removeEventListener("click", onClick, true);
    };
  }, []);

  if (!active) return null;

  return (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed inset-x-0 top-0 z-[100] h-0.5 overflow-hidden bg-[var(--primary)]/20"
    >
      <div className="jb-indeterminate-bar h-full w-1/3 rounded-full bg-[var(--primary)]" />
    </div>
  );
}

/**
 * Top-of-viewport progress bar that triggers immediately on internal link
 * clicks or `startNavigationProgress()`, and clears once the destination
 * route commits. Uses zero i18n namespaces so root layout stays "common"-only.
 */
export function NavigationProgress() {
  return (
    <React.Suspense fallback={null}>
      <NavigationProgressInner />
    </React.Suspense>
  );
}
