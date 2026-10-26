"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  AdminError,
  adminGet,
  adminPut,
  type InstitutionSettings,
  type SettingField,
  type SettingsResponse,
} from "@/lib/admin";

/** Field set for the flat /admin/institutions/{code} payload (no schema from the API). */
const INST_FIELDS: SettingField[] = [
  { key: "name", section: "institution", type: "string", label: "Name" },
  { key: "short_name", section: "institution", type: "string", label: "Short name" },
  { key: "active", section: "institution", type: "bool", label: "Active" },
  { key: "ror", section: "institution", type: "string", label: "ROR" },
  { key: "openalex_id", section: "institution", type: "string", label: "OpenAlex ID" },
  {
    key: "pure_oai_base_url",
    section: "institution",
    type: "string",
    label: "Pure OAI base URL",
  },
  {
    key: "openaire_org_id",
    section: "institution",
    type: "string",
    label: "OpenAIRE organisation ID",
  },
  {
    key: "data_window_start",
    section: "institution",
    type: "number",
    label: "Data window start",
  },
  { key: "data_window_end", section: "institution", type: "number", label: "Data window end" },
  { key: "library_url", section: "institution", type: "string", label: "Library URL" },
  { key: "oa_guide_url", section: "institution", type: "string", label: "OA guide URL" },
  { key: "support_email", section: "institution", type: "string", label: "Support email" },
  { key: "admin_contact", section: "institution", type: "string", label: "Admin contact" },
  {
    key: "research_portal_url",
    section: "institution",
    type: "string",
    label: "Research portal URL",
  },
];

/** API value → editable draft: raw input text for text-ish fields, boolean for bools. */
function toDraft(field: SettingField, value: unknown): string | boolean {
  if (field.type === "bool") return value === true;
  if (field.type === "list") return Array.isArray(value) ? value.join("\n") : "";
  if (field.type === "secret") return ""; // typed new value only; masked stored value is never echoed
  return value == null ? "" : String(value);
}

/** Draft → PUT body value; undefined = leave out of the request (keeps stored value). */
function toBodyValue(field: SettingField, raw: string | boolean): string | number | boolean | string[] | undefined {
  if (field.type === "bool") return raw === true;
  if (field.type === "secret") return raw === "" ? undefined : String(raw);
  const text = String(raw);
  if (field.type === "number") return text.trim() === "" ? undefined : Number(text.trim());
  if (field.type === "list")
    return text.split("\n").map((line) => line.trim()).filter(Boolean);
  const trimmed = text.trim();
  return trimmed === "" ? "" : trimmed;
}

function isChanged(field: SettingField, draft: string | boolean, initial: unknown): boolean {
  if (field.type === "bool") return draft !== (initial === true);
  if (field.type === "secret") return draft !== "";
  if (field.type === "number") {
    const text = String(draft).trim();
    return text === "" ? initial != null : Number(text) !== initial;
  }
  if (field.type === "list")
    return (
      JSON.stringify(toBodyValue(field, draft)) !==
      JSON.stringify(Array.isArray(initial) ? initial : [])
    );
  return String(draft).trim() !== String(initial ?? "").trim();
}

const TEXTAREA_CLASS =
  "flex w-full rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-3 py-2 text-base min-[560px]:text-sm placeholder:text-[var(--muted-foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:opacity-50";

function SettingRow({
  field,
  value,
  placeholder,
  onChange,
}: {
  field: SettingField;
  value: string | boolean;
  placeholder?: string;
  onChange: (value: string | boolean) => void;
}) {
  const id = `setting-${field.key}`;
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="text-sm font-medium">
        {field.label}
      </label>
      {field.type === "bool" ? (
        <label htmlFor={id} className="flex items-center gap-2 text-sm text-muted-foreground">
          <input
            id={id}
            type="checkbox"
            className="size-4 accent-[var(--primary)]"
            checked={value === true}
            onChange={(e) => onChange(e.target.checked)}
          />
          {value ? "Enabled" : "Disabled"}
        </label>
      ) : field.type === "list" ? (
        <textarea
          id={id}
          rows={3}
          className={TEXTAREA_CLASS}
          value={String(value)}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <Input
          id={id}
          type={field.type === "number" ? "number" : field.type === "secret" ? "password" : "text"}
          placeholder={placeholder}
          value={String(value)}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {field.help && <p className="text-xs text-muted-foreground">{field.help}</p>}
      {field.type === "list" && (
        <p className="text-xs text-muted-foreground">One value per line.</p>
      )}
    </div>
  );
}

type Doc = { fields: SettingField[]; values: Record<string, unknown> };

/**
 * One schema-driven editor for both settings surfaces: "global" renders the
 * /admin/settings schema (section=global); "institution" renders the flat
 * /admin/institutions/{code} payload against INST_FIELDS. Saves a diff —
 * only changed fields go into the PUT body; omitted fields keep their
 * stored value, which is how secrets stay untouched.
 */
function SettingsForm({
  variant,
  token,
  code,
  onUnauthorized,
}: {
  variant: "global" | "institution";
  token: string;
  code?: string;
  /** Called with null to drop the stored token; pass the useAdminToken setter. */
  onUnauthorized: (token: string | null) => void;
}) {
  const [fields, setFields] = useState<SettingField[] | null>(null);
  const [initial, setInitial] = useState<Record<string, unknown>>({});
  const [draft, setDraft] = useState<Record<string, string | boolean>>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchDoc = useCallback(async (): Promise<Doc> => {
    if (variant === "institution") {
      const inst = await adminGet<InstitutionSettings>(
        `/institutions/${encodeURIComponent(code ?? "")}`,
        token,
      );
      return { fields: INST_FIELDS, values: inst };
    }
    const res = await adminGet<SettingsResponse>("/settings", token);
    return {
      fields: res.schema.filter((f) => f.section === "global"),
      values: res.values,
    };
  }, [variant, code, token]);

  const put = useCallback(
    (body: Record<string, unknown>) =>
      variant === "institution"
        ? adminPut(`/institutions/${encodeURIComponent(code ?? "")}`, token, body)
        : adminPut("/settings", token, { values: body }),
    [variant, code, token],
  );

  const reload = useCallback(async () => {
    try {
      const doc = await fetchDoc();
      setFields(doc.fields);
      setInitial(doc.values);
      setDraft(Object.fromEntries(doc.fields.map((f) => [f.key, toDraft(f, doc.values[f.key])])));
      setLoadError(null);
      setSaved(false);
      setError(null);
    } catch (err) {
      if (err instanceof AdminError && err.status === 401) onUnauthorized(null);
      else setLoadError(`Could not load settings (${err instanceof Error ? err.message : err}).`);
    }
  }, [fetchDoc, onUnauthorized]);

  useEffect(() => {
    void reload();
  }, [reload]);

  if (loadError) return <p className="text-sm text-destructive">{loadError}</p>;
  if (!fields) return <p className="text-sm text-muted-foreground">Loading…</p>;

  const save = async () => {
    for (const f of fields) {
      if (f.type === "number" && String(draft[f.key]).trim() !== "" && Number.isNaN(Number(draft[f.key]))) {
        setError(`"${f.label}" must be a number.`);
        return;
      }
    }
    // Secrets and cleared numbers omit themselves from the body (toBodyValue
    // returns undefined), so an "empty" diff means nothing can be sent.
    const body: Record<string, unknown> = {};
    for (const f of fields) {
      if (!isChanged(f, draft[f.key], initial[f.key])) continue;
      const value = toBodyValue(f, draft[f.key]);
      if (value !== undefined) body[f.key] = value;
    }
    if (Object.keys(body).length === 0) {
      setError("No changes to save.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await put(body);
      await reload();
      setSaved(true);
    } catch (err) {
      if (err instanceof AdminError && err.status === 401) onUnauthorized(null);
      else setError(`Save failed (${err instanceof Error ? err.message : err}).`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
        {fields.map((f) => (
          <SettingRow
            key={f.key}
            field={f}
            value={draft[f.key]}
            placeholder={
              f.type === "secret" ? (initial[f.key] ? "set (********)" : "not set") : undefined
            }
            onChange={(value) => {
              setSaved(false);
              setDraft((d) => ({ ...d, [f.key]: value }));
            }}
          />
        ))}
      </div>
      <div className="flex items-center gap-3">
        <Button onClick={() => void save()} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </Button>
        {saved && <span className="text-sm text-muted-foreground">Saved.</span>}
        {error && <span className="text-sm text-destructive">{error}</span>}
      </div>
    </div>
  );
}

export function GlobalSettingsForm({
  token,
  onUnauthorized,
}: {
  token: string;
  onUnauthorized: (token: string | null) => void;
}) {
  return <SettingsForm variant="global" token={token} onUnauthorized={onUnauthorized} />;
}

export function InstitutionSettingsForm({
  token,
  code,
  onUnauthorized,
}: {
  token: string;
  code: string;
  onUnauthorized: (token: string | null) => void;
}) {
  return <SettingsForm variant="institution" token={token} code={code} onUnauthorized={onUnauthorized} />;
}
