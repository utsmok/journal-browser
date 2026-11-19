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
  description,
  className,
  contentClassName,
  children,
  defaultOpen = true,
}: {
  id: string;
  title: React.ReactNode;
  description?: React.ReactNode;
  className?: string;
  contentClassName?: string;
  children: React.ReactNode;
  /** False for long reference sections (author tables, publication lists)
   * that sit below the decision content; the section nav still reaches
   * them because a matching URL hash opens the card. */
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = React.useState(defaultOpen);
  // Deep links (#section-id from the section nav or a shared URL) must not
  // land on a closed card: open when the hash matches, now and on change.
  // The section nav also announces jumps as jb-open-section events, because
  // it scrolls without changing the hash.
  React.useEffect(() => {
    const sync = () => {
      if (window.location.hash === `#${id}`) setOpen(true);
    };
    const onJump = (event: Event) => {
      if ((event as CustomEvent<string>).detail === id) setOpen(true);
    };
    sync();
    window.addEventListener("hashchange", sync);
    window.addEventListener("jb-open-section", onJump);
    return () => {
      window.removeEventListener("hashchange", sync);
      window.removeEventListener("jb-open-section", onJump);
    };
  }, [id]);
  return (
    <Card id={id} className={cn("scroll-mt-16", className)}>
      <CardHeader>
        <CardTitle>
          <button
            type="button"
            aria-expanded={open}
            aria-controls={`${id}-content`}
            onClick={() => setOpen((o) => !o)}
            className="flex w-full flex-wrap items-center gap-2 text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--primary)]"
          >
            {title}
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
      <CardContent id={`${id}-content`} className={cn(!open && "hidden", contentClassName)}>
        {children}
      </CardContent>
    </Card>
  );
}
