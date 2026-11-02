"use client";

import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import { BackLink } from "@/components/back-link";
import { CollapsibleCard } from "@/components/collapsible-card";
import { ListSkeletonRows } from "@/components/states";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useFunder } from "@/hooks/use-api";
import { useInstitution } from "@/hooks/use-institution";
import { errorMessage, type FunderDetailResponse } from "@/lib/api";
import { useFunderPrefs } from "@/lib/funder-prefs";

const ROR_URL = "https://ror.org/";
const FUNDREF_URL = "https://doi.org/10.13039/";

function CanonLinks({ funder }: { funder: FunderDetailResponse }) {
  const links: { label: string; href: string }[] = [];
  if (funder.ror) links.push({ label: "ROR", href: ROR_URL + funder.ror });
  if (funder.fundref) links.push({ label: "FundRef", href: FUNDREF_URL + funder.fundref });
  if (funder.openalex_funder_id) links.push({ label: "OpenAlex", href: funder.openalex_funder_id });
  if (funder.url) links.push({ label: "Website", href: funder.url });
  return (
    <p className="flex flex-wrap gap-3 text-sm">
      {links.map((l) => (
        <a
          key={l.label}
          href={l.href}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-0.5 underline decoration-dotted underline-offset-2"
        >
          {l.label}
          <ExternalLink aria-hidden className="size-3.5" />
        </a>
      ))}
    </p>
  );
}

/** Verbatim harvested policy block; the JSON shape is the OPF payload, so
 * render known sub-blocks when present and fall back to pretty JSON. */
function PolicyBlock({ data }: { data: Record<string, unknown> | null | undefined }) {
  if (!data) return <p className="text-sm text-[var(--muted-foreground)]">Not harvested.</p>;
  return (
    <pre className="max-h-96 overflow-y-auto rounded-[var(--radius)] bg-[var(--muted)] p-3 text-xs whitespace-pre-wrap">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

export default function FunderPage() {
  const params = useParams<{ id: string }>();
  const inst = useInstitution();
  const [, setFunder] = useFunderPrefs();
  const id = params?.id ? Number(params.id) : undefined;
  const { data, isPending, isError, error, refetch } = useFunder(id);

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <BackLink href={`/?q=${encodeURIComponent(data?.name ?? "")}`} label="Search" />
      {isPending && <ListSkeletonRows rows={6} />}
      {isError && (
        <div>
          <p className="text-[var(--destructive)]">{errorMessage(error)}</p>
          <Button variant="outline" size="sm" className="mt-2" onClick={() => refetch()}>
            Retry
          </Button>
        </div>
      )}
      {data && (
        <>
          <h1 className="mb-1 text-3xl font-bold text-balance">{data.name}</h1>
          <p className="mb-2 text-sm text-[var(--muted-foreground)]">
            {(data.country ?? "").toUpperCase() || "—"}
            {data.policy_structured
              ? " · structured OA policy"
              : " · text-only policy (no machine-readable rules)"}
          </p>
          <div className="mb-6 flex flex-wrap items-center gap-4">
            <CanonLinks funder={data} />
            <Button
              variant="outline"
              size="sm"
              onClick={() => setFunder({ id: data.id, name: data.name ?? `Funder ${data.id}` })}
              title="Show funder-fit badges on the journal search"
            >
              Use as my funder
            </Button>
          </div>

          {data.top_journals.length > 0 && (
            <section className="mb-8">
              <h2 className="mb-2 text-xl font-bold">Top journals (institution works)</h2>
              <Card>
                <CardContent className="p-0">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-[var(--border)] text-left text-[var(--muted-foreground)]">
                        <th className="px-3 py-2 font-medium">Journal</th>
                        <th className="px-3 py-2 font-medium">ISSN-L</th>
                        <th className="px-3 py-2 text-right font-medium">Works</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.top_journals.map((j) => (
                        <tr
                          key={j.issn_l}
                          className="border-b border-[var(--border)] last:border-0"
                        >
                          <td className="px-3 py-2">
                            <Link
                              href={`/${inst}/journals/${j.issn_l}`}
                              className="underline decoration-dotted underline-offset-2"
                            >
                              {j.title ?? j.issn_l}
                            </Link>
                          </td>
                          <td className="px-3 py-2 tabular-nums">{j.issn_l}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{j.n_works}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardContent>
              </Card>
            </section>
          )}

          <div className="space-y-4">
            <CollapsibleCard id="funder-publications-policy" title="Publications policy">
              <PolicyBlock data={data.publications_policy} />
            </CollapsibleCard>
            <CollapsibleCard id="funder-data-policy" title="Data archiving policy">
              <PolicyBlock data={data.data_archiving_policy} />
            </CollapsibleCard>
          </div>
        </>
      )}
    </div>
  );
}
