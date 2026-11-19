"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { AdminDrawer } from "@/components/admin/drawer";
import { CopyButton, RecordField, RecordJson, useReviewer } from "@/components/admin/record";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatDate } from "@/lib/format";
import {
  AdminError,
  adminGet,
  type AuthorIdentityAdmin,
  type StoredExternalAuthor,
} from "@/lib/admin";

type LocalProfile = {
  author: {
    pure_uuid: string;
    name: string;
    orcid: string | null;
    openalex_author_id: string | null;
    openaire_person_id: string | null;
    crossref_orcid: string | null;
    faculty: string | null;
    research_group: string | null;
    institute: string | null;
    orgs: string[];
    n_works: number;
  };
  works: { title: string; year: number; doi: string | null }[];
};

type OpenAlexPayload = {
  display_name?: string;
  orcid?: string | null;
  works_count?: number;
  cited_by_count?: number;
  display_name_alternatives?: string[];
  last_known_institution?: { display_name?: string } | null;
  last_known_institutions?: { display_name?: string }[] | null;
  topics?: { display_name?: string }[];
};

function MatchBadge({ ok, yes, no }: { ok: boolean; yes: string; no: string }) {
  return <Badge variant={ok ? "secondary" : "outline"}>{ok ? `✓ ${yes}` : no}</Badge>;
}

/**
 * Side-by-side decision view for one author identity candidate: the local
 * Pure profile (public author API) against the OpenAlex record from the
 * harvest's stored source_records payloads, plus the cascade evidence, with
 * confirm/reject actions. No live API calls.
 */
export function AuthorIdentityDrawer({
  row,
  token,
  onClose,
  onFlip,
  busy,
}: {
  row: AuthorIdentityAdmin;
  token: string;
  onClose: () => void;
  onFlip: (row: AuthorIdentityAdmin, status: string, note: string, changedBy: string) => void;
  busy: string | null;
}) {
  const t = useTranslations("admin");
  const [note, setNote] = useState("");
  const [reviewer, setReviewer] = useReviewer();
  const [local, setLocal] = useState<LocalProfile | null>(null);
  const [localMissing, setLocalMissing] = useState(false);
  const [external, setExternal] = useState<StoredExternalAuthor | null>(null);
  const [externalMissing, setExternalMissing] = useState(false);

  const isOpenalex = row.source === "openalex";

  useEffect(() => {
    let cancelled = false;
    setLocal(null);
    setLocalMissing(false);
    if (!row.institution_code) return;
    void fetch(`/api/v1/${row.institution_code}/authors/${row.author_pure_uuid}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(String(res.status)))))
      .then((data) => {
        if (!cancelled) setLocal(data as LocalProfile);
      })
      .catch(() => {
        if (!cancelled) setLocalMissing(true);
      });
    return () => {
      cancelled = true;
    };
  }, [row]);

  useEffect(() => {
    let cancelled = false;
    setExternal(null);
    setExternalMissing(false);
    if (!isOpenalex || !token) return;
    const instQ = row.institution_code
      ? `?institution=${encodeURIComponent(row.institution_code)}`
      : "";
    void adminGet<StoredExternalAuthor>(`/external-author/${row.external_id}${instQ}`, token)
      .then((data) => {
        if (!cancelled) setExternal(data);
      })
      .catch((err) => {
        if (!cancelled && !(err instanceof AdminError && err.status === 404)) {
          // Transient failure — surface as "missing" too; the link fallback covers review.
        }
        if (!cancelled) setExternalMissing(true);
      });
    return () => {
      cancelled = true;
    };
  }, [row, isOpenalex, token]);

  const payload = (external?.author ?? {}) as OpenAlexPayload;
  const evidence = (row.evidence ?? {}) as Record<string, unknown>;
  const evidenceOrcids = Array.isArray(evidence.orcids) ? (evidence.orcids as string[]) : [];
  const nameMatch =
    payload.display_name != null &&
    !!row.author_name &&
    payload.display_name.trim().toLowerCase() === row.author_name.trim().toLowerCase();
  const localOrcid = local?.author.orcid ?? null;
  const externalOrcid = payload.orcid ?? null;
  const orcidOverlap =
    (localOrcid != null && externalOrcid != null && localOrcid === externalOrcid) ||
    (externalOrcid != null && evidenceOrcids.includes(externalOrcid));

  const flip = (status: string) => onFlip(row, status, note, reviewer);

  return (
    <AdminDrawer title={t("authorIdentity.title")} onClose={onClose}>
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-base font-semibold">{row.author_name ?? row.author_pure_uuid}</p>
            <p className="text-xs text-muted-foreground">
              {t("authorIdentity.subtitle", {
                source: row.source,
                method: row.method ?? "—",
                confidence: row.confidence ?? "—",
              })}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge
              variant={
                row.status === "confirmed"
                  ? "default"
                  : row.status === "rejected"
                    ? "outline"
                    : "muted"
              }
            >
              {row.status}
            </Badge>
            <CopyButton
              text={JSON.stringify(row, null, 2)}
              label={t("authorIdentity.copyRecord")}
            />
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <section className="rounded-[var(--radius)] border p-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold">{t("authorIdentity.localTitle")}</h3>
              {local && payload.display_name && (
                <MatchBadge
                  ok={nameMatch}
                  yes={t("authorIdentity.nameMatches")}
                  no={t("authorIdentity.nameDiffers")}
                />
              )}
            </div>
            {local ? (
              <div className="space-y-0.5">
                <RecordField label={t("authorIdentity.fieldName")} value={local.author.name} />
                <RecordField
                  label={t("authorIdentity.fieldPureUuid")}
                  value={local.author.pure_uuid}
                  mono
                />
                <RecordField label={t("authorIdentity.fieldOrcid")} value={localOrcid} mono />
                <RecordField
                  label={t("authorIdentity.fieldInstitute")}
                  value={local.author.institute}
                />
                <RecordField
                  label={t("authorIdentity.fieldFaculty")}
                  value={local.author.faculty}
                />
                <RecordField
                  label={t("authorIdentity.fieldResearchGroup")}
                  value={local.author.research_group}
                />
                <RecordField
                  label={t("authorIdentity.fieldOrgs")}
                  value={local.author.orgs.join(", ")}
                />
                <RecordField
                  label={t("authorIdentity.fieldWorksLocal")}
                  value={local.author.n_works}
                />
                {localOrcid && externalOrcid && (
                  <div className="pt-1">
                    <MatchBadge
                      ok={orcidOverlap}
                      yes={t("authorIdentity.orcidAgrees")}
                      no={t("authorIdentity.orcidConflict")}
                    />
                  </div>
                )}
                <div className="pt-2">
                  <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {t("authorIdentity.recentLocalWorks")}
                  </p>
                  <ul className="mt-1 space-y-1 text-sm">
                    {local.works.slice(0, 8).map((work) => (
                      <li
                        key={`${work.title}-${work.year}`}
                        className="truncate"
                        title={work.title}
                      >
                        <span className="text-muted-foreground">{work.year}</span> · {work.title}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                {localMissing ? t("authorIdentity.localMissing") : t("authorIdentity.loadingLocal")}
              </p>
            )}
          </section>

          <section className="rounded-[var(--radius)] border p-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold">
                {t("authorIdentity.externalTitle", {
                  source: isOpenalex ? "OpenAlex" : "OpenAIRE",
                })}
              </h3>
              {external && (
                <p className="text-[10px] text-muted-foreground">
                  {t("authorIdentity.stored", {
                    date: external.harvested_at ? formatDate(external.harvested_at) : "—",
                  })}
                </p>
              )}
            </div>
            {isOpenalex ? (
              external ? (
                <div className="space-y-0.5">
                  <RecordField
                    label={t("authorIdentity.fieldDisplayName")}
                    value={payload.display_name}
                  />
                  <RecordField
                    label={t("authorIdentity.fieldOpenalexId")}
                    value={row.external_id}
                    mono
                    href={`https://openalex.org/${row.external_id}`}
                  />
                  <RecordField label={t("authorIdentity.fieldOrcid")} value={externalOrcid} mono />
                  <RecordField
                    label={t("authorIdentity.fieldWorksOpenalex")}
                    value={payload.works_count}
                  />
                  <RecordField
                    label={t("authorIdentity.fieldCitations")}
                    value={payload.cited_by_count}
                  />
                  <RecordField
                    label={t("authorIdentity.fieldLastInstitution")}
                    value={
                      payload.last_known_institutions?.[0]?.display_name ??
                      payload.last_known_institution?.display_name ??
                      null
                    }
                  />
                  <RecordField
                    label={t("authorIdentity.fieldTopics")}
                    value={(payload.topics ?? [])
                      .slice(0, 3)
                      .map((topic) => topic.display_name)
                      .join(", ")}
                  />
                  {(payload.display_name_alternatives ?? []).length > 0 && (
                    <RecordField
                      label={t("authorIdentity.fieldAltNames")}
                      value={(payload.display_name_alternatives ?? []).slice(0, 4).join(", ")}
                    />
                  )}
                  <div className="pt-2">
                    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      {t("authorIdentity.recentHarvestWorks")}
                    </p>
                    <ul className="mt-1 space-y-1 text-sm">
                      {external.works.map((work) => (
                        <li key={work.w_id} className="truncate" title={work.title ?? ""}>
                          <span className="text-muted-foreground">{work.year}</span> ·{" "}
                          {work.title ?? work.w_id}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              ) : (
                <div className="space-y-2 text-sm">
                  <p className="text-muted-foreground">
                    {externalMissing
                      ? t("authorIdentity.externalMissing")
                      : t("authorIdentity.loadingExternal")}
                  </p>
                  <RecordField
                    label={t("authorIdentity.fieldOpenalexId")}
                    value={row.external_id}
                    mono
                    href={`https://openalex.org/${row.external_id}`}
                  />
                </div>
              )
            ) : (
              <div className="space-y-2 text-sm">
                <p className="text-muted-foreground">{t("authorIdentity.openaireNote")}</p>
                <RecordField
                  label={t("authorIdentity.fieldOpenaireId")}
                  value={row.external_id}
                  mono
                  href={`https://explore.openaire.eu/search/find?keyword=${encodeURIComponent(row.external_id)}`}
                />
              </div>
            )}
          </section>
        </div>

        <RecordJson label={t("authorIdentity.evidence")} data={row.evidence} />

        <section className="space-y-3 rounded-[var(--radius)] border p-4">
          <h3 className="text-sm font-semibold">{t("authorIdentity.decision")}</h3>
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor="reviewer-name" className="text-sm text-muted-foreground">
              {t("authorIdentity.reviewer")}
            </label>
            <Input
              id="reviewer-name"
              placeholder={t("authorIdentity.reviewerPlaceholder")}
              value={reviewer}
              onChange={(event) => setReviewer(event.target.value)}
              className="w-72"
            />
          </div>
          <Input
            placeholder={t("authorIdentity.notePlaceholder")}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              disabled={busy === `${row.source}:${row.external_id}` || row.status === "confirmed"}
              onClick={() => flip("confirmed")}
            >
              {t("authorIdentity.confirmMatch")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={busy === `${row.source}:${row.external_id}` || row.status === "rejected"}
              onClick={() => flip("rejected")}
            >
              {t("authorIdentity.reject")}
            </Button>
            {row.status !== "candidate" && (
              <Button variant="ghost" size="sm" onClick={() => flip("candidate")}>
                {t("authorIdentity.backToCandidate")}
              </Button>
            )}
            <span className="text-xs text-muted-foreground">{t("authorIdentity.flipsNote")}</span>
          </div>
        </section>
      </div>
    </AdminDrawer>
  );
}
