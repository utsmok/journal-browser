"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";

/** Clipboard write with transient "Copied" feedback. */
export function CopyButton({
  text,
  label,
  className,
}: {
  text: string;
  label?: string;
  className?: string;
}) {
  const t = useTranslations("admin");
  const [copied, setCopied] = useState(false);
  const copy = useCallback(() => {
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
    });
  }, [text]);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);
  return (
    <Button variant="outline" size="sm" className={className} onClick={copy}>
      {copied ? t("copy.copied") : (label ?? t("copy.json"))}
    </Button>
  );
}

/** One label/value row in a record drawer; clicking the value copies it. */
export function RecordField({
  label,
  value,
  mono,
  href,
}: {
  label: string;
  value: string | number | boolean | null | undefined;
  mono?: boolean;
  href?: string;
}) {
  const t = useTranslations("admin");
  const display = value === null || value === undefined || value === "" ? "—" : String(value);
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <dt className="shrink-0 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd
        className={`min-w-0 break-words text-right text-sm ${mono ? "font-mono text-xs" : ""}`}
        title={href ? undefined : t("copy.clickToCopy")}
        onClick={href ? undefined : () => void navigator.clipboard.writeText(display)}
        role={href ? undefined : "button"}
      >
        {href ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="underline underline-offset-2 hover:text-[var(--primary-text)]"
          >
            {display}
          </a>
        ) : (
          display
        )}
      </dd>
    </div>
  );
}

/** Pretty-printed JSON block with a copy button — for evidence/stats payloads. */
export function RecordJson({ label, data }: { label: string; data: unknown }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
        <CopyButton text={JSON.stringify(data, null, 2)} />
      </div>
      <pre className="max-h-72 overflow-auto rounded-[var(--radius)] border bg-[var(--muted)] p-3 font-mono text-xs leading-relaxed">
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  );
}

/** Reviewer name persisted locally; sent along with flips as changed_by. */
export function useReviewer(): [string, (name: string) => void] {
  const [name, setName] = useState("");
  useEffect(() => {
    setName(window.localStorage.getItem("jb-admin-reviewer") ?? "");
  }, []);
  const update = useCallback((value: string) => {
    setName(value);
    if (value) window.localStorage.setItem("jb-admin-reviewer", value);
    else window.localStorage.removeItem("jb-admin-reviewer");
  }, []);
  return [name, update];
}
