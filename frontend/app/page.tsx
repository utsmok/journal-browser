"use client";

import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type JournalRow = {
  title: string;
  publisher: string;
  deal: string | null;
  oa: boolean;
  works: number;
};

// Placeholder rows: replaced by /api/v1/journals via TanStack Query in phase 4.
const ROWS: JournalRow[] = [
  { title: "Water Research", publisher: "Elsevier", deal: "100% discount", oa: false, works: 212 },
  { title: "PLOS ONE", publisher: "PLOS", deal: null, oa: true, works: 96 },
  { title: "Scientific Reports", publisher: "Nature Portfolio", deal: null, oa: true, works: 84 },
  { title: "Technological Forecasting and Social Change", publisher: "Elsevier", deal: "100% discount", oa: false, works: 41 },
  { title: "Journal of Cleaner Production", publisher: "Elsevier", deal: "100% discount", oa: false, works: 38 },
];

const columns: ColumnDef<JournalRow>[] = [
  {
    accessorKey: "title",
    header: "Journal",
    cell: (info) => <span className="font-medium">{info.getValue<string>()}</span>,
  },
  { accessorKey: "publisher", header: "Publisher" },
  {
    accessorKey: "deal",
    header: "Open access deal",
    cell: (info) => {
      const deal = info.getValue<string | null>();
      return deal ? <Badge>{deal}</Badge> : <Badge variant="outline">No deal</Badge>;
    },
  },
  {
    accessorKey: "oa",
    header: "OA journal",
    cell: (info) =>
      info.getValue<boolean>() ? <Badge variant="secondary">OA</Badge> : <Badge variant="muted">Hybrid</Badge>,
  },
  { accessorKey: "works", header: "UT papers (2020-)" },
];

export default function Home() {
  const [query, setQuery] = React.useState("");
  const data = React.useMemo(
    () =>
      ROWS.filter((row) =>
        row.title.toLowerCase().includes(query.trim().toLowerCase()),
      ),
    [query],
  );
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <section className="mb-10">
        <h1 className="mb-3 text-3xl font-bold">
          Find the best home for your next article
        </h1>
        <p className="mb-6 max-w-2xl text-[var(--muted-foreground)]">
          Search journals to see whether they are covered by an open access deal, what
          publishing there costs, and how the University of Twente publishes in them.
        </p>
        <form
          className="flex max-w-xl gap-2"
          onSubmit={(event) => event.preventDefault()}
        >
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search by journal title or ISSN"
            aria-label="Search journals"
          />
          <Button type="submit">Search</Button>
        </form>
      </section>

      <Card>
        <CardHeader>
          <CardTitle>Journals</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              {table.getHeaderGroups().map((group) => (
                <TableRow key={group.id}>
                  {group.headers.map((header) => (
                    <TableHead key={header.id}>
                      {flexRender(
                        header.column.columnDef.header,
                        header.getContext(),
                      )}
                    </TableHead>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="mt-3 text-xs text-[var(--muted-foreground)]">
            Placeholder rows for layout review; live data arrives with the search API.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
