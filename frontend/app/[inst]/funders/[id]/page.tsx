"use client";

import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import { BackLink } from "@/components/back-link";
import { CollapsibleCard } from "@/components/collapsible-card";
import { SourceNote } from "@/components/source-note";
import { ListSkeletonRows } from "@/components/states";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useFunder } from "@/hooks/use-api";
import { useInstitution } from "@/hooks/use-institution";
import { errorMessage, type FunderDetailResponse } from "@/lib/api";
import { useFunderPrefs } from "@/lib/funder-prefs";

const ROR_URL = "https://ror.org/";
const FUNDREF_URL = "https://doi.org/10.13039/";
const OPF_URL = "https://openpolicyfinder.jisc.ac.uk/";
const OPENAIRE_URL = "https://openaire.eu";

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

/** Values inside the OPF policy sub-blocks use short codes
 * ("requires", "national_repository"); humanize before showing. */
function policyValue(v: unknown): string {
  if (typeof v === "string") return v.replaceAll("_", " ");
  if (Array.isArray(v)) return v.map(policyValue).join("; ");
  if (v && typeof v === "object") {
    return Object.values(v as Record<string, unknown>)
      .map(policyValue)
      .join("; ");
  }
  return String(v ?? "");
}

const POLICY_LABELS: Record<string, string> = {
  what: "What",
  when: "When",
  where: "Where",
  license: "License",
  requirement: "Requirement",
  special_conditions: "Special conditions",
  conditions: "Conditions",
};

/** One OPF policy sub-block (archiving_policy / publishing_policy):
 * known keys as label rows, everything else falls back to pretty JSON. */
function PolicyRules({ rules }: { rules: Record<string, unknown> }) {
  const known = Object.entries(POLICY_LABELS).filter(([k]) => k in rules);
  const rest = Object.keys(rules).filter((k) => !(k in POLICY_LABELS));
  return (
    <>
      {known.length > 0 && (
        <dl className="mb-3 grid grid-cols-[10rem_1fr] gap-x-3 gap-y-1.5 text-sm">
          {known.map(([k, label]) => (
            <React.Fragment key={k}>
              <dt className="text-[var(--muted-foreground)]">{label}</dt>
              <dd>{policyValue(rules[k]) || "—"}</dd>
            </React.Fragment>
          ))}
        </dl>
      )}
      {rest.length > 0 && (
        <pre className="max-h-48 overflow-y-auto rounded-[var(--radius)] bg-[var(--muted)] p-3 text-xs whitespace-pre-wrap">
          {JSON.stringify(Object.fromEntries(rest.map((k) => [k, rules[k]])), null, 2)}
        </pre>
      )}
    </>
  );
}

/** A curated OPF link list ([{url, type, description}]). */
function PolicyUrls({ urls }: { urls: unknown }) {
  if (!Array.isArray(urls) || urls.length === 0) return null;
  return (
    <ul className="mb-3 space-y-1 text-sm">
      {urls.map((u: { url?: string; description?: string }, i: React.Key) =>
        u?.url ? (
          <li key={i}>
            <a
              href={u.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 underline decoration-dotted underline-offset-2"
            >
              {u.description || u.url}
              <ExternalLink aria-hidden className="size-3" />
            </a>
          </li>
        ) : null,
      )}
    </ul>
  );
}

/** Full rendered view of a harvested OPF policy payload (urls, notes,
 * scope, structured rules); unknown shapes fall back to pretty JSON. */
function PolicyBlock({ data }: { data: Record<string, unknown> | null | undefined }) {
  if (!data) return <p className="text-sm text-[var(--muted-foreground)]">Not harvested.</p>;
  // Nested shape (publications_policy: archiving_policy/publishing_policy
  // sub-blocks) and flat shape (data_archiving_policy: rule keys directly
  // on the payload) both occur in the OPF payloads.
  const RULE_KEYS = [
    "what",
    "when",
    "where",
    "license",
    "requirement",
    "conditions",
    "special_conditions",
  ];
  const flat = RULE_KEYS.some((k) => k in data) ? data : null;
  const rules = flat
    ? []
    : ([
        ["Archiving rules", data.archiving_policy],
        ["Publishing rules", data.publishing_policy],
      ].filter(([, v]) => v && typeof v === "object") as [string, Record<string, unknown>][]);
  const notes = Array.isArray(data.notes) ? (data.notes as string[]) : [];
  const scope = Array.isArray(data.scope) ? (data.scope as string[]) : [];
  if (!flat && rules.length === 0 && notes.length === 0 && !Array.isArray(data.urls)) {
    return (
      <pre className="max-h-96 overflow-y-auto rounded-[var(--radius)] bg-[var(--muted)] p-3 text-xs whitespace-pre-wrap">
        {JSON.stringify(data, null, 2)}
      </pre>
    );
  }
  return (
    <div className="text-sm">
      <PolicyUrls urls={data.urls} />
      {notes.map((n, i) => (
        <p key={i} className="mb-2 last:mb-0">
          {n}
        </p>
      ))}
      {scope.length > 0 && (
        <p className="mt-3 text-xs text-[var(--muted-foreground)]">
          Scope: {scope.map(policyValue).join(", ")}
        </p>
      )}
      {flat && (
        <div className="mt-4 border-t border-[var(--border)] pt-3">
          <PolicyRules rules={flat} />
        </div>
      )}
      {rules.map(([label, block]) => (
        <div key={label} className="mt-4 border-t border-[var(--border)] pt-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
            {label}
          </p>
          <PolicyRules rules={block} />
        </div>
      ))}
    </div>
  );
}

/** OpenAIRE Graph identity for the same funder (canon-linked via ROR). */
function OpenaireCard({ oa }: { oa: NonNullable<FunderDetailResponse["openaire"]> }) {
  return (
    <CollapsibleCard id="funder-openaire" title="OpenAIRE record">
      <div className="text-sm">
        <dl className="grid grid-cols-[10rem_1fr] gap-x-3 gap-y-1.5">
          <dt className="text-[var(--muted-foreground)]">Name</dt>
          <dd>{oa.name ?? "—"}</dd>
          {oa.short_name && (
            <>
              <dt className="text-[var(--muted-foreground)]">Short name</dt>
              <dd>{oa.short_name}</dd>
            </>
          )}
          {oa.jurisdiction && (
            <>
              <dt className="text-[var(--muted-foreground)]">Jurisdiction</dt>
              <dd>{oa.jurisdiction}</dd>
            </>
          )}
          <dt className="text-[var(--muted-foreground)]">OpenAIRE id</dt>
          <dd className="break-all">{oa.openaire_id}</dd>
        </dl>
        <div className="mt-2">
          <SourceNote source="OpenAIRE Graph" url={OPENAIRE_URL} codes={["openaire-enrichment"]} />
        </div>
      </div>
    </CollapsibleCard>
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
            {" · "}
            {data.n_ut_works.toLocaleString()} UT works
            {" · "}
            {data.policy_structured
              ? "structured OA policy"
              : "text-only policy (no machine-readable rules)"}
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
              <div className="mt-1">
                <SourceNote
                  source="UT works via PURE, grants from OpenAlex/OpenAIRE"
                  url={OPENAIRE_URL}
                  codes={["openalex-coverage", "openaire-enrichment"]}
                />
              </div>
            </section>
          )}

          <div className="space-y-4">
            <CollapsibleCard id="funder-publications-policy" title="Publications policy">
              <PolicyBlock data={data.publications_policy} />
              <div className="mt-2">
                <SourceNote
                  source="Jisc Open Policy Finder"
                  url={OPF_URL}
                  codes={["jisc-policy-currency"]}
                />
              </div>
            </CollapsibleCard>
            <CollapsibleCard id="funder-data-policy" title="Data archiving policy">
              <PolicyBlock data={data.data_archiving_policy} />
              <div className="mt-2">
                <SourceNote
                  source="Jisc Open Policy Finder"
                  url={OPF_URL}
                  codes={["jisc-policy-currency"]}
                />
              </div>
            </CollapsibleCard>
            {data.openaire && <OpenaireCard oa={data.openaire} />}
          </div>
        </>
      )}
    </div>
  );
}
