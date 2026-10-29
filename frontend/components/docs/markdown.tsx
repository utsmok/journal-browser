"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { MermaidBlock } from "@/components/docs/mermaid-block";
import { useInstitution } from "@/hooks/use-institution";
import {
  parseTable,
  slugifyHeading,
  type DocBlock,
} from "@/lib/docs";

/*
 * Minimal inline markdown: **bold**, *italic*, `code`, [text](url). Link
 * targets: relative *.md → /{inst}/docs/{stem} (#anchor preserved),
 * #anchor in-page, http(s) external in a new tab.
 */
const INLINE_RE =
  /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\*[^*\n]+\*)|(\[[^\]\n]+\]\([^)\s]*\))/g;

const LINK_CLASS =
  "text-[var(--primary-text)] underline-offset-2 hover:underline";

function DocLink({ href, children }: { href: string; children: ReactNode }) {
  const inst = useInstitution();
  if (href.startsWith("#")) {
    return (
      <a href={href} className={LINK_CLASS}>
        {children}
      </a>
    );
  }
  if (/\.md(#.*)?$/i.test(href)) {
    const [path, anchor] = href.split("#");
    const stem = path.split("/").pop()!.replace(/\.md$/i, "");
    return (
      <Link
        href={`/${inst}/docs/${stem}${anchor ? `#${anchor}` : ""}`}
        className={LINK_CLASS}
      >
        {children}
      </Link>
    );
  }
  const external = /^https?:\/\//i.test(href);
  return (
    <a
      href={href}
      {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}
      className={LINK_CLASS}
    >
      {children}
    </a>
  );
}

export function renderInline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let k = 0;
  for (const m of text.matchAll(INLINE_RE)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("`")) {
      out.push(
        <code
          key={k++}
          className="rounded bg-[var(--muted)] px-1 py-0.5 font-mono text-[0.9em]"
        >
          {tok.slice(1, -1)}
        </code>,
      );
    } else if (tok.startsWith("**")) {
      out.push(<strong key={k++}>{renderInline(tok.slice(2, -2))}</strong>);
    } else if (tok.startsWith("*")) {
      out.push(<em key={k++}>{renderInline(tok.slice(1, -1))}</em>);
    } else {
      const cut = tok.indexOf("](");
      out.push(
        <DocLink key={k++} href={tok.slice(cut + 2, -1)}>
          {renderInline(tok.slice(1, cut))}
        </DocLink>,
      );
    }
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// --- Block rendering -------------------------------------------------------

function headingTag(level: number): "h2" | "h3" | "h4" {
  // h1 is the doc title in the masthead; deeper levels clamp at h4.
  return level >= 4 ? "h4" : level === 3 ? "h3" : "h2";
}

function listItems(text: string): { ordered: boolean; items: string[] } {
  const lines = text.split("\n").filter((l) => l.trim());
  const ordered = /^\s*\d+[.)]\s/.test(lines[0] ?? "");
  const items = lines.map((l) =>
    l.replace(/^\s*(?:[-*+]|\d+[.)])\s+/, ""),
  );
  return { ordered, items };
}

function CodeView({ block }: { block: DocBlock }) {
  // Fences are block syntax, not content: strip them if the backend keeps them.
  const lines = block.text.split("\n");
  const body =
    lines[0]?.startsWith("```") && lines.at(-1)?.startsWith("```")
      ? lines.slice(1, -1).join("\n")
      : block.text;
  return (
    <pre className="overflow-x-auto rounded-[var(--radius)] bg-[var(--muted)] p-4 font-mono text-sm leading-relaxed">
      {body}
    </pre>
  );
}

/** Pure view of one doc block; edit chrome lives in the reader page. */
export function BlockContent({ block }: { block: DocBlock }) {
  switch (block.type) {
    case "heading": {
      const m = block.text.match(/^(#{1,6})\s+/);
      const level = block.level ?? (m ? m[1].length : 2);
      // Level 1 is the doc title; the masthead band already renders it.
      if (level === 1) return null;
      const text = block.text.replace(/^#{1,6}\s+/, "");
      const Tag = headingTag(level);
      return (
        <Tag id={slugifyHeading(text)} className="scroll-mt-20 pt-4 font-bold">
          {renderInline(text)}
        </Tag>
      );
    }
    case "paragraph":
      return <p className="whitespace-pre-line">{renderInline(block.text)}</p>;
    case "list": {
      const { ordered, items } = listItems(block.text);
      const List = ordered ? "ol" : "ul";
      return (
        <List
          className={`space-y-1 pl-6 ${ordered ? "list-decimal" : "list-disc"}`}
        >
          {items.map((item, i) => (
            <li key={i} className="whitespace-pre-line">
              {renderInline(item)}
            </li>
          ))}
        </List>
      );
    }
    case "table": {
      // Full markup (incl. cell wrappers) lives with the editor in the reader;
      // this static view is for non-editing contexts.
      return <TableMarkup block={block} />;
    }
    case "code":
      return block.lang === "mermaid" ? (
        <MermaidBlock code={block.text.replace(/^```mermaid\n|\n```$/g, "")} />
      ) : (
        <CodeView block={block} />
      );
    case "quote":
      return (
        <blockquote className="rounded-[var(--radius)] bg-[var(--muted)] px-4 py-3">
          <p className="whitespace-pre-line">
            {renderInline(block.text.replace(/^>\s?/gm, ""))}
          </p>
        </blockquote>
      );
    case "hr":
      return <hr className="border-[var(--border)]" />;
  }
}

export function TableMarkup({
  block,
  cell,
  onCellDoubleClick,
  onCellKeyDown,
  cellRef,
  children,
}: {
  block: DocBlock;
  cell?: { row: number; col: number } | null;
  onCellDoubleClick?: (row: number, col: number) => void;
  onCellKeyDown?: (e: React.KeyboardEvent<HTMLTableCellElement>) => void;
  cellRef?: React.Ref<HTMLTableCellElement>;
  children?: React.ReactNode;
}) {
  const rows = parseTable(block.text);
  const header = rows[1]?.align ? rows[0] : null;
  const body = header ? rows.slice(2) : rows;
  const cellClass =
    "border-b border-[var(--border)] px-3 py-2 align-top tabular-nums";
  return (
    <div className="relative w-full overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        {header && (
          <thead>
            <tr className="bg-[var(--muted)] text-left">
              {header.cells.map((c, j) => (
                <th key={j} scope="col" className={`${cellClass} font-semibold`}>
                  {renderInline(c)}
                </th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {body.map((r, i) => (
            <tr key={i}>
              {r.cells.map((c, j) => {
                const active =
                  cell != null && cell.row === i + (header ? 2 : 0) && cell.col === j;
                return (
                  <td
                    key={j}
                    ref={active ? cellRef : undefined}
                    contentEditable={active || undefined}
                    suppressContentEditableWarning
                    onDoubleClick={
                      onCellDoubleClick
                        ? () => onCellDoubleClick(i + (header ? 2 : 0), j)
                        : undefined
                    }
                    onKeyDown={active ? onCellKeyDown : undefined}
                    className={`${cellClass} ${
                      active
                        ? "cursor-text outline outline-1 outline-[var(--ring)]"
                        : ""
                    }`}
                  >
                    {active ? c : renderInline(c)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {children}
    </div>
  );
}
