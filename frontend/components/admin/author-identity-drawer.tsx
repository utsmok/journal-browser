"use client";

import { useEffect, useState } from "react";

import { AdminDrawer } from "@/components/admin/drawer";
import { CopyButton, RecordField, RecordJson, useReviewer } from "@/components/admin/record";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { AuthorIdentityAdmin } from "@/lib/admin";

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

type OpenAlexAuthor = {
  id: string;
  orcid: string | null;
  display_name: string;
  display_name_alternatives?: string[];
  works_count: number;
  cited_by_count: number;
  last_known_institution?: { display_name: string } | null;
  last_known_institutions?: { display_name: string }[] | null;
  topics?: { display_name: string }[];
};

type OpenAlexWork = { display_name: string; publication_year: number | null; doi: string | null };

function MatchBadge({ ok, yes, no }: { ok: boolean; yes: string; no: string }) {
  return <Badge variant={ok ? "secondary" : "outline"}>{ok ? `✓ ${yes}` : no}</Badge>;
}

/**
 * Side-by-side decision view for one author identity candidate: the local
 * Pure profile (public author API) against the external OpenAlex record,
 * plus the cascade evidence, with confirm/reject actions.
 */
export function AuthorIdentityDrawer({
  row,
  onClose,
  onFlip,
  busy,
}: {
  row: AuthorIdentityAdmin;
  onClose: () => void;
  onFlip: (row: AuthorIdentityAdmin, status: string, note: string, changedBy: string) => void;
  busy: string | null;
}) {
  const [note, setNote] = useState("");
  const [reviewer, setReviewer] = useReviewer();
  const [local, setLocal] = useState<LocalProfile | null>(null);
  const [localMissing, setLocalMissing] = useState(false);
  const [external, setExternal] = useState<OpenAlexAuthor | null>(null);
  const [externalWorks, setExternalWorks] = useState<OpenAlexWork[]>([]);
  const [externalFailed, setExternalFailed] = useState(false);

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
    setExternalWorks([]);
    setExternalFailed(false);
    if (!isOpenalex) return;
    void fetch(`https://api.openalex.org/authors/${row.external_id}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(String(res.status)))))
      .then((data) => {
        if (cancelled) return;
        setExternal(data as OpenAlexAuthor);
        return fetch(
          `https://api.openalex.org/works?filter=author.id:${row.external_id}&sort=publication_date:desc&per-page=8&select=display_name,publication_year,doi`,
        )
          .then((res) => (res.ok ? res.json() : Promise.reject(new Error(String(res.status)))))
          .then((works) => {
            if (!cancelled) setExternalWorks((works as { results: OpenAlexWork[] }).results ?? []);
          })
          .catch(() => undefined);
      })
      .catch(() => {
        if (!cancelled) setExternalFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [row, isOpenalex]);

  const evidence = (row.evidence ?? {}) as Record<string, unknown>;
  const evidenceOrcids = Array.isArray(evidence.orcids) ? (evidence.orcids as string[]) : [];
  const nameMatch =
    external != null &&
    !!row.author_name &&
    external.display_name.trim().toLowerCase() === row.author_name.trim().toLowerCase();
  const localOrcid = local?.author.orcid ?? null;
  const externalOrcid = external?.orcid ?? null;
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
              {local && external && (
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
              {local && external && orcidOverlap && <MatchBadge ok yes="ORCID in evidence" no="" />}
            </div>
            {isOpenalex ? (
              external ? (
                <div className="space-y-0.5">
                  <RecordField label="Display name" value={external.display_name} />
                  <RecordField
                    label="OpenAlex id"
                    value={row.external_id}
                    mono
                    href={`https://openalex.org/${row.external_id}`}
                  />
                  <RecordField label="ORCID" value={externalOrcid} mono />
                  <RecordField label="Works (OpenAlex)" value={external.works_count} />
                  <RecordField label="Citations" value={external.cited_by_count} />
                  <RecordField
                    label="Last known institution"
                    value={
                      external.last_known_institutions?.[0]?.display_name ??
                      external.last_known_institution?.display_name ??
                      null
                    }
                  />
                  <RecordField
                    label="Topics"
                    value={(external.topics ?? [])
                      .slice(0, 3)
                      .map((topic) => topic.display_name)
                      .join(", ")}
                  />
                  {(external.display_name_alternatives ?? []).length > 0 && (
                    <RecordField
                      label="Alternative names"
                      value={(external.display_name_alternatives ?? []).slice(0, 4).join(", ")}
                    />
                  )}
                  <div className="pt-2">
                    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Recent OpenAlex works
                    </p>
                    <ul className="mt-1 space-y-1 text-sm">
                      {externalWorks.map((work) => (
                        <li
                          key={`${work.display_name}-${work.publication_year}`}
                          className="truncate"
                          title={work.display_name}
                        >
                          <span className="text-muted-foreground">{work.publication_year}</span> ·{" "}
                          {work.display_name}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {externalFailed
                    ? "OpenAlex fetch failed (offline or rate-limited) — use the id link and evidence below."
                    : "Loading OpenAlex record…"}
                </p>
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
