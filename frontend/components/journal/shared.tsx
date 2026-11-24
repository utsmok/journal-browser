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
        "inline-flex items-center gap-1 text-[var(--primary-text)] underline-offset-2 hover:underline",
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
    <button
      type="button"
      onClick={copy}
      aria-label={`${title} ${label}`}
      aria-live="polite"
      title={title}
      className="inline-flex size-6 shrink-0 items-center justify-center rounded border border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
    >
      {state === "copied" ? (
        <Check aria-hidden className="size-3.5 text-emerald-600" />
      ) : state === "failed" ? (
        <X aria-hidden className="size-3.5 text-[var(--destructive)]" />
      ) : (
        <Copy aria-hidden className="size-3.5" />
      )}
    </button>
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
      className="self-start text-sm text-[var(--muted-foreground)] underline-offset-2 hover:underline"
      aria-expanded={open}
      onClick={onToggle}
    >
      {open ? t("list.showLess") : moreLabel}
    </button>
  );
}
