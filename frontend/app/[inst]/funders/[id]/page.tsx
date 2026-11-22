"use client";

import { Check, ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";
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
import { useSiteMeta } from "@/hooks/use-site-meta";
import { useYearRange } from "@/hooks/use-year-filter";
import { errorMessage, type FunderDetailResponse } from "@/lib/api";
import { useFunderPrefs } from "@/lib/funder-prefs";

const ROR_URL = "https://ror.org/";
const FUNDREF_URL = "https://doi.org/10.13039/";
const OPF_URL = "https://openpolicyfinder.jisc.ac.uk/";
const OPENAIRE_URL = "https://openaire.eu";

function CanonLinks({ funder }: { funder: FunderDetailResponse }) {
  const t = useTranslations("funders");
  const links: { label: string; href: string }[] = [];
  if (funder.ror) links.push({ label: t("detail.ror"), href: ROR_URL + funder.ror });
  if (funder.fundref)
    links.push({ label: t("detail.fundref"), href: FUNDREF_URL + funder.fundref });
  if (funder.openalex_funder_id)
    links.push({ label: t("detail.openalex"), href: funder.openalex_funder_id });
  if (funder.url) links.push({ label: t("detail.website"), href: funder.url });
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
 * ("requires", "national_repository"); humanize before showing.
 * Boolean values render as the given Yes/No labels. */
function policyValue(v: unknown, yesLabel: string, noLabel: string): string {
  if (typeof v === "boolean") return v ? yesLabel : noLabel;
  if (typeof v === "string") return v.replaceAll("_", " ");
  if (Array.isArray(v)) return v.map((x) => policyValue(x, yesLabel, noLabel)).join("; ");
  if (v && typeof v === "object") {
    return Object.values(v as Record<string, unknown>)
      .map((x) => policyValue(x, yesLabel, noLabel))
      .join("; ");
  }
  return String(v ?? "");
}

/** Known OPF rule keys → message keys; unknown keys render humanized. */
const POLICY_LABEL_KEYS: Record<string, string> = {
  what: "detail.policy.what",
  when: "detail.policy.when",
  where: "detail.policy.where",
  license: "detail.policy.license",
  requirement: "detail.policy.requirement",
  special_conditions: "detail.policy.specialConditions",
  conditions: "detail.policy.conditions",
};

// Payload wrapper keys rendered elsewhere; never show them as JSON fallback.
const NON_RULE_KEYS: Record<string, true> = { urls: true, notes: true, scope: true };

/** One OPF policy sub-block (archiving_policy / publishing_policy):
 * every key renders as a label row — known keys get curated labels,
 * unknown keys get a humanized label, never a raw JSON dump. */
function PolicyRules({ rules }: { rules: Record<string, unknown> }) {
  const t = useTranslations("funders");
  const rows: [string, unknown][] = [];
  const seen = new Set<string>();
  for (const [k, key] of Object.entries(POLICY_LABEL_KEYS)) {
    if (k in rules) {
      rows.push([t(key), rules[k]]);
      seen.add(k);
    }
  }
  for (const k of Object.keys(rules)) {
    if (!seen.has(k) && !(k in NON_RULE_KEYS)) {
      rows.push([k.charAt(0).toUpperCase() + k.slice(1).replaceAll("_", " "), rules[k]]);
    }
  }
  if (rows.length === 0) return null;
  return (
    <dl className="grid grid-cols-[10rem_1fr] gap-x-3 gap-y-1.5 text-sm">
      {rows.map(([label, value]) => (
        <React.Fragment key={label}>
          <dt className="text-[var(--muted-foreground)]">{label}</dt>
          <dd>{policyValue(value, t("detail.policy.yes"), t("detail.policy.no")) || "—"}</dd>
        </React.Fragment>
      ))}
    </dl>
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
 * scope, structured rules); unknown shapes render as humanized rows
 * rather than a raw JSON dump. */
function PolicyBlock({ data }: { data: Record<string, unknown> | null | undefined }) {
  const t = useTranslations("funders");
  if (!data)
    return (
      <p className="text-sm text-[var(--muted-foreground)]">{t("detail.policy.notHarvested")}</p>
    );
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
        [t("detail.policy.archivingRules"), data.archiving_policy],
        [t("detail.policy.publishingRules"), data.publishing_policy],
      ].filter(([, v]) => v && typeof v === "object") as [string, Record<string, unknown>][]);
  const notes = Array.isArray(data.notes) ? (data.notes as string[]) : [];
  const scope = Array.isArray(data.scope) ? (data.scope as string[]) : [];
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
          {t("detail.policy.scope", {
            scope: scope
              .map((v) => policyValue(v, t("detail.policy.yes"), t("detail.policy.no")))
              .join(", "),
          })}
        </p>
      )}
      {flat && (
        <div className="mt-4 border-t border-[var(--border)] pt-3">
          <PolicyRules rules={flat} />
        </div>
      )}
      {rules.map(([label, block]) => (
        <div key={label} className="mt-4 border-t border-[var(--border)] pt-3">
          <p className="mb-2 text-sm font-medium">{label}</p>
          <PolicyRules rules={block} />
        </div>
      ))}
      {!flat && rules.length === 0 && (
        <div className="mt-3">
          <PolicyRules rules={data} />
        </div>
      )}
    </div>
  );
}

/** OpenAIRE Graph identity for the same funder (canon-linked via ROR). */
function OpenaireCard({ oa }: { oa: NonNullable<FunderDetailResponse["openaire"]> }) {
  const t = useTranslations("funders");
  return (
    <CollapsibleCard id="funder-openaire" title={t("detail.openaire.title")}>
      <div className="text-sm">
        <dl className="grid grid-cols-[10rem_1fr] gap-x-3 gap-y-1.5">
          <dt className="text-[var(--muted-foreground)]">{t("detail.openaire.name")}</dt>
          <dd>{oa.name ?? "—"}</dd>
          {oa.short_name && (
            <>
              <dt className="text-[var(--muted-foreground)]">{t("detail.openaire.shortName")}</dt>
              <dd>{oa.short_name}</dd>
            </>
          )}
          {oa.jurisdiction && (
            <>
              <dt className="text-[var(--muted-foreground)]">
                {t("detail.openaire.jurisdiction")}
              </dt>
              <dd>{oa.jurisdiction}</dd>
            </>
          )}
          <dt className="text-[var(--muted-foreground)]">{t("detail.openaire.id")}</dt>
          <dd className="break-all">{oa.openaire_id}</dd>
        </dl>
        {oa.streams.length > 0 && (
          <div className="mt-3 border-t border-[var(--border)] pt-3">
            <p className="mb-1.5 text-sm font-medium">{t("detail.openaire.streams")}</p>
            <ul className="space-y-1">
              {oa.streams.map((s) => (
                <li key={s.level0_id} className="flex justify-between gap-3">
                  <span className="min-w-0 truncate">{s.name ?? s.level0_id}</span>
                  <span className="shrink-0 tabular-nums text-[var(--muted-foreground)]">
                    {s.n_projects.toLocaleString()}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="mt-2">
          <SourceNote
            source={t("detail.openaire.source")}
            url={OPENAIRE_URL}
            codes={["openaire-enrichment"]}
          />
        </div>
      </div>
    </CollapsibleCard>
  );
}

export default function FunderPage() {
  const t = useTranslations("funders");
  const tc = useTranslations("common");
  const params = useParams<{ id: string }>();
  const inst = useInstitution();
  const site = useSiteMeta();
  const [funder, setFunder] = useFunderPrefs();
  const id = params?.id ? Number(params.id) : undefined;
  const { year_from, year_to } = useYearRange();
  const { data, isPending, isError, error, refetch } = useFunder(id, { year_from, year_to });

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-10">
      <BackLink href={`/${inst}/funders`} label={t("detail.backToList")} />
      {isPending && <ListSkeletonRows rows={6} />}
      {isError && (
        <div>
          <p className="text-[var(--destructive)]">{errorMessage(tc, error)}</p>
          <Button variant="outline" size="sm" className="mt-2" onClick={() => refetch()}>
            {t("detail.retry")}
          </Button>
        </div>
      )}
      {data && (
        <>
          <h1 className="mb-1 text-3xl font-bold text-balance">{data.name}</h1>
          <p className="mb-2 text-sm text-[var(--muted-foreground)]">
            {(data.country ?? "").toUpperCase() || "—"}
            {" · "}
            {t("detail.worksByInst", { count: data.n_ut_works, inst: site.short })}
            {" · "}
            {data.policy_structured ? t("detail.policyStructured") : t("detail.policyTextOnly")}
          </p>
          <div className="mb-6 flex flex-wrap items-center gap-4">
            <CanonLinks funder={data} />
            {(() => {
              const mine = funder?.id === data.id;
              return (
                <Button
                  variant={mine ? "default" : "outline"}
                  size="sm"
                  aria-pressed={mine}
                  onClick={() =>
                    setFunder(
                      mine
                        ? null
                        : { id: data.id, name: data.name ?? t("unnamedFunder", { id: data.id }) },
                    )
                  }
                  title={mine ? t("detail.myFunderHintOn") : t("detail.myFunderHintOff")}
                >
                  {mine ? (
                    <>
                      <Check aria-hidden className="size-4" />
                      {t("detail.yourFunder")}
                    </>
                  ) : (
                    t("detail.useAsMyFunder")
                  )}
                </Button>
              );
            })()}
          </div>

          {data.top_journals.length > 0 && (
            <section className="mb-8">
              <h2 className="mb-2 text-xl font-bold">{t("instWorks", { inst: site.short })}</h2>
              <Card>
                <CardContent className="p-0">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-[var(--border)] text-left text-[var(--muted-foreground)]">
                        <th className="px-3 py-2 font-medium">{t("detail.journal")}</th>
                        <th className="px-3 py-2 font-medium">{t("detail.issnL")}</th>
                        <th className="px-3 py-2 text-right font-medium">{t("detail.works")}</th>
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
                  source={t("detail.worksSource", { inst: site.short })}
                  url={OPENAIRE_URL}
                  codes={["openalex-coverage", "openaire-enrichment"]}
                />
              </div>
            </section>
          )}

          <div className="space-y-4">
            <CollapsibleCard id="funder-publications-policy" title={t("detail.publicationsPolicy")}>
              <PolicyBlock data={data.publications_policy} />
              <div className="mt-2">
                <SourceNote
                  source={t("sourceJisc")}
                  url={OPF_URL}
                  codes={["jisc-policy-currency"]}
                />
              </div>
            </CollapsibleCard>
            <CollapsibleCard id="funder-data-policy" title={t("detail.dataPolicy")}>
              <PolicyBlock data={data.data_archiving_policy} />
              <div className="mt-2">
                <SourceNote
                  source={t("sourceJisc")}
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
