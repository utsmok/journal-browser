"use client";

import { useEffect, useRef, useState } from "react";

/**
 * One mermaid diagram, rendered client-side. The library is imported only
 * when a diagram actually appears on the page. Always light theme: the site
 * darkens its own chrome in dark mode, but print CSS prints white paper and
 * printToPDF/Ctrl+P cannot be observed from JS — a fixed light diagram is
 * correct on both surfaces. Any failure falls back to the raw source in a
 * pre block.
 */
export function MermaidBlock({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function render() {
      try {
        // Dynamic import on purpose (task spec): mermaid is a very large
        // dependency that must stay out of every other route's bundle; load
        // it lazily, only when a page actually contains a diagram.
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({ startOnLoad: false, theme: "default" });
        const { svg } = await mermaid.render(
          `mmd-${Math.random().toString(36).slice(2)}`,
          code,
        );
        if (!cancelled && ref.current) {
          ref.current.innerHTML = svg;
          setFailed(false);
        }
      } catch (err) {
        console.error("Mermaid render failed", err);
        if (!cancelled) setFailed(true);
      }
    }

    void render();
    return () => {
      cancelled = true;
    };
  }, [code]);

  if (failed) {
    return (
      <div className="space-y-1">
        <pre className="overflow-x-auto rounded-[var(--radius)] bg-[var(--muted)] p-4 font-mono text-sm">
          {code}
        </pre>
        <p className="text-xs text-[var(--muted-foreground)]">
          Diagram could not be rendered; showing the mermaid source.
        </p>
      </div>
    );
  }
  return (
    <div
      ref={ref}
      className="overflow-x-auto rounded-[var(--radius)] bg-white p-4 dark:bg-[var(--muted)] [&_svg]:mx-auto [&_svg]:h-auto [&_svg]:max-w-full"
    />
  );
}
