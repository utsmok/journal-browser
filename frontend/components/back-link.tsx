import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { cn } from "@/lib/utils";

/** Inline "back" navigation: arrow plus label in the shared link style. */
export function BackLink({
  href,
  label,
  className,
}: {
  href: string;
  label: string;
  className?: string;
}) {
  return (
    <Link
      href={href}
      className={cn(
        className,
        "inline-flex items-center gap-1 text-sm text-[var(--primary-text)] underline-offset-4 hover:underline",
      )}
    >
      <ArrowLeft aria-hidden className="size-4" /> {label}
    </Link>
  );
}
