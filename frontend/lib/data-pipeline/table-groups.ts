export type SchemaColumn = {
  name: string;
  type: string;
  nullable: boolean;
  default: string | null;
};

export type SchemaForeignKey = {
  name: string;
  columns: string[];
  toTable: string;
  toColumns: string[];
  onUpdate: string;
  onDelete: string;
};

export type SchemaTable = {
  name: string;
  kind: string;
  columns: SchemaColumn[];
  primaryKey: string[];
  uniques: { name: string; columns: string[] }[];
  foreignKeys: SchemaForeignKey[];
  checks: { name: string; definition: string }[];
  indexes: { name: string; definition: string }[];
};

export type DbSchema = {
  generatedAt: string;
  tables: SchemaTable[];
};

export type TableGroup = {
  name: string;
  tables: string[];
};

export const TABLE_GROUPS: TableGroup[] = [
  {
    name: "Journal universe",
    tables: [
      "journals",
      "journal_flags",
      "journal_apc_aggregates",
      "apc_evidence",
      "scimagojr_metrics",
      "publishers",
      "openalex_publishers",
      "issn_map",
    ],
  },
  {
    name: "Works",
    tables: [
      "works",
      "openalex_works",
      "work_identity",
      "work_funders",
      "author_works",
      "work_pure_authors",
      "institution_works_stats",
      "institution_trends",
    ],
  },
  {
    name: "People and orgs",
    tables: [
      "authors",
      "author_identities",
      "pure_persons",
      "pure_person_orgs",
      "pure_orgs",
      "pure_org_parents",
    ],
  },
  {
    name: "Deals",
    tables: ["deals", "deal_journals", "deal_institutions"],
  },
  {
    name: "Funders and policy",
    tables: [
      "openalex_funders",
      "openaire_funders",
      "openaire_funder_streams",
      "funder_links",
      "jisc_funders",
      "jisc_funder_groups",
      "jisc_policies",
      "jisc_publications",
      "jisc_publishers",
      "jisc_repositories",
    ],
  },
  {
    name: "Landing and bookkeeping",
    tables: ["source_records", "raw_files", "harvest_runs", "harvest_state"],
  },
  {
    name: "Site and configuration",
    tables: [
      "institutions",
      "cache_epoch",
      "limitations",
      "manual_overrides",
      "status_changes",
      "feedback_items",
      "doc_edits",
      "usage_events",
    ],
  },
];
