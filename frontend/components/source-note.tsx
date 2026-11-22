"use client";

import { ExternalLink, GitBranch, Info } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { useTranslations } from "next-intl";

import { useLimitations } from "@/hooks/use-api";
import { cn } from "@/lib/utils";

type SourceNoteProps = {
  /** Data source label, e.g. "OpenAlex". */
  source?: string;
  /** Upstream documentation link for the source itself. */
  url?: string | null;
  /** Caveat codes resolved against /api/v1/meta/limitations. */
  codes?: string[];
  /** Optional anchor inside /data-pipeline explaining how this data is matched/processed. */
  processAnchor?: string;
  className?: string;
};

/**
 * Inline data-provenance marker. Shows the source label; hovering/focusing
 * reveals the limitation registry entries (scope, hint, severity, url) for
 * this data's caveat codes, plus a direct link to the processing rules on
 * /data-pipeline when processAnchor is provided.
 */
export function SourceNote({ source, url, codes, processAnchor, className }: SourceNoteProps) {
  const t = useTranslations("common");
  const { data: limitations } = useLimitations();
  const caveats = (limitations ?? []).filter((l) => codes?.includes(l.code));
  const tooltipId = React.useId();
  const hasTooltip = caveats.length > 0 || Boolean(url) || Boolean(processAnchor);

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
      <span>{source ?? t("sourceNote.fallbackLabel")}</span>
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
                  {t("sourceNote.moreInfo")} <ExternalLink aria-hidden className="size-3" />
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
          {processAnchor && (
            <Link
              href={`/data-pipeline#${processAnchor}`}
              className={cn(
                "flex items-center gap-1 text-[var(--primary-text)] underline-offset-2 hover:underline",
                url || caveats.length > 0 ? "mt-2 border-t border-[var(--border)] pt-2" : "",
              )}
            >
              <GitBranch aria-hidden className="size-3 shrink-0" />
              {t("sourceNote.howProcessed")} →
            </Link>
          )}
        </span>
      )}
    </span>
  );
}

/** Direct, always-visible link from any data section to its matching
 * methodology & processing rules on /data-pipeline. */
export function ProcessLink({
  anchor,
  label,
  className,
}: {
  anchor: string;
  label?: string;
  className?: string;
}) {
  const t = useTranslations("common");
  return (
    <Link
      href={`/data-pipeline#${anchor}`}
      className={cn(
        "inline-flex items-center gap-1 text-xs font-medium text-[var(--primary-text)] underline-offset-2 hover:underline",
        className,
      )}
    >
      <GitBranch aria-hidden className="size-3 shrink-0" />
      <span>{label ?? t("sourceNote.howBuilt")}</span>
    </Link>
  );
}
