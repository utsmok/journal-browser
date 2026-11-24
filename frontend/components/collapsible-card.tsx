"use client";

import { ChevronDown } from "lucide-react";
import * as React from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * Card whose header toggles the content. Content is CSS-hidden, never
 * unmounted, so state inside (pagination, charts, copy buttons) survives.
 */
export function CollapsibleCard({
  id,
  title,
  count,
  description,
  className,
  contentClassName,
  children,
  defaultOpen = true,
  compact = false,
  onOpenChange,
}: {
  id: string;
  title: React.ReactNode;
  count?: number | string;
  description?: React.ReactNode;
  className?: string;
  contentClassName?: string;
  children: React.ReactNode;
  /** False for long reference sections (author tables, publication lists)
   * that sit below the decision content; the section nav still reaches
   * them because a matching URL hash opens the card. */
  defaultOpen?: boolean;
  /** Tighter header and content padding for dense detail views. */
  compact?: boolean;
  /** Notified whenever open state changes (toggle click, hash, or nav jump). */
  onOpenChange?: (open: boolean) => void;
}) {
  const [open, setOpen] = React.useState(defaultOpen);
  const onOpenChangeRef = React.useRef(onOpenChange);
  React.useEffect(() => {
    onOpenChangeRef.current = onOpenChange;
  }, [onOpenChange]);

  const setOpenAndNotify = React.useCallback((next: boolean) => {
    setOpen(next);
    onOpenChangeRef.current?.(next);
  }, []);

  // Deep links (#section-id from the section nav or a shared URL) must not
  // land on a closed card: open when the hash matches, now and on change.
  React.useEffect(() => {
    const sync = () => {
      if (window.location.hash === `#${id}`) setOpenAndNotify(true);
    };
    const onJump = (event: Event) => {
      if ((event as CustomEvent<string>).detail === id) setOpenAndNotify(true);
    };
    sync();
    window.addEventListener("hashchange", sync);
    window.addEventListener("jb-open-section", onJump);
    return () => {
      window.removeEventListener("hashchange", sync);
      window.removeEventListener("jb-open-section", onJump);
    };
  }, [id, setOpenAndNotify]);

  return (
    <Card id={id} className={cn("scroll-mt-16", className)}>
      <CardHeader className={compact ? "px-4 py-3" : undefined}>
        <CardTitle className={compact ? "text-base" : undefined}>
          <button
            type="button"
            aria-expanded={open}
            aria-controls={`${id}-content`}
            onClick={() => setOpenAndNotify(!open)}
            className="flex w-full flex-wrap items-center gap-2 text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--primary)]"
          >
            {title}
            {count !== undefined && (
              <span className="rounded-full bg-[var(--muted)] px-2 py-0.5 text-xs font-medium tabular-nums text-[var(--muted-foreground)]">
                {typeof count === "number" ? count.toLocaleString("en") : count}
              </span>
            )}
            <ChevronDown
              aria-hidden
              className={cn(
                "ml-auto size-4 shrink-0 text-[var(--muted-foreground)] transition-transform",
                !open && "-rotate-90",
              )}
            />
          </button>
        </CardTitle>
        {description}
      </CardHeader>
      <CardContent
        id={`${id}-content`}
        className={cn(compact && "px-4 pb-4 pt-0", !open && "hidden", contentClassName)}
      >
        {children}
      </CardContent>
    </Card>
  );
}
