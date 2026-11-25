"use client";

import { useRouter } from "next/navigation";

/** Runs the server render of the current page again: the retry for a fetch
 * that failed on the server. */
export function RefreshButton({ label, className }: { label: string; className?: string }) {
  const router = useRouter();
  return (
    <button type="button" onClick={() => router.refresh()} className={className}>
      {label}
    </button>
  );
}
