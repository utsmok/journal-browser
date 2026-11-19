"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

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

type CapUsageRow = {
  year: string;
  pool: string;
  total: string;
  used: string;
  asOf: string;
  note: string;
};

function yearsSpan(d: Pick<AdminDeal, "start_year" | "end_year">) {
  if (d.start_year == null && d.end_year == null) return "—";
  return `${d.start_year ?? "?"}–${d.end_year ?? ""}`;
}

function capToRows(cap: Record<string, unknown> | null): CapRow[] {
  return Object.entries(cap ?? {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([year, count]) => ({ year, count: String(count) }));
}

/** Stable JSON form with object keys sorted, so change detection cannot
 * hinge on key insertion order. */
function canonicalJson(value: unknown): string {
  return JSON.stringify(value, (_key, v) =>
    v !== null && typeof v === "object" && !Array.isArray(v)
      ? Object.fromEntries(Object.entries(v).sort())
      : v,
  );
}

function capUsageToRows(usage: AdminDealDetail["cap_usage"]): CapUsageRow[] {
  return (usage ?? []).map((entry) => ({
    year: String(entry.year),
    pool: entry.pool ?? "",
    total: String(entry.total),
    used: entry.used == null ? "" : String(entry.used),
    asOf: entry.as_of ?? "",
    note: entry.note ?? "",
  }));
}

export function DealStatusBadge({ status }: { status: string }) {
  const t = useTranslations("admin");
  const label =
    status === "current"
      ? t("deals.statusCurrent")
      : status === "archive"
        ? t("deals.statusArchive")
        : status;
  return <Badge variant={status === "current" ? "default" : "muted"}>{label}</Badge>;
}

function FlagBadge({ deal }: { deal: AdminDeal }) {
  const t = useTranslations("admin");
  if (!deal.needs_curation) return null;
  return (
    <Badge variant="outline" title={deal.needs_curation_reason ?? undefined}>
      {t("deals.flagged")}
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
  const t = useTranslations("admin");
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("deals.columnPublisher")}</TableHead>
          <TableHead>{t("deals.columnStatus")}</TableHead>
          <TableHead>{t("deals.columnYears")}</TableHead>
          <TableHead>{t("deals.columnJournals")}</TableHead>
          <TableHead>{t("deals.columnCap")}</TableHead>
          <TableHead>{t("deals.columnInstitutions")}</TableHead>
          <TableHead>{t("deals.columnFlag")}</TableHead>
          <TableHead aria-label={t("deals.columnActions")} />
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
            <TableCell>
              {d.capped ? <Badge variant="secondary">{t("deals.capped")}</Badge> : "—"}
            </TableCell>
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
                {t("deals.edit")}
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
  const t = useTranslations("admin");
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
  const [capUsageRows, setCapUsageRows] = useState<CapUsageRow[]>([]);

  const [issn, setIssn] = useState("");
  const [issnName, setIssnName] = useState("");
  const [journalBusy, setJournalBusy] = useState(false);

  const fail = (err: unknown, action: string) => {
    if (err instanceof AdminError && err.status === 401) {
      onUnauthorized(null);
      return;
    }
    if (err instanceof AdminError && err.status === 409) {
      setError(t("deals.esacInUse"));
      return;
    }
    setError(
      t("deals.actionFailed", {
        action,
        message: err instanceof Error ? err.message : String(err),
      }),
    );
  };

  const reload = useCallback(async () => {
    // Skip the pre-hydration window (token still "") — an unauthenticated
    // fetch here 401s and would clear a valid stored session.
    if (!token) return;
    try {
      const d = await adminGet<AdminDealDetail>(`/deals/${dealId}`, token);
      setDetail(d);
      setLoadError(null);
      setSaved(false);
      setError(null);
      setStatus(d.status);
      setStartYear(d.start_year == null ? "" : String(d.start_year));
      setEndYear(d.end_year == null ? "" : String(d.end_year));
      setCao(d.corresponding_authors_only ?? false);
      setEsacId(d.esac_id ?? "");
      setSummary(d.summary ?? "");
      setCapText(d.cap_text ?? "");
      setCapRows(capToRows(d.cap_numbers));
      setCapUsageRows(capUsageToRows(d.cap_usage));
    } catch (err) {
      if (err instanceof AdminError && err.status === 401) onUnauthorized(null);
      else
        setLoadError(
          t("deals.loadFailed", { message: err instanceof Error ? err.message : String(err) }),
        );
    }
  }, [dealId, token, onUnauthorized, t]);

  useEffect(() => {
    void reload();
  }, [reload]);

  if (loadError) return <p className="text-sm text-destructive">{loadError}</p>;
  if (!detail) return <p className="text-sm text-muted-foreground">{t("deals.loading")}</p>;

  const save = async () => {
    const sy = startYear.trim() === "" ? null : Number(startYear);
    const ey = endYear.trim() === "" ? null : Number(endYear);
    if (startYear.trim() !== "" && !Number.isInteger(sy)) {
      setError(t("deals.startYearWhole"));
      return;
    }
    if (endYear.trim() !== "" && !Number.isInteger(ey)) {
      setError(t("deals.endYearWhole"));
      return;
    }
    let cap: Record<string, number> | null = null;
    if (capRows.length > 0) {
      cap = {};
      for (const row of capRows) {
        if (!/^\d{4}$/.test(row.year.trim())) {
          setError(t("deals.capYearsFourDigits"));
          return;
        }
        const n = Number(row.count);
        if (!Number.isInteger(n)) {
          setError(t("deals.capCountsWhole"));
          return;
        }
        cap[row.year.trim()] = n;
      }
    }
    let capUsage: Record<string, unknown>[] | null = null;
    if (capUsageRows.length > 0) {
      capUsage = [];
      for (const row of capUsageRows) {
        if (row.year.trim() === "" || row.total.trim() === "") {
          setError(t("deals.capUsageNeedsYearTotal"));
          return;
        }
        const year = Number(row.year);
        const total = Number(row.total);
        const used = row.used.trim() === "" ? null : Number(row.used);
        if (
          !Number.isInteger(year) ||
          !Number.isInteger(total) ||
          (used != null && !Number.isInteger(used))
        ) {
          setError(t("deals.capUsageWhole"));
          return;
        }
        capUsage.push({
          year,
          pool: row.pool.trim() || null,
          total,
          used,
          as_of: row.asOf.trim() || null,
          note: row.note.trim() || null,
        });
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
    if (canonicalJson(cap) !== canonicalJson(detail.cap_numbers)) body.cap_numbers = cap;
    if (canonicalJson(capUsage) !== canonicalJson(detail.cap_usage ?? null))
      body.cap_usage = capUsage;
    if (Object.keys(body).length === 0) {
      setError(t("deals.noChanges"));
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
      fail(err, t("deals.actionSave"));
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
      fail(err, t("deals.actionJournalUpdate"));
      return false;
    } finally {
      setJournalBusy(false);
    }
  };

  const addJournal = () => {
    const clean = issn.trim().toUpperCase();
    if (!ISSN_RE.test(clean)) {
      setError(t("deals.issnFormat"));
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
    if (
      !window.confirm(
        t("deals.removeJournalConfirm", { name: j.journal_name ?? j.issn, issn: j.issn }),
      )
    )
      return;
    void putJournals({ remove: [j.issn] });
  };

  const toggleParticipation = (code: string, add: boolean) => {
    setError(null);
    adminPut<AdminDealDetail>(
      `/deals/${dealId}/participations`,
      token,
      add ? { add: [code] } : { remove: [code] },
    )
      .then((d) => {
        setDetail(d);
        onChanged();
      })
      .catch((err) => fail(err, t("deals.actionParticipationUpdate")));
  };

  return (
    <div className="space-y-6 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-base font-semibold">
          {t("deals.editTitle", { publisher: detail.publisher ?? `#${detail.id}` })}
        </h3>
        <DealStatusBadge status={detail.status} />
        <FlagBadge deal={detail} />
      </div>
      {detail.needs_curation && detail.needs_curation_reason && (
        <p className="text-sm text-muted-foreground">
          {t("deals.flagReason", { reason: detail.needs_curation_reason })}
        </p>
      )}

      <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
        <div className="space-y-1">
          <label htmlFor="deal-status" className="text-sm font-medium">
            {t("deals.status")}
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
            <option value="current">{t("deals.statusCurrent")}</option>
            <option value="archive">{t("deals.statusArchive")}</option>
          </select>
        </div>
        <div className="space-y-1">
          <label htmlFor="deal-esac" className="text-sm font-medium">
            {t("deals.esacId")}
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
            {t("deals.startYear")}
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
            {t("deals.endYear")}
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
        {t("deals.correspondingOnly")}
      </label>

      <div className="space-y-1">
        <label htmlFor="deal-summary" className="text-sm font-medium">
          {t("deals.summary")}
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
          {t("deals.capTitle")}{" "}
          <span className="text-muted-foreground">{t("deals.capTitleHint")}</span>
        </p>
        {capRows.map((row, i) => (
          <div key={i} className="flex items-center gap-2">
            <Input
              type="number"
              aria-label={t("deals.capYear")}
              placeholder={t("deals.capYearPlaceholder")}
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
              aria-label={t("deals.capAmount")}
              placeholder={t("deals.capAmountPlaceholder")}
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
              {t("deals.remove")}
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
          {t("deals.addYear")}
        </Button>
        <div className="space-y-1">
          <label htmlFor="deal-cap-text" className="text-sm font-medium">
            {t("deals.capText")}
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

      <div className="space-y-2">
        <p className="text-sm font-medium">
          {t("deals.capUsageTitle")}{" "}
          <span className="text-muted-foreground">{t("deals.capUsageTitleHint")}</span>
        </p>
        {capUsageRows.map((row, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2">
            <Input
              type="number"
              aria-label={t("deals.usageYear")}
              placeholder={t("deals.capYearPlaceholder")}
              className="w-24"
              value={row.year}
              onChange={(e) => {
                setSaved(false);
                setCapUsageRows((rows) =>
                  rows.map((r, j) => (j === i ? { ...r, year: e.target.value } : r)),
                );
              }}
            />
            <Input
              aria-label={t("deals.usagePool")}
              placeholder={t("deals.usagePoolPlaceholder")}
              className="w-40"
              value={row.pool}
              onChange={(e) => {
                setSaved(false);
                setCapUsageRows((rows) =>
                  rows.map((r, j) => (j === i ? { ...r, pool: e.target.value } : r)),
                );
              }}
            />
            <Input
              type="number"
              aria-label={t("deals.usageTotal")}
              placeholder={t("deals.usageTotalPlaceholder")}
              className="w-24"
              value={row.total}
              onChange={(e) => {
                setSaved(false);
                setCapUsageRows((rows) =>
                  rows.map((r, j) => (j === i ? { ...r, total: e.target.value } : r)),
                );
              }}
            />
            <Input
              type="number"
              aria-label={t("deals.apcsUsed")}
              placeholder={t("deals.apcsUsedPlaceholder")}
              className="w-24"
              value={row.used}
              onChange={(e) => {
                setSaved(false);
                setCapUsageRows((rows) =>
                  rows.map((r, j) => (j === i ? { ...r, used: e.target.value } : r)),
                );
              }}
            />
            <Input
              aria-label={t("deals.reportedAsOf")}
              placeholder={t("deals.asOfPlaceholder")}
              className="w-56"
              value={row.asOf}
              onChange={(e) => {
                setSaved(false);
                setCapUsageRows((rows) =>
                  rows.map((r, j) => (j === i ? { ...r, asOf: e.target.value } : r)),
                );
              }}
            />
            <Input
              aria-label={t("deals.usageNote")}
              placeholder={t("deals.usageNotePlaceholder")}
              className="w-56"
              value={row.note}
              onChange={(e) => {
                setSaved(false);
                setCapUsageRows((rows) =>
                  rows.map((r, j) => (j === i ? { ...r, note: e.target.value } : r)),
                );
              }}
            />
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setSaved(false);
                setCapUsageRows((rows) => rows.filter((_, j) => j !== i));
              }}
            >
              {t("deals.remove")}
            </Button>
          </div>
        ))}
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setSaved(false);
            setCapUsageRows((rows) => [
              ...rows,
              {
                year: String(new Date().getFullYear()),
                pool: "",
                total: "",
                used: "",
                asOf: "",
                note: "",
              },
            ]);
          }}
        >
          {t("deals.addEntry")}
        </Button>
      </div>

      <div className="flex items-center gap-3">
        <Button onClick={() => void save()} disabled={saving}>
          {saving ? t("deals.saving") : t("deals.save")}
        </Button>
        {saved && <span className="text-sm text-muted-foreground">{t("deals.saved")}</span>}
        {error && <span className="text-sm text-destructive">{error}</span>}
      </div>

      <div className="space-y-2 border-t border-[var(--border)] pt-4">
        <h4 className="text-sm font-semibold">
          {t("deals.journalsTitle", { count: detail.journal_count })}
        </h4>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            aria-label={t("deals.issn")}
            placeholder={t("deals.issnPlaceholder")}
            className="w-48"
            value={issn}
            onChange={(e) => setIssn(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !journalBusy) addJournal();
            }}
          />
          <Input
            aria-label={t("deals.journalName")}
            placeholder={t("deals.journalNamePlaceholder")}
            className="w-56"
            value={issnName}
            onChange={(e) => setIssnName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !journalBusy) addJournal();
            }}
          />
          <Button size="sm" onClick={() => void addJournal()} disabled={journalBusy}>
            {t("deals.add")}
          </Button>
        </div>
        <div className="max-h-72 overflow-y-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("deals.columnIssn")}</TableHead>
                <TableHead>{t("deals.columnName")}</TableHead>
                <TableHead>{t("deals.columnSource")}</TableHead>
                <TableHead aria-label={t("deals.columnActions")} />
              </TableRow>
            </TableHeader>
            <TableBody>
              {detail.journals.map((j) => (
                <TableRow
                  key={j.issn}
                  className={cn(j.excluded && "text-muted-foreground line-through")}
                >
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
                      {t("deals.remove")}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>

      <div className="space-y-2 border-t border-[var(--border)] pt-4">
        <h4 className="text-sm font-semibold">{t("deals.participations")}</h4>
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
  const t = useTranslations("admin");
  const [publisherName, setPublisherName] = useState("");
  const [esacId, setEsacId] = useState("");
  const [status, setStatus] = useState<"current" | "archive">("current");
  const [startYear, setStartYear] = useState("");
  const [endYear, setEndYear] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = async () => {
    if (!publisherName.trim()) {
      setError(t("deals.publisherRequired"));
      return;
    }
    const sy = startYear.trim() === "" ? undefined : Number(startYear);
    const ey = endYear.trim() === "" ? undefined : Number(endYear);
    if (
      (sy !== undefined && !Number.isInteger(sy)) ||
      (ey !== undefined && !Number.isInteger(ey))
    ) {
      setError(t("deals.yearsWhole"));
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
      else if (err instanceof AdminError && err.status === 409) setError(t("deals.esacInUse"));
      else if (err instanceof AdminError && err.status === 422)
        setError(t("deals.publisherNotFound"));
      else
        setError(
          t("deals.createFailed", { message: err instanceof Error ? err.message : String(err) }),
        );
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4">
      <h3 className="text-base font-semibold">{t("deals.createTitle")}</h3>
      <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
        <div className="space-y-1">
          <label htmlFor="new-deal-publisher" className="text-sm font-medium">
            {t("deals.publisherName")}
          </label>
          <Input
            id="new-deal-publisher"
            value={publisherName}
            onChange={(e) => setPublisherName(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <label htmlFor="new-deal-esac" className="text-sm font-medium">
            {t("deals.esacId")}{" "}
            <span className="text-muted-foreground">{t("deals.esacIdOptional")}</span>
          </label>
          <Input id="new-deal-esac" value={esacId} onChange={(e) => setEsacId(e.target.value)} />
        </div>
        <div className="space-y-1">
          <label htmlFor="new-deal-status" className="text-sm font-medium">
            {t("deals.status")}
          </label>
          <select
            id="new-deal-status"
            className={SELECT_CLASS}
            value={status}
            onChange={(e) => setStatus(e.target.value as "current" | "archive")}
          >
            <option value="current">{t("deals.statusCurrent")}</option>
            <option value="archive">{t("deals.statusArchive")}</option>
          </select>
        </div>
        <div className="flex items-end gap-2">
          <div className="w-28 space-y-1">
            <label htmlFor="new-deal-start" className="text-sm font-medium">
              {t("deals.startYear")}
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
              {t("deals.endYear")}
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
          {saving ? t("deals.creating") : t("deals.create")}
        </Button>
        <Button variant="ghost" onClick={onCancel} disabled={saving}>
          {t("deals.cancel")}
        </Button>
        {error && <span className="text-sm text-destructive">{error}</span>}
      </div>
    </div>
  );
}
