"use client";

import { ExternalLink, Info } from "lucide-react";
import * as React from "react";

import { useLimitations } from "@/hooks/use-api";
import { cn } from "@/lib/utils";

type SourceNoteProps = {
  /** Data source label, e.g. "OpenAlex". */
  source?: string;
  /** Upstream documentation link for the source itself. */
  url?: string | null;
  /** Caveat codes resolved against /api/v1/meta/limitations. */
  codes?: string[];
  className?: string;
};

/**
 * Inline data-provenance marker. Shows the source label; hovering/focusing
 * reveals the limitation registry entries (scope, hint, severity, url) for
 * this data's caveat codes. Renders a plain label if codes are unknown.
 */
export function SourceNote({ source, url, codes, className }: SourceNoteProps) {
  const { data: limitations } = useLimitations();
  const caveats = (limitations ?? []).filter((l) => codes?.includes(l.code));
  const tooltipId = React.useId();
  const hasTooltip = caveats.length > 0 || Boolean(url);

  return (
    <span
      tabIndex={0}
      {...(hasTooltip ? { "aria-describedby": tooltipId } : {})}
      className={cn(
        "group relative inline-flex cursor-help items-center gap-1 align-baseline text-xs text-[var(--muted-foreground)]",
        className,
      )}
    >
      <Info aria-hidden className="size-3 shrink-0" />
      <span>{source ?? "Source"}</span>
      {hasTooltip && (
        <span
          role="tooltip"
          id={tooltipId}
          className="absolute bottom-full left-0 z-50 mb-1.5 hidden w-80 max-w-[calc(100vw-2.5rem)] rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-3 text-left text-xs shadow-lg after:absolute after:-bottom-1.5 after:left-0 after:right-0 after:h-1.5 after:content-[''] group-hover:block group-focus-within:block group-focus:block"
        >
          {caveats.map((c) => (
            <span key={c.code} className="mb-2 block last:mb-0">
              <span className="flex items-center gap-1.5">
                <span className="font-semibold">{c.code}</span>
                <span
                  className={cn(
                    "rounded-full px-1.5 py-px text-[10px] font-medium uppercase tracking-wide",
                    c.severity === "warning"
                      ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                      : "bg-[var(--muted)] text-[var(--muted-foreground)]",
                  )}
                >
                  {c.severity}
                </span>
              </span>
              <span className="mt-0.5 block text-[var(--muted-foreground)]">
                {c.hint} <span className="opacity-70">({c.scope})</span>
              </span>
              {c.url && (
                <a
                  href={c.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-0.5 inline-flex items-center gap-0.5 text-[var(--primary-text)] underline-offset-2 hover:underline"
                >
                  More info <ExternalLink aria-hidden className="size-3" />
                </a>
              )}
            </span>
          ))}
          {url && (
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 flex items-center gap-0.5 border-t border-[var(--border)] pt-2 text-[var(--primary-text)] underline-offset-2 hover:underline"
            >
              {url.replace(/^https?:\/\//, "")} <ExternalLink aria-hidden className="size-3" />
            </a>
          )}
        </span>
      )}
    </span>
  );
}
