"use client";

import { Check, Copy, ExternalLink, X } from "lucide-react";
import * as React from "react";
import { useTranslations } from "next-intl";

import type { JournalDetailResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

export type NamedTopic = { display_name?: string };

export function External({
  href,
  children,
  className,
  title,
}: {
  href: string;
  children: React.ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title={title}
      className={cn(
        "inline-flex min-h-11 min-w-11 max-w-full items-center gap-1 text-[var(--primary-text)] underline-offset-2 hover:underline [overflow-wrap:anywhere] min-[1024px]:min-h-0 min-[1024px]:min-w-0",
        className,
      )}
    >
      {children} <ExternalLink aria-hidden className="size-3.5 shrink-0" />
    </a>
  );
}

/** Hostname of a URL, for compact license badges; falls back to the raw
    string when the value does not parse as a URL. */
export function urlHost(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

export function Metric({
  label,
  value,
  note,
  hint,
}: {
  label: string;
  value: string;
  note?: React.ReactNode;
  hint?: string;
}) {
  return (
    // Focusable so keyboard users can raise the title-tooltip too.
    <div title={hint} tabIndex={hint ? 0 : undefined}>
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
      <div className="text-xs font-medium">{label}</div>
      {note && <div className="text-[11px] text-[var(--muted-foreground)]">{note}</div>}
    </div>
  );
}

/** A 24px bordered icon box. On phones the button around it is a 44px
 * target; negative margins keep the box where the 24px button sat. */
export function IconBoxButton({ className, children, ...props }: React.ComponentProps<"button">) {
  return (
    <button
      {...props}
      className={cn(
        "inline-flex size-11 shrink-0 items-center justify-center rounded text-[var(--muted-foreground)] hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] -m-2.5 min-[1024px]:m-0 min-[1024px]:size-6",
        className,
      )}
    >
      <span className="inline-flex size-6 items-center justify-center rounded border border-[var(--border)]">
        {children}
      </span>
    </button>
  );
}

/** Clipboard write with a brief "Copied" affordance; no alerts. */
export function CopyButton({ text, label }: { text: string; label: string }) {
  const t = useTranslations("journals");
  const [state, setState] = React.useState<"idle" | "copied" | "failed">("idle");
  const timer = React.useRef<number | undefined>(undefined);
  React.useEffect(() => () => window.clearTimeout(timer.current), []);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
    timer.current = window.setTimeout(() => setState("idle"), 1500);
  };
  const title =
    state === "copied"
      ? t("list.copied")
      : state === "failed"
        ? t("list.copyFailed")
        : t("list.copy");
  return (
    <IconBoxButton
      type="button"
      onClick={copy}
      aria-label={`${title} ${label}`}
      aria-live="polite"
      title={title}
    >
      {state === "copied" ? (
        <Check aria-hidden className="size-3.5 text-emerald-600" />
      ) : state === "failed" ? (
        <X aria-hidden className="size-3.5 text-[var(--destructive)]" />
      ) : (
        <Copy aria-hidden className="size-3.5" />
      )}
    </IconBoxButton>
  );
}

export const WORKS_PAGE_SIZE = 10;

/** List caps: reference-data sections show the top slice and reveal the
 * rest on demand (limit, don't delete). */
export const TOPICS_LIMIT = 8;
export const NAMES_LIMIT = 10;
export const SIMILAR_LIMIT = 10;

export type GreenOaPolicy = NonNullable<JournalDetailResponse["green_oa"]>;
export type UtAuthorship = JournalDetailResponse["ut_authorship"];
export type OpenalexOnly = JournalDetailResponse["openalex_only"];
export function doiHref(doi: string | null): string | null {
  if (!doi) return null;
  return /^https?:\/\//.test(doi) ? doi : `https://doi.org/${doi}`;
}

/** Reveal control for capped lists; matches the author-page pattern. */
export function MoreToggle({
  open,
  onToggle,
  moreLabel,
}: {
  open: boolean;
  onToggle: () => void;
  moreLabel: string;
}) {
  const t = useTranslations("journals");
  return (
    <button
      type="button"
      className="inline-flex min-h-11 self-start items-center text-sm text-[var(--muted-foreground)] underline-offset-2 hover:underline min-[1024px]:min-h-0"
      aria-expanded={open}
      onClick={onToggle}
    >
      {open ? t("list.showLess") : moreLabel}
    </button>
  );
}
