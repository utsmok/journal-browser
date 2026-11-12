import type { ReactNode } from "react";

import { getTranslations } from "next-intl/server";

import type { DbSchema, SchemaTable } from "@/lib/data-pipeline/table-groups";
import { GROUP_LABEL_KEYS, TABLE_GROUPS } from "@/lib/data-pipeline/table-groups";
import schemaJson from "@/lib/data-pipeline-schema.json";

const schema = schemaJson as DbSchema;

function Chip({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--muted-foreground)]">
      {children}
    </span>
  );
}

async function TableDetails({ table }: { table: SchemaTable }) {
  const t = await getTranslations("dataPipeline");
  return (
    <details className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] px-4 py-1">
      <summary className="flex cursor-pointer flex-wrap items-center gap-2 py-2 text-sm">
        <span className="font-mono font-medium">{table.name}</span>
        <span className="text-[var(--muted-foreground)]">
          {t("database.columnsCount", { count: table.columns.length })}
        </span>
        {table.primaryKey.length > 0 && <Chip>{t("database.pkChip")}</Chip>}
        {table.foreignKeys.length > 0 && (
          <Chip>{t("database.fkChip", { count: table.foreignKeys.length })}</Chip>
        )}
      </summary>
      <div className="pb-3">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr className="border-b border-[var(--border)] text-left text-[var(--muted-foreground)]">
              <th scope="col" className="py-1.5 pr-4 font-semibold">
                {t("database.headColumn")}
              </th>
              <th scope="col" className="py-1.5 pr-4 font-semibold">
                {t("database.headType")}
              </th>
              <th scope="col" className="py-1.5 pr-4 font-semibold">
                {t("database.headNull")}
              </th>
              <th scope="col" className="py-1.5 font-semibold">
                {t("database.headDefault")}
              </th>
            </tr>
          </thead>
          <tbody>
            {table.columns.map((column) => (
              <tr key={column.name} className="border-b border-[var(--border)] last:border-0">
                <td className="py-1 pr-4 font-mono">{column.name}</td>
                <td className="py-1 pr-4 font-mono">{column.type}</td>
                <td className="py-1 pr-4 text-[var(--muted-foreground)]">
                  {column.nullable ? t("database.nullYes") : t("database.nullNo")}
                </td>
                <td className="py-1 font-mono text-[var(--muted-foreground)]">
                  {column.default === null
                    ? ""
                    : column.default.startsWith("nextval(")
                      ? t("database.defaultAutoincrement")
                      : column.default}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mt-3 space-y-1 text-xs text-[var(--muted-foreground)]">
          {table.primaryKey.length > 0 && (
            <p>{t("database.primaryKeyLine", { keys: table.primaryKey.join(", ") })}</p>
          )}
          {table.uniques.map((unique) => (
            <p key={unique.name}>
              {t("database.uniqueLine", { name: unique.name, columns: unique.columns.join(", ") })}
            </p>
          ))}
          {table.foreignKeys.map((fk) => (
            <p key={fk.name}>
              {t("database.foreignKeyLine", {
                columns: fk.columns.join(", "),
                table: fk.toTable,
                referencedColumns: fk.toColumns.join(", "),
                onDelete: fk.onDelete,
              })}
            </p>
          ))}
          {table.checks.length > 0 && (
            <p>
              {t("database.checksLine", {
                checks: table.checks.map((check) => `${check.name} ${check.definition}`).join("; "),
              })}
            </p>
          )}
          {table.indexes.length > 0 && (
            <p>
              {t("database.indexesLine", {
                count: table.indexes.length,
                names: table.indexes.map((index) => index.name).join(", "),
              })}
            </p>
          )}
        </div>
      </div>
    </details>
  );
}

export async function DbReference() {
  const t = await getTranslations("dataPipeline");
  const byName = new Map(schema.tables.map((table) => [table.name, table]));
  const grouped = new Set(TABLE_GROUPS.flatMap((group) => group.tables));
  const ungrouped = schema.tables.filter((table) => !grouped.has(table.name));
  return (
    <div className="space-y-6">
      {TABLE_GROUPS.map((group) => (
        <div key={group.name} className="space-y-2">
          <h3 className="text-lg font-semibold">{t(GROUP_LABEL_KEYS[group.name] ?? group.name)}</h3>
          {group.tables.map((tableName) => {
            const table = byName.get(tableName);
            if (!table) return null;
            return <TableDetails key={tableName} table={table} />;
          })}
        </div>
      ))}
      {ungrouped.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-lg font-semibold">{t("database.otherTables")}</h3>
          {ungrouped.map((table) => (
            <TableDetails key={table.name} table={table} />
          ))}
        </div>
      )}
    </div>
  );
}
