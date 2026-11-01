"use client";

import { useState } from "react";

import { AdminDrawer } from "@/components/admin/drawer";
import { CopyButton, RecordField, RecordJson, useReviewer } from "@/components/admin/record";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { WorkIdentityAdmin } from "@/lib/admin";

/**
 * Decision view for one work identity: what the harvest matched, how, and
 * with what evidence — with confirm/miss/reopen actions.
 */
export function WorkIdentityDrawer({
  row,
  onClose,
  onFlip,
  busy,
}: {
  row: WorkIdentityAdmin;
  onClose: () => void;
  onFlip: (row: WorkIdentityAdmin, status: string, note: string, changedBy: string) => void;
  busy: string | null;
}) {
  const [note, setNote] = useState("");
  const [reviewer, setReviewer] = useReviewer();
  const key = `${row.institution_id}:${row.source}:${row.source_pk}`;
  const flip = (status: string) => onFlip(row, status, note, reviewer);

  return (
    <AdminDrawer title="Work identity review" onClose={onClose}>
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate text-base font-semibold">{row.work_title ?? row.work_id}</p>
            <p className="text-xs text-muted-foreground">
              {row.source} · matched by {row.matched_by}
              {row.confidence != null ? ` · confidence ${row.confidence}` : ""}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge
              variant={
                row.status === "confirmed"
                  ? "default"
                  : row.status === "missing"
                    ? "outline"
                    : "muted"
              }
            >
              {row.status}
            </Badge>
            <CopyButton text={JSON.stringify(row, null, 2)} label="Copy record" />
          </div>
        </div>

        <dl className="divide-y">
          <RecordField
            label="External record"
            value={row.source_pk}
            mono
            href={
              row.source === "openalex" && row.source_pk.startsWith("doi:")
                ? `https://doi.org/${row.source_pk.slice(4)}`
                : undefined
            }
          />
          <RecordField label="Local work id" value={row.work_id} mono />
          <RecordField label="Local work title" value={row.work_title} />
          <RecordField label="Institution" value={row.institution_code ?? row.institution_id} />
          <RecordField label="Note" value={row.note} />
          <RecordField label="Updated" value={row.updated_at} />
        </dl>

        <RecordJson label="Row as stored" data={row} />

        <section className="space-y-3 rounded-[var(--radius)] border p-4">
          <h3 className="text-sm font-semibold">Decision</h3>
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor="wi-reviewer-name" className="text-sm text-muted-foreground">
              Reviewer
            </label>
            <Input
              id="wi-reviewer-name"
              placeholder="your name (stored locally, lands in the audit log)"
              value={reviewer}
              onChange={(event) => setReviewer(event.target.value)}
              className="w-72"
            />
          </div>
          <Input
            placeholder="Optional note recorded with the flip"
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              disabled={busy === key || row.status === "confirmed"}
              onClick={() => flip("confirmed")}
            >
              Confirm link
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={busy === key || row.status === "missing"}
              onClick={() => flip("missing")}
            >
              Mark as missing
            </Button>
            {row.status !== "candidate" && (
              <Button variant="ghost" size="sm" onClick={() => flip("candidate")}>
                Reopen as candidate
              </Button>
            )}
            <span className="text-xs text-muted-foreground">
              &lsquo;Missing&rsquo; records a lookup gap, not a bad link. Flips are durable and
              audited.
            </span>
          </div>
        </section>
      </div>
    </AdminDrawer>
  );
}
