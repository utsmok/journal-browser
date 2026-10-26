"use client";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { AdminRun, InstitutionDirectoryEntry } from "@/lib/admin";

export function StatusBadge({ status }: { status: string }) {
  const variant =
    status === "completed" ? "secondary" : status === "failed" ? "outline" : "muted";
  return <Badge variant={variant}>{status}</Badge>;
}

/** Harvest runs table shared by the global and per-institution admin pages. */
export function RunsTable({
  runs,
  directory = [],
}: {
  runs: AdminRun[];
  directory?: InstitutionDirectoryEntry[];
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>#</TableHead>
          <TableHead>Institution</TableHead>
          <TableHead>Source</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Started</TableHead>
          <TableHead>Stats</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run) => (
          <TableRow key={run.id}>
            <TableCell>{run.id}</TableCell>
            <TableCell>
              {run.institution_code == null
                ? "shared"
                : directory.find((i) => i.code === run.institution_code)?.short_name ??
                  run.institution_code}
            </TableCell>
            <TableCell>
              {run.source}/{run.entity_type}
            </TableCell>
            <TableCell>
              <StatusBadge status={run.status} />
            </TableCell>
            <TableCell className="whitespace-nowrap text-muted-foreground">
              {run.started_at?.slice(0, 19).replace("T", " ")}
            </TableCell>
            <TableCell
              className="max-w-md truncate font-mono text-xs"
              title={JSON.stringify(run.stats)}
            >
              {JSON.stringify(run.stats)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
