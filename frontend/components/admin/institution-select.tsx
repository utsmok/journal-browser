"use client";

import { useInstitutionsDirectory } from "@/hooks/use-api";

const SELECT_CLASS =
  "rounded-[var(--radius)] border border-input bg-[var(--card)] px-2 py-1 text-sm";

/**
 * Institution picker fed by the public directory. With `allLabel` it gains an
 * "all institutions" option whose value is the literal "all" — callers map
 * that to an absent filter.
 */
export function InstitutionSelect({
  id,
  value,
  onChange,
  allLabel,
}: {
  id: string;
  value: string;
  onChange: (code: string) => void;
  allLabel?: string;
}) {
  const { data } = useInstitutionsDirectory();
  const unis = data ?? [];
  return (
    <select
      id={id}
      className={SELECT_CLASS}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      {allLabel && <option value="all">{allLabel}</option>}
      {unis.map((inst) => (
        <option key={inst.code} value={inst.code}>
          {inst.name}
        </option>
      ))}
    </select>
  );
}
