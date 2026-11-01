"use client";

import { useEffect, useState } from "react";

import { AdminDrawer } from "@/components/admin/drawer";
import { CopyButton, RecordField, RecordJson, useReviewer } from "@/components/admin/record";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
    <AdminDrawer title="Author identity review" onClose={onClose}>
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-base font-semibold">{row.author_name ?? row.author_pure_uuid}</p>
            <p className="text-xs text-muted-foreground">
              {row.source} · {row.method ?? "—"} · confidence {row.confidence ?? "—"}
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
            <CopyButton text={JSON.stringify(row, null, 2)} label="Copy record" />
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <section className="rounded-[var(--radius)] border p-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold">Local — Pure</h3>
              {local && payload.display_name && (
                <MatchBadge ok={nameMatch} yes="name matches" no="name differs" />
              )}
            </div>
            {local ? (
              <div className="space-y-0.5">
                <RecordField label="Name" value={local.author.name} />
                <RecordField label="Pure uuid" value={local.author.pure_uuid} mono />
                <RecordField label="ORCID" value={localOrcid} mono />
                <RecordField label="Institute" value={local.author.institute} />
                <RecordField label="Faculty" value={local.author.faculty} />
                <RecordField label="Research group" value={local.author.research_group} />
                <RecordField label="Orgs" value={local.author.orgs.join(", ")} />
                <RecordField label="Works (local)" value={local.author.n_works} />
                {localOrcid && externalOrcid && (
                  <div className="pt-1">
                    <MatchBadge ok={orcidOverlap} yes="ORCID agrees" no="ORCID conflict" />
                  </div>
                )}
                <div className="pt-2">
                  <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Recent local works
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
                {localMissing
                  ? "Local author not in the current roster (authors re-ingest may have dropped them)."
                  : "Loading local profile…"}
              </p>
            )}
          </section>

          <section className="rounded-[var(--radius)] border p-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold">
                External — {isOpenalex ? "OpenAlex" : "OpenAIRE"}
              </h3>
              {external && (
                <p className="text-[10px] text-muted-foreground">
                  stored{" "}
                  {external.harvested_at
                    ? new Date(external.harvested_at).toLocaleDateString()
                    : "—"}
                </p>
              )}
            </div>
            {isOpenalex ? (
              external ? (
                <div className="space-y-0.5">
                  <RecordField label="Display name" value={payload.display_name} />
                  <RecordField
                    label="OpenAlex id"
                    value={row.external_id}
                    mono
                    href={`https://openalex.org/${row.external_id}`}
                  />
                  <RecordField label="ORCID" value={externalOrcid} mono />
                  <RecordField label="Works (OpenAlex)" value={payload.works_count} />
                  <RecordField label="Citations" value={payload.cited_by_count} />
                  <RecordField
                    label="Last known institution"
                    value={
                      payload.last_known_institutions?.[0]?.display_name ??
                      payload.last_known_institution?.display_name ??
                      null
                    }
                  />
                  <RecordField
                    label="Topics"
                    value={(payload.topics ?? [])
                      .slice(0, 3)
                      .map((topic) => topic.display_name)
                      .join(", ")}
                  />
                  {(payload.display_name_alternatives ?? []).length > 0 && (
                    <RecordField
                      label="Alternative names"
                      value={(payload.display_name_alternatives ?? []).slice(0, 4).join(", ")}
                    />
                  )}
                  <div className="pt-2">
                    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Recent works (from the works harvest)
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
                      ? "No stored profile for this id — it fell outside the author sweep. Open it on OpenAlex instead:"
                      : "Loading stored OpenAlex profile…"}
                  </p>
                  <RecordField
                    label="OpenAlex id"
                    value={row.external_id}
                    mono
                    href={`https://openalex.org/${row.external_id}`}
                  />
                </div>
              )
            ) : (
              <div className="space-y-2 text-sm">
                <p className="text-muted-foreground">
                  OpenAIRE records are not fetched in-app. Review via the evidence and the record id
                  below.
                </p>
                <RecordField
                  label="OpenAIRE id"
                  value={row.external_id}
                  mono
                  href={`https://explore.openaire.eu/search/find?keyword=${encodeURIComponent(row.external_id)}`}
                />
              </div>
            )}
          </section>
        </div>

        <RecordJson label="Cascade evidence" data={row.evidence} />

        <section className="space-y-3 rounded-[var(--radius)] border p-4">
          <h3 className="text-sm font-semibold">Decision</h3>
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor="reviewer-name" className="text-sm text-muted-foreground">
              Reviewer
            </label>
            <Input
              id="reviewer-name"
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
              disabled={busy === `${row.source}:${row.external_id}` || row.status === "confirmed"}
              onClick={() => flip("confirmed")}
            >
              Confirm match
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={busy === `${row.source}:${row.external_id}` || row.status === "rejected"}
              onClick={() => flip("rejected")}
            >
              Reject
            </Button>
            {row.status !== "candidate" && (
              <Button variant="ghost" size="sm" onClick={() => flip("candidate")}>
                Back to candidate
              </Button>
            )}
            <span className="text-xs text-muted-foreground">
              Flips are sticky across harvest re-runs and audited.
            </span>
          </div>
        </section>
      </div>
    </AdminDrawer>
  );
}
