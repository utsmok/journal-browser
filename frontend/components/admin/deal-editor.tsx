"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  AdminError,
  adminGet,
  adminPost,
  adminPut,
  type AdminDeal,
  type AdminDealDetail,
  type AdminDealJournal,
  type InstitutionDirectoryEntry,
} from "@/lib/admin";
import { cn } from "@/lib/utils";

const TEXTAREA_CLASS =
  "flex w-full rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-3 py-2 text-base min-[560px]:text-sm placeholder:text-[var(--muted-foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:opacity-50";

const SELECT_CLASS =
  "h-10 rounded-[var(--radius)] border border-input bg-[var(--card)] px-2 py-1 text-base min-[560px]:text-sm disabled:opacity-50";

const ISSN_RE = /^\d{4}-\d{3}[\dX]$/;

type CapRow = { year: string; count: string };

function yearsSpan(d: Pick<AdminDeal, "start_year" | "end_year">) {
  if (d.start_year == null && d.end_year == null) return "—";
  return `${d.start_year ?? "?"}–${d.end_year ?? ""}`;
}

function capToRows(cap: Record<string, number> | null): CapRow[] {
  return Object.entries(cap ?? {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([year, count]) => ({ year, count: String(count) }));
}

export function DealStatusBadge({ status }: { status: string }) {
  return <Badge variant={status === "current" ? "default" : "muted"}>{status}</Badge>;
}

function FlagBadge({ deal }: { deal: AdminDeal }) {
  if (!deal.needs_curation) return null;
  return (
    <Badge variant="outline" title={deal.needs_curation_reason ?? undefined}>
      flagged
    </Badge>
  );
}

/** Admin deals overview: one row per deal, click to open the editor. */
export function DealsTable({
  deals,
  selectedId,
  onSelect,
}: {
  deals: AdminDeal[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Publisher</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Years</TableHead>
          <TableHead>Journals</TableHead>
          <TableHead>Cap</TableHead>
          <TableHead>Institutions</TableHead>
          <TableHead>Flag</TableHead>
          <TableHead aria-label="Actions" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {deals.map((d) => (
          <TableRow
            key={d.id}
            className={cn("cursor-pointer", d.id === selectedId && "bg-[var(--muted)]")}
            onClick={() => onSelect(d.id)}
          >
            <TableCell>{d.publisher ?? `#${d.id}`}</TableCell>
            <TableCell>
              <DealStatusBadge status={d.status} />
            </TableCell>
            <TableCell className="whitespace-nowrap">{yearsSpan(d)}</TableCell>
            <TableCell>{d.journal_count}</TableCell>
            <TableCell>{d.capped ? <Badge variant="secondary">capped</Badge> : "—"}</TableCell>
            <TableCell
              className="max-w-xs truncate text-muted-foreground"
              title={d.participations.join(", ")}
            >
              {d.participations.length === 0 ? "—" : d.participations.join(", ")}
            </TableCell>
            <TableCell>
              <FlagBadge deal={d} />
            </TableCell>
            <TableCell>
              <Button
                variant="outline"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect(d.id);
                }}
              >
                Edit
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/**
 * Editor for one deal: editable deal fields (PUTs only the changed subset),
 * journal membership (add by ISSN / remove with confirm), and institutional
 * participations (each checkbox toggle PUTs immediately).
 */
export function DealEditor({
  dealId,
  token,
  institutions,
  onUnauthorized,
  onChanged,
}: {
  dealId: number;
  token: string;
  institutions: InstitutionDirectoryEntry[];
  onUnauthorized: (token: string | null) => void;
  /** Called after any mutation so the parent list can refetch. */
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<AdminDealDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [status, setStatus] = useState<"current" | "archive">("current");
  const [startYear, setStartYear] = useState("");
  const [endYear, setEndYear] = useState("");
  const [cao, setCao] = useState(false);
  const [esacId, setEsacId] = useState("");
  const [summary, setSummary] = useState("");
  const [capText, setCapText] = useState("");
  const [capRows, setCapRows] = useState<CapRow[]>([]);

  const [issn, setIssn] = useState("");
  const [issnName, setIssnName] = useState("");
  const [journalBusy, setJournalBusy] = useState(false);

  const fail = (err: unknown, what: string) => {
    if (err instanceof AdminError && err.status === 401) {
      onUnauthorized(null);
      return;
    }
    if (err instanceof AdminError && err.status === 409) {
      setError("ESAC id already in use.");
      return;
    }
    setError(`${what} failed (${err instanceof Error ? err.message : err}).`);
  };

  const reload = useCallback(async () => {
    try {
      const d = await adminGet<AdminDealDetail>(`/deals/${dealId}`, token);
      setDetail(d);
      setLoadError(null);
      setSaved(false);
      setError(null);
      setStatus(d.status);
      setStartYear(d.start_year == null ? "" : String(d.start_year));
      setEndYear(d.end_year == null ? "" : String(d.end_year));
      setCao(d.corresponding_authors_only);
      setEsacId(d.esac_id ?? "");
      setSummary(d.summary ?? "");
      setCapText(d.cap_text ?? "");
      setCapRows(capToRows(d.cap_numbers));
    } catch (err) {
      if (err instanceof AdminError && err.status === 401) onUnauthorized(null);
      else setLoadError(`Could not load deal (${err instanceof Error ? err.message : err}).`);
    }
  }, [dealId, token, onUnauthorized]);

  useEffect(() => {
    void reload();
  }, [reload]);

  if (loadError) return <p className="text-sm text-destructive">{loadError}</p>;
  if (!detail) return <p className="text-sm text-muted-foreground">Loading deal…</p>;

  const save = async () => {
    const sy = startYear.trim() === "" ? null : Number(startYear);
    const ey = endYear.trim() === "" ? null : Number(endYear);
    if (startYear.trim() !== "" && !Number.isInteger(sy)) {
      setError("Start year must be a whole year.");
      return;
    }
    if (endYear.trim() !== "" && !Number.isInteger(ey)) {
      setError("End year must be a whole year.");
      return;
    }
    let cap: Record<string, number> | null = null;
    if (capRows.length > 0) {
      cap = {};
      for (const row of capRows) {
        if (!/^\d{4}$/.test(row.year.trim())) {
          setError("Cap years must be 4-digit years.");
          return;
        }
        const n = Number(row.count);
        if (!Number.isInteger(n)) {
          setError("Cap counts must be whole numbers.");
          return;
        }
        cap[row.year.trim()] = n;
      }
    }
    // Diff against the loaded detail: only changed fields go into the PUT body.
    const body: Record<string, unknown> = {};
    if (status !== detail.status) body.status = status;
    if (sy !== detail.start_year) body.start_year = sy;
    if (ey !== detail.end_year) body.end_year = ey;
    if (cao !== detail.corresponding_authors_only) body.corresponding_authors_only = cao;
    if (esacId.trim() !== (detail.esac_id ?? ""))
      body.esac_id = esacId.trim() === "" ? null : esacId.trim();
    if (summary !== (detail.summary ?? "")) body.summary = summary === "" ? null : summary;
    if (capText !== (detail.cap_text ?? "")) body.cap_text = capText === "" ? null : capText;
    if (JSON.stringify(cap) !== JSON.stringify(detail.cap_numbers)) body.cap_numbers = cap;
    if (Object.keys(body).length === 0) {
      setError("No changes to save.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await adminPut<AdminDealDetail>(`/deals/${dealId}`, token, body);
      await reload();
      setSaved(true);
      onChanged();
    } catch (err) {
      fail(err, "Save");
    } finally {
      setSaving(false);
    }
  };

  /** Returns true when the membership change was applied. */
  const putJournals = async (body: {
    add?: { issn: string; journal_name?: string }[];
    remove?: string[];
  }): Promise<boolean> => {
    setJournalBusy(true);
    setError(null);
    try {
      const d = await adminPut<AdminDealDetail>(`/deals/${dealId}/journals`, token, body);
      setDetail(d);
      onChanged();
      return true;
    } catch (err) {
      fail(err, "Journal update");
      return false;
    } finally {
      setJournalBusy(false);
    }
  };

  const addJournal = () => {
    const clean = issn.trim().toUpperCase();
    if (!ISSN_RE.test(clean)) {
      setError("ISSN must look like 9999-9999 or 9999-999X.");
      return;
    }
    const entry: { issn: string; journal_name?: string } = { issn: clean };
    if (issnName.trim()) entry.journal_name = issnName.trim();
    void putJournals({ add: [entry] }).then((ok) => {
      if (ok) {
        setIssn("");
        setIssnName("");
      }
    });
  };

  const removeJournal = (j: AdminDealJournal) => {
    if (!window.confirm(`Remove ${j.journal_name ?? j.issn} (${j.issn}) from this deal?`)) return;
    void putJournals({ remove: [j.issn] });
  };

  const toggleParticipation = (code: string, add: boolean) => {
    setError(null);
    adminPut<AdminDealDetail>(`/deals/${dealId}/participations`, token, add ? { add: [code] } : { remove: [code] })
      .then((d) => {
        setDetail(d);
        onChanged();
      })
      .catch((err) => fail(err, "Participation update"));
  };

  return (
    <div className="space-y-6 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-base font-semibold">
          Edit deal: {detail.publisher ?? `#${detail.id}`}
        </h3>
        <DealStatusBadge status={detail.status} />
        <FlagBadge deal={detail} />
      </div>
      {detail.needs_curation && detail.needs_curation_reason && (
        <p className="text-sm text-muted-foreground">
          Flag reason: {detail.needs_curation_reason}
        </p>
      )}

      <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
        <div className="space-y-1">
          <label htmlFor="deal-status" className="text-sm font-medium">
            Status
          </label>
          <select
            id="deal-status"
            className={SELECT_CLASS}
            value={status}
            onChange={(e) => {
              setSaved(false);
              setStatus(e.target.value as "current" | "archive");
            }}
          >
            <option value="current">current</option>
            <option value="archive">archive</option>
          </select>
        </div>
        <div className="space-y-1">
          <label htmlFor="deal-esac" className="text-sm font-medium">
            ESAC id
          </label>
          <Input
            id="deal-esac"
            value={esacId}
            onChange={(e) => {
              setSaved(false);
              setEsacId(e.target.value);
            }}
          />
        </div>
        <div className="space-y-1">
          <label htmlFor="deal-start" className="text-sm font-medium">
            Start year
          </label>
          <Input
            id="deal-start"
            type="number"
            value={startYear}
            onChange={(e) => {
              setSaved(false);
              setStartYear(e.target.value);
            }}
          />
        </div>
        <div className="space-y-1">
          <label htmlFor="deal-end" className="text-sm font-medium">
            End year
          </label>
          <Input
            id="deal-end"
            type="number"
            value={endYear}
            onChange={(e) => {
              setSaved(false);
              setEndYear(e.target.value);
            }}
          />
        </div>
      </div>

      <label className="flex items-center gap-2 text-sm text-muted-foreground">
        <input
          type="checkbox"
          className="size-4 accent-[var(--primary)]"
          checked={cao}
          onChange={(e) => {
            setSaved(false);
            setCao(e.target.checked);
          }}
        />
        Corresponding authors only
      </label>

      <div className="space-y-1">
        <label htmlFor="deal-summary" className="text-sm font-medium">
          Summary
        </label>
        <textarea
          id="deal-summary"
          rows={3}
          className={TEXTAREA_CLASS}
          value={summary}
          onChange={(e) => {
            setSaved(false);
            setSummary(e.target.value);
          }}
        />
      </div>

      <div className="space-y-2">
        <p className="text-sm font-medium">
          Cap per year{" "}
          <span className="text-muted-foreground">(empty = not capped)</span>
        </p>
        {capRows.map((row, i) => (
          <div key={i} className="flex items-center gap-2">
            <Input
              type="number"
              aria-label="Cap year"
              placeholder="year"
              className="w-28"
              value={row.year}
              onChange={(e) => {
                setSaved(false);
                setCapRows((rows) =>
                  rows.map((r, j) => (j === i ? { ...r, year: e.target.value } : r)),
                );
              }}
            />
            <Input
              type="number"
              aria-label="Cap amount"
              placeholder="cap"
              className="w-28"
              value={row.count}
              onChange={(e) => {
                setSaved(false);
                setCapRows((rows) =>
                  rows.map((r, j) => (j === i ? { ...r, count: e.target.value } : r)),
                );
              }}
            />
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setSaved(false);
                setCapRows((rows) => rows.filter((_, j) => j !== i));
              }}
            >
              Remove
            </Button>
          </div>
        ))}
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setSaved(false);
            setCapRows((rows) => [...rows, { year: String(new Date().getFullYear()), count: "" }]);
          }}
        >
          Add year
        </Button>
        <div className="space-y-1">
          <label htmlFor="deal-cap-text" className="text-sm font-medium">
            Cap text
          </label>
          <Input
            id="deal-cap-text"
            value={capText}
            onChange={(e) => {
              setSaved(false);
              setCapText(e.target.value);
            }}
          />
        </div>
      </div>

      <div className="flex items-center gap-3">
        <Button onClick={() => void save()} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </Button>
        {saved && <span className="text-sm text-muted-foreground">Saved.</span>}
        {error && <span className="text-sm text-destructive">{error}</span>}
      </div>

      <div className="space-y-2 border-t border-[var(--border)] pt-4">
        <h4 className="text-sm font-semibold">Journals ({detail.journal_count})</h4>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            aria-label="ISSN"
            placeholder="9999-9999 or 9999-999X"
            className="w-48"
            value={issn}
            onChange={(e) => setIssn(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !journalBusy) addJournal();
            }}
          />
          <Input
            aria-label="Journal name"
            placeholder="Name (optional)"
            className="w-56"
            value={issnName}
            onChange={(e) => setIssnName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !journalBusy) addJournal();
            }}
          />
          <Button size="sm" onClick={() => void addJournal()} disabled={journalBusy}>
            Add
          </Button>
        </div>
        <div className="max-h-72 overflow-y-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ISSN</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Source</TableHead>
                <TableHead aria-label="Actions" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {detail.journals.map((j) => (
                <TableRow key={j.issn} className={cn(j.excluded && "text-muted-foreground line-through")}>
                  <TableCell className={cn("font-mono text-xs", j.excluded && "line-through")}>
                    {j.issn}
                  </TableCell>
                  <TableCell className={cn(j.excluded && "line-through")}>
                    {j.journal_name ?? "—"}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{j.source}</Badge>
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={journalBusy}
                      onClick={() => removeJournal(j)}
                    >
                      Remove
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>

      <div className="space-y-2 border-t border-[var(--border)] pt-4">
        <h4 className="text-sm font-semibold">Participating institutions</h4>
        <div className="grid gap-2 sm:grid-cols-2">
          {institutions.map((inst) => (
            <label
              key={inst.code}
              className="flex items-center gap-2 text-sm text-muted-foreground"
            >
              <input
                type="checkbox"
                className="size-4 accent-[var(--primary)]"
                checked={detail.participations.includes(inst.code)}
                onChange={(e) => toggleParticipation(inst.code, e.target.checked)}
              />
              {inst.short_name ?? inst.name}
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}

/** Minimal create form: publisher name (or nothing else), ESAC id, status, years. */
export function CreateDealForm({
  token,
  onUnauthorized,
  onCreated,
  onCancel,
}: {
  token: string;
  onUnauthorized: (token: string | null) => void;
  /** Called with the new deal id so the parent can select it in the editor. */
  onCreated: (id: number) => void;
  onCancel: () => void;
}) {
  const [publisherName, setPublisherName] = useState("");
  const [esacId, setEsacId] = useState("");
  const [status, setStatus] = useState<"current" | "archive">("current");
  const [startYear, setStartYear] = useState("");
  const [endYear, setEndYear] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = async () => {
    if (!publisherName.trim()) {
      setError("Publisher name is required.");
      return;
    }
    const sy = startYear.trim() === "" ? undefined : Number(startYear);
    const ey = endYear.trim() === "" ? undefined : Number(endYear);
    if (
      (sy !== undefined && !Number.isInteger(sy)) ||
      (ey !== undefined && !Number.isInteger(ey))
    ) {
      setError("Years must be whole numbers.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const detail = await adminPost<AdminDealDetail>("/deals", token, {
        publisher_name: publisherName.trim(),
        ...(esacId.trim() ? { esac_id: esacId.trim() } : {}),
        status,
        ...(sy !== undefined ? { start_year: sy } : {}),
        ...(ey !== undefined ? { end_year: ey } : {}),
      });
      onCreated(detail.id);
    } catch (err) {
      if (err instanceof AdminError && err.status === 401) onUnauthorized(null);
      else if (err instanceof AdminError && err.status === 409)
        setError("ESAC id already in use.");
      else if (err instanceof AdminError && err.status === 422)
        setError("Publisher not found — provide a publisher name.");
      else setError(`Create failed (${err instanceof Error ? err.message : err}).`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4">
      <h3 className="text-base font-semibold">Add deal</h3>
      <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
        <div className="space-y-1">
          <label htmlFor="new-deal-publisher" className="text-sm font-medium">
            Publisher name
          </label>
          <Input
            id="new-deal-publisher"
            value={publisherName}
            onChange={(e) => setPublisherName(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <label htmlFor="new-deal-esac" className="text-sm font-medium">
            ESAC id <span className="text-muted-foreground">(optional)</span>
          </label>
          <Input id="new-deal-esac" value={esacId} onChange={(e) => setEsacId(e.target.value)} />
        </div>
        <div className="space-y-1">
          <label htmlFor="new-deal-status" className="text-sm font-medium">
            Status
          </label>
          <select
            id="new-deal-status"
            className={SELECT_CLASS}
            value={status}
            onChange={(e) => setStatus(e.target.value as "current" | "archive")}
          >
            <option value="current">current</option>
            <option value="archive">archive</option>
          </select>
        </div>
        <div className="flex items-end gap-2">
          <div className="w-28 space-y-1">
            <label htmlFor="new-deal-start" className="text-sm font-medium">
              Start year
            </label>
            <Input
              id="new-deal-start"
              type="number"
              value={startYear}
              onChange={(e) => setStartYear(e.target.value)}
            />
          </div>
          <div className="w-28 space-y-1">
            <label htmlFor="new-deal-end" className="text-sm font-medium">
              End year
            </label>
            <Input
              id="new-deal-end"
              type="number"
              value={endYear}
              onChange={(e) => setEndYear(e.target.value)}
            />
          </div>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <Button onClick={() => void create()} disabled={saving}>
          {saving ? "Creating…" : "Create"}
        </Button>
        <Button variant="ghost" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
        {error && <span className="text-sm text-destructive">{error}</span>}
      </div>
    </div>
  );
}
