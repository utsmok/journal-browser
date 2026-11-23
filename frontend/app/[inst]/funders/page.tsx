"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";

import { SourceNote } from "@/components/source-note";
import { ListSkeletonRows } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useFunderDirectory } from "@/hooks/use-api";
import { useDebounced } from "@/hooks/use-debounced";
import { useInstitution } from "@/hooks/use-institution";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { errorMessage, type FunderListItem } from "@/lib/api";

const OPF_URL = "https://openpolicyfinder.jisc.ac.uk/";
const PAGE_SIZE = 50;

function FunderRow({ funder, inst }: { funder: FunderListItem; inst: string }) {
  const t = useTranslations("funders");
  return (
    <TableRow>
      <TableCell>
        <Link
          href={`/${inst}/funders/${funder.id}`}
          className="underline decoration-dotted underline-offset-2 hover:decoration-solid"
        >
          {funder.name ?? t("unnamedFunder", { id: funder.id })}
        </Link>
      </TableCell>
      <TableCell className="text-[var(--muted-foreground)]">
        {(funder.country ?? "").toUpperCase() || "—"}
      </TableCell>
      <TableCell className="tabular-nums">{funder.n_ut_works.toLocaleString()}</TableCell>
    </TableRow>
  );
}

function FundersPageInner() {
  const t = useTranslations("funders");
  const tc = useTranslations("common");
  const inst = useInstitution();
  const site = useSiteMeta();
  const sp = useSearchParams();
  // ?q= pre-fills the box so cross-links from the journal search ("search
  // funders for …") land on a running query instead of an empty input.
  const [input, setInput] = React.useState(() => sp.get("q") ?? "");
  const q = useDebounced(input.trim(), 250);
  const [offset, setOffset] = React.useState(0);
  // A new search restarts at the first page.
  React.useEffect(() => {
    setOffset(0);
  }, [q]);

  const { data, isPending, isError, error, refetch } = useFunderDirectory(q, offset, PAGE_SIZE);
  const total = data?.total ?? 0;
  const shown = data?.items.length ?? 0;

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <h1 className="text-3xl font-bold text-balance">{t("title")}</h1>
      <p className="mt-1 mb-4 text-sm text-[var(--muted-foreground)]">
        {t("search.intro", { inst: site.short })}
      </p>
      <div className="mb-4 flex items-center gap-2">
        <Input
          type="search"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={t("search.placeholder")}
          aria-label={t("search.searchAria")}
          className="max-w-xs"
        />
      </div>
      {isPending && <ListSkeletonRows rows={8} />}
      {isError && (
        <div>
          <p className="text-[var(--destructive)]">{errorMessage(tc, error)}</p>
          <Button variant="outline" size="sm" className="mt-2" onClick={() => refetch()}>
            {t("search.retry")}
          </Button>
        </div>
      )}
      {data && (
        <Card>
          <CardContent className="pt-6">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("search.funder")}</TableHead>
                  <TableHead>{t("search.country")}</TableHead>
                  <TableHead>{t("instWorks", { inst: site.short })}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={3} className="text-[var(--muted-foreground)]">
                      {t("search.empty", { q })}
                    </TableCell>
                  </TableRow>
                ) : (
                  data.items.map((f) => <FunderRow key={f.id} funder={f} inst={inst} />)
                )}
              </TableBody>
            </Table>
            {total > PAGE_SIZE && (
              <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm text-[var(--muted-foreground)]">
                  {t("search.range", { from: offset + 1, to: offset + shown, total })}
                </p>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={offset === 0}
                    onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                  >
                    <ChevronLeft aria-hidden className="size-4" /> {t("search.prev")}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={offset + shown >= total}
                    onClick={() => setOffset(offset + PAGE_SIZE)}
                  >
                    {t("search.next")} <ChevronRight aria-hidden className="size-4" />
                  </Button>
                </div>
              </div>
            )}
            <div className="mt-3">
              <SourceNote
                source={t("sourceJisc")}
                url={OPF_URL}
                codes={["jisc-policy-currency"]}
                howBuilt={tc("sourceNote.explain.greenOa")}
              />
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/** useSearchParams needs a Suspense boundary during prerender. */
export default function FundersPage() {
  return (
    <React.Suspense fallback={null}>
      <FundersPageInner />
    </React.Suspense>
  );
}
