"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { EditToolbar } from "@/components/docs/edit-toolbar";
import { BlockContent, TableMarkup } from "@/components/docs/markdown";
import { Button } from "@/components/ui/button";
import { useInstitution } from "@/hooks/use-institution";
import {
  AdminError,
  adminDelete,
  adminPut,
  useAdminToken,
} from "@/lib/admin";
import { errorMessage } from "@/lib/api";
import {
  GROUP_LABEL,
  fetchDoc,
  fetchDocs,
  parseTable,
  replaceCell,
  sha256Hex,
  sortDocs,
  type DocBlock,
  type DocDetail,
} from "@/lib/docs";
import { cn } from "@/lib/utils";

/** Auth failures bubble to the toolbar instead of each block. */
type SaveResult = Promise<string | null>;

export default function DocPage() {
  const inst = useInstitution();
  const { slug } = useParams<{ slug: string }>();
  const [token, setToken] = useAdminToken();
  const [editing, setEditing] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const qc = useQueryClient();

  const doc = useQuery({
    queryKey: ["docs", inst, slug],
    queryFn: () => fetchDoc(slug),
  });
  const index = useQuery({ queryKey: ["docs", inst], queryFn: fetchDocs });
  const ordered = useMemo(() => sortDocs(index.data ?? []), [index.data]);
  const pos = ordered.findIndex((d) => d.slug === slug);
  const prev = pos > 0 ? ordered[pos - 1] : null;
  const next = pos >= 0 && pos < ordered.length - 1 ? ordered[pos + 1] : null;

  const editedCount =
    doc.data?.blocks.filter((b) => b.edited).length ?? 0;
  const canEdit = editing && !!token;

  function handleAuthFailure() {
    setToken(null);
    setEditing(false);
    setAuthError("Session expired — sign in again.");
  }

  function failure(err: unknown): string | null {
    if (err instanceof AdminError && (err.status === 401 || err.status === 403)) {
      handleAuthFailure();
      return null;
    }
    console.error(err);
    return err instanceof AdminError
      ? `Admin request failed (${err.message})`
      : String(err);
  }

  async function saveBlock(
    block: DocBlock,
    replacement: string,
  ): SaveResult {
    try {
      await adminPut(
        `/docs/${slug}/edits`,
        token!,
        {
          block_key: block.key,
          // Hash of the text the editor saw, per contract.
          original_hash: await sha256Hex(block.text),
          replacement,
        },
      );
      // Swap the edited block in place; the list refetch refreshes counts.
      qc.setQueryData<DocDetail>(["docs", inst, slug], (d) =>
        d
          ? {
              ...d,
              blocks: d.blocks.map((b) =>
                b.key === block.key
                  ? { ...b, text: replacement, edited: true }
                  : b,
              ),
            }
          : d,
      );
      qc.invalidateQueries({ queryKey: ["docs", inst] });
      return null;
    } catch (err) {
      return failure(err);
    }
  }

  async function revertBlock(block: DocBlock): SaveResult {
    try {
      await adminDelete(
        `/docs/${slug}/edits/${encodeURIComponent(block.key)}`,
        token!,
      );
      // The server restores the original text; refetch to see it.
      qc.invalidateQueries({ queryKey: ["docs", inst] });
      return null;
    } catch (err) {
      return failure(err);
    }
  }

  return (
    <div className="docs-page">
      <EditToolbar
        token={token}
        onToken={setToken}
        editing={editing}
        setEditing={setEditing}
        authError={authError}
      />

      <div className="border-b border-[var(--border)] bg-[var(--muted)]">
        <div className="docs-page-column mx-auto max-w-[72ch] px-4 py-8">
          <Link
            href={`/${inst}/docs`}
            className="text-sm text-[var(--primary-text)] underline-offset-2 hover:underline"
          >
            ← All docs
          </Link>
          {doc.data && (
            <>
              <h1 className="mt-2 text-3xl font-bold">{doc.data.title}</h1>
              <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                {GROUP_LABEL[doc.data.group]} · {doc.data.blocks.length} blocks
                {editedCount > 0 && ` · ${editedCount} edited locally`}
              </p>
            </>
          )}
        </div>
      </div>

      <div className="docs-page-column mx-auto max-w-[72ch] space-y-6 px-4 py-10 text-[15px] leading-relaxed">
        {doc.isPending && (
          <p className="text-[var(--muted-foreground)]">Loading…</p>
        )}
        {doc.isError && (
          <p className="text-destructive">
            {errorMessage(doc.error)}{" "}
            <Link
              href={`/${inst}/docs`}
              className="text-[var(--primary-text)] underline-offset-2 hover:underline"
            >
              Back to the index.
            </Link>
          </p>
        )}
        {doc.data?.blocks.map((b) => {
          if (b.type === "hr") return <BlockContent key={b.key} block={b} />;
          if (b.type === "table")
            return (
              <EditableTable
                key={b.key}
                block={b}
                canEdit={canEdit}
                onSave={saveBlock}
                onRevert={revertBlock}
              />
            );
          return (
            <EditableTextBlock
              key={b.key}
              block={b}
              canEdit={canEdit}
              onSave={saveBlock}
              onRevert={revertBlock}
            />
          );
        })}

        {(prev || next) && (
          <nav className="mt-12 flex items-start justify-between gap-6 border-t border-[var(--border)] pt-4 text-sm">
            {prev ? (
              <Link
                href={`/${inst}/docs/${prev.slug}`}
                className="text-[var(--primary-text)] underline-offset-2 hover:underline"
              >
                ← {prev.title}
              </Link>
            ) : (
              <span />
            )}
            {next && (
              <Link
                href={`/${inst}/docs/${next.slug}`}
                className="text-right text-[var(--primary-text)] underline-offset-2 hover:underline"
              >
                {next.title} →
              </Link>
            )}
          </nav>
        )}
      </div>
    </div>
  );
}

// --- Block editors ---------------------------------------------------------

function EditedDot() {
  return (
    <span
      title="Edited on this server"
      className="absolute -right-3 top-2 size-2 rounded-full bg-[var(--primary-text)]"
    />
  );
}

function RevertButton({
  onRevert,
  block,
  busy,
}: {
  onRevert: (block: DocBlock) => SaveResult;
  block: DocBlock;
  busy: boolean;
}) {
  const [error, setError] = useState<string | null>(null);
  return (
    <span className="mt-1 flex items-center gap-2 text-xs">
      <Button
        size="sm"
        variant="ghost"
        className="h-6 px-2"
        disabled={busy}
        onClick={async () => setError(await onRevert(block))}
      >
        Revert
      </Button>
      {error && <span className="text-destructive">{error}</span>}
    </span>
  );
}

/** Text-ish blocks (heading, paragraph, list, quote, code): dblclick swaps
 * in an autosized raw-markdown textarea. */
function EditableTextBlock({
  block,
  canEdit,
  onSave,
  onRevert,
}: {
  block: DocBlock;
  canEdit: boolean;
  onSave: (block: DocBlock, replacement: string) => SaveResult;
  onRevert: (block: DocBlock) => SaveResult;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const areaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = areaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${el.scrollHeight}px`;
    }
  }, [draft]);

  async function save() {
    if (busy || draft === null) return;
    setBusy(true);
    const err = await onSave(block, draft);
    setBusy(false);
    if (err) setError(err);
    else {
      setDraft(null);
      setError(null);
    }
  }

  if (draft !== null) {
    return (
      <div className="space-y-2">
        <textarea
          ref={areaRef}
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              void save();
            } else if (e.key === "Escape") {
              setDraft(null);
            }
          }}
          className="w-full resize-none overflow-hidden rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] p-2 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
        />
        <div className="flex items-center gap-2">
          <Button size="sm" disabled={busy} onClick={() => void save()}>
            Save
          </Button>
          <Button size="sm" variant="outline" onClick={() => setDraft(null)}>
            Cancel
          </Button>
          <span className="text-xs text-[var(--muted-foreground)]">
            ⌘/Ctrl+Enter saves, Esc cancels
          </span>
          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="relative">
      <div
        onDoubleClick={() => canEdit && setDraft(block.text)}
        className={cn(
          "rounded-[var(--radius)]",
          canEdit && "cursor-text hover:outline hover:outline-1 hover:outline-[var(--ring)]",
        )}
      >
        <BlockContent block={block} />
      </div>
      {block.edited && <EditedDot />}
      {canEdit && block.edited && (
        <RevertButton block={block} onRevert={onRevert} busy={busy} />
      )}
    </div>
  );
}

/** Tables: dblclick a cell to contentEditable just that cell; saving
 * serializes the whole table back with the one cell swapped. */
function EditableTable({
  block,
  canEdit,
  onSave,
  onRevert,
}: {
  block: DocBlock;
  canEdit: boolean;
  onSave: (block: DocBlock, replacement: string) => SaveResult;
  onRevert: (block: DocBlock) => SaveResult;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cell, setCell] = useState<{ row: number; col: number } | null>(null);
  const cellRef = useRef<HTMLTableCellElement>(null);
  const rows = useMemo(() => parseTable(block.text), [block.text]);

  useEffect(() => {
    const el = cellRef.current;
    if (!el) return;
    el.focus();
    const range = document.createRange();
    range.selectNodeContents(el);
    const sel = window.getSelection();
    sel?.removeAllRanges();
    sel?.addRange(range);
  }, [cell]);

  async function saveCell() {
    if (!cell || busy) return;
    const value = cellRef.current?.textContent ?? "";
    setBusy(true);
    const err = await onSave(block, replaceCell(rows, cell.row, cell.col, value));
    setBusy(false);
    if (err) setError(err);
    else {
      setCell(null);
      setError(null);
    }
  }

  return (
    <div className="relative">
      <div
        className={cn(
          "rounded-[var(--radius)]",
          canEdit && "hover:outline hover:outline-1 hover:outline-[var(--ring)]",
        )}
      >
        <TableMarkup
          block={block}
          cell={cell}
          cellRef={cellRef}
          onCellDoubleClick={canEdit ? (row, col) => setCell({ row, col }) : undefined}
          onCellKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              void saveCell();
            } else if (e.key === "Escape") {
              setCell(null);
            }
          }}
        >
          {cell && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Button size="sm" disabled={busy} onClick={() => void saveCell()}>
                Save cell
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setCell(null)}
              >
                Cancel
              </Button>
              <span className="text-xs text-[var(--muted-foreground)]">
                ⌘/Ctrl+Enter saves, Esc cancels
              </span>
              {error && <p className="text-xs text-destructive">{error}</p>}
            </div>
          )}
        </TableMarkup>
      </div>
      {block.edited && <EditedDot />}
      {canEdit && block.edited && (
        <RevertButton block={block} onRevert={onRevert} busy={busy} />
      )}
    </div>
  );
}
