"use client";

import { usePathname } from "next/navigation";
import * as React from "react";

import { beginPageView, endPageView, initUsageTracking } from "@/lib/usage/tracker";

/** Mounts once inside Providers: opens/ends page-view dwell windows on
 * route change and installs the batch timer + global error listeners. */
export function UsageTracker() {
  const pathname = usePathname();
  const prev = React.useRef<string | null>(null);

  React.useEffect(() => {
    initUsageTracking();
  }, []);

  React.useEffect(() => {
    if (prev.current === pathname) return;
    prev.current = pathname;
    endPageView();
    beginPageView(pathname);
  }, [pathname]);

  return null;
}
