import type { Metadata } from "next";
import type { ReactNode } from "react";

import { DagDiagram } from "@/components/data-pipeline/dag-diagram";
import { DbReference } from "@/components/data-pipeline/db-reference";
import { DomainMap } from "@/components/data-pipeline/domain-map";
import { OaRules } from "@/components/data-pipeline/oa-rules";
import { StorageFlow } from "@/components/data-pipeline/storage-flow";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { SOURCES } from "@/lib/data-pipeline/sources";
import schema from "@/lib/data-pipeline-schema.json";

export const metadata: Metadata = {
  title: "Data pipeline",
  description: "Where the site's data comes from and how it is harvested and stored.",
};

const tableCount = schema.tables.length;
const columnCount = schema.tables.reduce((sum, table) => sum + table.columns.length, 0);
const institutionFkCount = schema.tables.reduce(
  (sum, table) => sum + table.foreignKeys.filter((fk) => fk.toTable === "institutions").length,
  0,
);

// [step, request shape, writes]
const OPENALEX_CALLS: [string, string, string][] = [
  [
    "journals",
    "GET /sources cursor sweep, 100 per page; batch GET for deal seeds; institution id resolved by ROR search",
    "source_records, journals, issn_map",
  ],
  [
    "publishers",
    "GET /publishers batches of 50, lineage roots fetched on demand",
    "openalex_publishers, journals.publisher_canonical",
  ],
  [
    "oa-colors",
    "GET /works per journal, filter primary_location.source, 20 most recent, concurrency 4",
    "journals.oa_status_observed",
  ],
  [
    "stats",
    "GET /works cursor sweep filtered by institution id and window; GET /works count per year with authorships.is_corresponding",
    "source_records, institution_works_stats, institution_trends",
  ],
  [
    "enrich",
    "GET /works/{doi} one call per DOI, chunks of 500, concurrency 10",
    "source_records, work_identity (confirmed), works fields",
  ],
  [
    "author-ids",
    "GET /authors cursor sweep by affiliations.institution.ror, 200 per page; GET /works for 50 author ids per call",
    "source_records, author_identities, openalex_works reproject",
  ],
];

const CROSSREF_CALLS: [string, string, string][] = [
  [
    "enrich",
    "GET /works?filter=doi:... batches of 50 DOIs, polite pool",
    "source_records, work_identity, works.journal_issn_l",
  ],
];

const PURE_CALLS: [string, string, string][] = [
  [
    "pure",
    "ListRecords, metadataPrefix oai_dc, set publications:year{Y} per window year",
    "source_records, works (upsert, retire on full sweep)",
  ],
  [
    "pure-cerif",
    "ListRecords, metadataPrefix oai_cerif_openaire, set openaire_cris_publications",
    "source_records, works.cerif_* columns, work_pure_authors",
  ],
  [
    "pure-entities",
    "ListRecords, same prefix, sets openaire_cris_orgunits and openaire_cris_persons",
    "source_records, pure_orgs, pure_org_parents, pure_persons",
  ],
];

const OPENAIRE_CALLS: [string, string, string][] = [
  [
    "openaire",
    "GET /researchProducts via aireloom, 100 per page, filtered by the institution's org id",
    "source_records, work_identity",
  ],
];

const DEAL_CALLS: [string, string, string][] = [
  [
    "deals-openaccess-nl",
    "GET overview /en/publishing/publisher-deals, then /en/publisher/{slug}, then each deal page, sequential",
    "raw_files, source_records, publishers, deals",
  ],
  [
    "deals-jct",
    "GET index sheet CSV, then one CSV per agreement with jitter",
    "raw_files, source_records, deals, deal_journals, deal_institutions",
  ],
  [
    "deals-reconcile",
    "database only: merge on esac_id, enforce unique agreement data, write a curation report to landing/reports",
    "deals, deal_journals, deal_institutions, journal_flags",
  ],
  [
    "deals-issn-l",
    "database only: issn_map lookup for NULL coverage ISSNs",
    "deal_journals.issn_l, needs_curation flags",
  ],
];

const CSV_CALLS: [string, string, string][] = [
  [
    "openapc",
    "GET 5 CSVs from raw.githubusercontent.com/OpenAPC/openapc-de",
    "raw_files, source_records, journal_apc_aggregates, apc_evidence, journals.latest_apc_euro",
  ],
  ["doaj", "GET https://doaj.org/csv", "raw_files, journals doaj_* columns"],
  [
    "scimagojr",
    "tracked seeds expanded into landing, no network",
    "scimagojr_metrics, journals.in_scimago, journals.latest_quartile",
  ],
];

// [job, what it does, writes]
const MANUAL_JOBS: [string, string, string][] = [
  [
    "harvest_jisc + normalize_jisc",
    "sweep the Jisc Open Policy Finder (x-api-key, search_after paging) and normalize into the canon tables; stamps journals.jisc_* policy columns",
    "jisc_publications, jisc_publishers, jisc_policies, jisc_funders, jisc_funder_groups, jisc_repositories, journals.jisc_*",
  ],
  [
    "harvest_openalex_funders",
    "full OpenAlex funders sweep, 200 per page",
    "openalex_funders, funder_links refresh",
  ],
  [
    "harvest_openaire_funders",
    "curated OpenAIRE funder canon (NWO, EC, Wellcome, NSF) plus level-0 funding streams",
    "openaire_funders, openaire_funder_streams",
  ],
  [
    "harvest_work_funders",
    "per-work funder and grant rows for every DOI work, single GETs in chunks of 500",
    "work_funders",
  ],
  [
    "import_pure_export",
    "import a Pure backend OAI export file as full CERIF records",
    "source_records (entity work_cerif_full)",
  ],
  [
    "harvest_pure_portal",
    "fill missing pure_org_parents from the public portal RSS, browser user agent, 2 s delay",
    "pure_org_parents, source_records",
  ],
  [
    "harvest_portal_persons",
    "bind relay-harvested portal person listings to persons and orgs",
    "pure_person_orgs, source_records",
  ],
  [
    "import_utmetadata_raw",
    "one-shot copy of ut-metadata verbatim works into the local landing store and stats rebuild",
    "source_records, institution_works_stats",
  ],
  ["import_utmetadata_works", "one-shot copy of ut-metadata canonical works into works", "works"],
  [
    "ingest_emerald_contract",
    "reconstruct one deal's journal list from the signed contract spreadsheet",
    "deal_journals (source manual), deal_institutions, deals",
  ],
  [
    "enrich_usage_geo",
    "backfill usage_events.country from ip-api.com batches",
    "usage_events.country",
  ],
  ["verify_utmetadata", "dev check that the local corpus matches ut-metadata", "nothing (report)"],
  [
    "funder_link_matrix",
    "coverage report of Jisc funders linked to OpenAlex and OpenAIRE twins",
    "nothing (stdout)",
  ],
];

const OA_RULES: string[] = [
  "OA evidence (is_in_doaj, is_oa, or doaj_in_doaj) plus charge evidence (a DOAJ APC flag, OpenAPC rows, latest_apc_euro, or an OpenAlex list price) gives gold.",
  "DOAJ-listed with doaj_has_apc explicitly false gives diamond.",
  "An observed work color of gold, diamond, or hybrid gives that value.",
  "Deal coverage gives hybrid.",
  "Remaining OA evidence gives generic.",
  "Everything else is subscription.",
];

const TOC: [string, string][] = [
  ["External sources", "sources"],
  ["Harvest order", "dag"],
  ["How each source is harvested", "jobs"],
  ["What bootstrap does not fetch", "manual"],
  ["How data is stored", "storage"],
  ["Database reference", "database"],
  ["How the site serves this data", "serving"],
];

function Code({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-[var(--muted)] px-1 font-mono text-[0.875em]">{children}</code>
  );
}

function CallsTable({ rows }: { rows: [string, string, string][] }) {
  return (
    <Card>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Step</TableHead>
              <TableHead>Request shape</TableHead>
              <TableHead>Writes</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map(([step, request, writes]) => (
              <TableRow key={step}>
                <TableCell className="whitespace-nowrap font-mono text-xs">{step}</TableCell>
                <TableCell>{request}</TableCell>
                <TableCell className="font-mono text-xs">{writes}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </Card>
  );
}

function DataTable({ head, rows }: { head: string[]; rows: string[][] }) {
  return (
    <Card>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              {head.map((label) => (
                <TableHead key={label}>{label}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row[0]}>
                <TableCell className="whitespace-nowrap font-mono text-xs">{row[0]}</TableCell>
                {row.slice(1, -1).map((cell) => (
                  <TableCell key={cell}>{cell}</TableCell>
                ))}
                <TableCell className="font-mono text-xs">{row[row.length - 1]}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </Card>
  );
}

export default function DataPipelinePage() {
  return (
    <div className="mx-auto max-w-screen-2xl space-y-10 px-4 py-10">
      <header className="space-y-3">
        <h1 className="text-3xl font-bold">Data pipeline</h1>
        <p className="max-w-prose">
          This page maps where the site&apos;s data comes from, how harvest jobs fetch it, and how
          the database stores it. It documents the working code, and the database section is
          generated from the live schema, so it cannot drift from reality by hand. Row counts change
          while jobs run, so the page carries none. For live freshness, query{" "}
          <Code>GET /api/v1/{"{code}"}/meta/freshness</Code>.
        </p>
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
          {TOC.map(([label, id]) => (
            <li key={id}>
              <a href={`#${id}`} className="text-[var(--primary-text)] hover:underline">
                {label}
              </a>
            </li>
          ))}
        </ul>
      </header>

      <section id="sources" className="space-y-4">
        <h2 className="mt-2 text-2xl font-semibold">External sources</h2>
        <p className="max-w-prose">
          Fourteen feeds supply the database. Thirteen are outside services; one is the previous
          platform&apos;s own Postgres, read over a DSN. The Runs column names bootstrap steps;
          anything marked manual runs only when someone starts it.
        </p>
        <DataTable
          head={["Source", "Provides", "Transport and pacing", "Used by"]}
          rows={SOURCES.map((source) => [
            source.name,
            source.provides,
            source.transport,
            source.usedBy,
          ])}
        />
      </section>

      <section id="dag" className="space-y-4">
        <h2 className="mt-2 text-2xl font-semibold">Harvest order</h2>
        <p className="max-w-prose">
          Bootstrap runs <Code>backend/jobs/bootstrap.py</Code>. It plans three bands: a global
          layer shared by every institution, a per-institution layer that runs once for each hosted
          institution code, and a final embeddings step. The scheduler launches any step the moment
          all of its dependencies have finished, so independent branches overlap. Every step is a
          subprocess. If a step fails, no new step launches, running siblings finish, and the
          process exits nonzero, which keeps the backend from starting on a half-filled database.
        </p>
        <p className="max-w-prose">
          Three modes matter. Auto mode, the deployment default, exits immediately when the journals
          table already has rows. Repair mode (<Code>--from STEP</Code>) reruns the plan serially
          starting at one step. <Code>--institution CODE</Code> replans for a single institution
          only, which is how a new institution joins an existing deployment.
        </p>
        <Card className="p-4">
          <DagDiagram />
        </Card>
        <p className="text-sm text-[var(--muted-foreground)]">
          Every institution step runs once per hosted code; cross-layer dependencies pull from the
          global band.
        </p>
      </section>

      <section id="jobs" className="space-y-6">
        <h2 className="mt-2 text-2xl font-semibold">How each source is harvested</h2>

        <div className="space-y-3">
          <h3 className="text-lg font-semibold">OpenAlex</h3>
          <p className="max-w-prose">
            One cursor sweep over the sources collection fills the journal universe (
            <Code>journals</Code>), keyed on ISSN-L, with every variant ISSN mapped through{" "}
            <Code>issn_map</Code>. The same job seeds deal-covered journals in batches of 50 when
            run with <Code>--seed-deals-only</Code>. Publisher lineage is resolved afterwards in
            batches of 50 publisher ids, including a second pass for lineage roots.
          </p>
          <p className="max-w-prose">
            Five institution-side jobs read OpenAlex. The stats job sweeps all works of the
            institution (filter <Code>institutions.id</Code>, one page per 100) and counts
            corresponding-author works per year. The enrich job resolves journals for each work DOI
            with single-entity GETs in chunks of 500 at concurrency 10, which stays inside the free
            key&apos;s 30 requests per second; a 404 is recorded as a missing identity so Crossref
            only sees true gaps. The author-ids job sweeps authors affiliated with the
            institution&apos;s ROR (200 per page) and then pulls works for resolved author ids, 50
            ids per request, up to a budget of 2000 authors. The OA color job samples the 20 most
            recent works of each OA journal, four journals at a time, and fills only NULL observed
            colors, so it is resumable.
          </p>
          <CallsTable rows={OPENALEX_CALLS} />
        </div>

        <div className="space-y-3">
          <h3 className="text-lg font-semibold">Crossref</h3>
          <p className="max-w-prose">
            Works whose DOI missed at OpenAlex go to Crossref in batches of 50 DOIs through the
            polite pool (the configured contact email identifies the client). Confirmed matches
            write the same work_identity rows and resolve journal ISSNs through issn_map. The CERIF
            rung after both tries local <Code>works.cerif_issn</Code> values and needs no network.
          </p>
          <CallsTable rows={CROSSREF_CALLS} />
        </div>

        <div className="space-y-3">
          <h3 className="text-lg font-semibold">Pure OAI-PMH</h3>
          <p className="max-w-prose">
            Three passes over the same OAI endpoint, all anonymous, paced at one second, and
            paginated by resumption token; a stale token restarts the set at most twice. The works
            pass lists <Code>oai_dc</Code> records one OAI set per publication year in the data
            window; a full sweep also retires works that disappeared from Pure by stamping
            retired_at. The CERIF pass lists the <Code>openaire_cris_publications</Code> set with
            the CERIF metadata prefix and fills each work&apos;s CERIF ISSN, publisher, DOI, and OA
            status plus the per-work author edges in work_pure_authors. The entities pass lists the
            orgunit and person sets and rebuilds pure_orgs, pure_org_parents, and pure_persons from
            the stored records.
          </p>
          <CallsTable rows={PURE_CALLS} />
        </div>

        <div className="space-y-3">
          <h3 className="text-lg font-semibold">OpenAIRE</h3>
          <p className="max-w-prose">
            When the institution has an <Code>openaire_org_id</Code>, the openaire job sweeps the
            Graph API&apos;s research products (100 per page, the v3 maximum), stores every payload
            verbatim, and confirms work_identity rows where the product&apos;s DOI matches a local
            work. Title matching produces candidate rows for review instead of silent facts.
          </p>
          <CallsTable rows={OPENAIRE_CALLS} />
        </div>

        <div className="space-y-3">
          <h3 className="text-lg font-semibold">Deal registers</h3>
          <p className="max-w-prose">
            Two independent harvests feed one merged register. The openaccess.nl scraper walks the
            publisher-deals overview, then each publisher page, then each deal page, strictly one
            request at a time, and stores every HTML page verbatim. The JCT job reads the published
            index sheet, then one CSV per agreement at its Data URL, jittered 0.5 to 1.5 s because
            Google throttles bursts. Reconcile merges both on ESAC id, never letting a conflict win
            silently: conflicting rows get flagged needs_curation, admin-removed rows stay excluded,
            and manual_overrides reapply after every run. A final pass resolves coverage ISSNs to
            ISSN-L through issn_map and flags the rows it cannot resolve.
          </p>
          <CallsTable rows={DEAL_CALLS} />
        </div>

        <div className="space-y-3">
          <h3 className="text-lg font-semibold">OpenAPC, DOAJ, Scimago</h3>
          <p className="max-w-prose">
            The OpenAPC job downloads five CSV files from the project&apos;s GitHub raw storage,
            stores them as landing copies, and rebuilds two aggregates by full replace:
            journal_apc_aggregates per ISSN-L and period, and apc_evidence for the home institution,
            then refreshes journals.latest_apc_euro. The DOAJ job downloads the full journal CSV
            once and stamps is_in_doaj, DOAJ APC facts, and the canon homepage onto journals by ISSN
            match; OA journals DOAJ does not list get an explicit false. The Scimago job expands
            tracked seed CSVs (the site blocks scripted clients), upserts scimagojr_metrics per
            ISSN-L and year, stamps journals.in_scimago, and refreshes latest_quartile.
          </p>
          <CallsTable rows={CSV_CALLS} />
        </div>
      </section>

      <section id="manual" className="space-y-4">
        <h2 className="mt-2 text-2xl font-semibold">What bootstrap does not fetch</h2>
        <p className="max-w-prose">
          These jobs exist in the repo but the bootstrap plan never calls them. Some are one-shot
          repairs, some backfill data the automatic pipeline does not cover, and some are dev
          checks. A fresh deployment runs without their data until someone runs them by hand.
        </p>
        <DataTable head={["Job", "What it does", "Writes"]} rows={MANUAL_JOBS} />
      </section>

      <section id="storage" className="space-y-4">
        <h2 className="mt-2 text-2xl font-semibold">How data is stored</h2>
        <p className="max-w-prose">
          Every payload lands verbatim before anything is normalized. The download helper writes the
          bytes under <Code>landing/</Code> and records a raw_files row; an ingest session then
          stores the parsed payload in source_records with a SHA-256 content hash on (source, entity
          type, source key, hash), so re-harvesting identical content inserts nothing and every
          version stays. Normalized tables such as journals, works, openalex_works, deals, the Pure
          tables, and the Jisc tables rebuild from those stored copies, which is what makes every
          job safe to rerun.
        </p>
        <p className="max-w-prose">
          A third layer denormalizes serving state onto the rows the site reads: journal_flags (one
          row per journal per hosted institution), works_2020_plus, latest_apc_euro,
          publisher_canonical, oa_status_observed, the persisted search_vector column, and the
          embedding vectors. Every run is bookkept in harvest_runs and harvest_state, and a
          successful run bumps the single-row cache_epoch, which invalidates the in-process facet
          and snapshot caches (24 hour TTL, keyed on the epoch).
        </p>
        <p className="max-w-prose">
          Not everything arrives from harvests. The site itself writes usage_events (batched page
          views, searches, and errors; IP addresses are nulled after a retention window),
          feedback_items (with the reporter&apos;s query state), doc_edits (admin edits applied over
          served docs), manual_overrides (admin corrections that reapply after every harvest),
          author_identities and work_identity review decisions, and the append-only status_changes
          audit.
        </p>
        <StorageFlow />
      </section>

      <section id="database" className="space-y-4">
        <h2 className="mt-2 text-2xl font-semibold">Database reference</h2>
        <p className="max-w-prose">
          {tableCount} tables, {columnCount} columns, generated from the live database on{" "}
          {schema.generatedAt} by <Code>backend/scripts/dump_db_schema.py</Code>. The
          alembic_version bookkeeping table is excluded. Regenerate after schema changes with{" "}
          <Code>
            {
              "cd backend && uv run python scripts/dump_db_schema.py --dsn <read-only dsn> --out ../frontend/lib/data-pipeline-schema.json"
            }
          </Code>
          .
        </p>
        <Card className="p-4">
          <DomainMap />
        </Card>
        <p className="text-sm text-[var(--muted-foreground)]">
          Most tables also carry an institution_id foreign key into institutions; those{" "}
          {institutionFkCount} edges are omitted to keep the map readable.
        </p>
        <DbReference />
        <p className="text-sm text-[var(--muted-foreground)]">
          {tableCount} tables, {columnCount} columns
        </p>
      </section>

      <section id="serving" className="space-y-4">
        <h2 className="mt-2 text-2xl font-semibold">How the site serves this data</h2>
        <p className="max-w-prose">
          Journal search funnels every listing through one shared query,{" "}
          <Code>services/search/query.py</Code> <Code>base_query</Code>. It joins journals to the
          institution&apos;s journal_flags row, keeps journal-type venues with more than 3 works in
          the window plus every other venue type with at least one institution work, and never
          serves journals marked browse_excluded. Relevance combines a title-prefix tier, Postgres
          full-text rank, and a small works_count nudge. Facets run over the identical filtered base
          and cache for 24 hours keyed on the cache epoch. Journal detail assembles the row plus
          deal coverage, per-year institution stats (a pure_canon and an OpenAlex dimension),
          Scimago quartiles, APC aggregates and evidence, the raw venue payload, and works from the
          openalex_works store.
        </p>
        <p className="max-w-prose">
          Journal <Code>oa_type</Code> is derived at query time, never stored. First match wins:
        </p>
        <ol className="max-w-prose list-decimal space-y-1 pl-5 text-sm">
          {OA_RULES.map((rule) => (
            <li key={rule}>{rule}</li>
          ))}
        </ol>
        <p className="max-w-prose">
          NULL flags never count as false; a NULL doaj_in_doaj means the DOAJ sweep never judged the
          journal. Work-level oa_status is stored at harvest time instead, canonicalized to a
          six-value vocabulary. The funder fit tiers on top combine oa_type with the Jisc
          green-route columns (submitted, accepted, or published versions allowed, embargo months)
          in one SQL case mirrored in Python.
        </p>
        <OaRules />
        <p className="max-w-prose">
          Journals embed as 384-dimension vectors over cleaned title, top five topics, and up to
          three most-cited work titles, using BAAI/bge-small-en-v1.5 through fastembed ONNX on CPU.
          An HNSW index in pgvector serves similar-journal lists in three scopes (institution,
          deals, all) and semantic search; author recommendations average their venues&apos; vectors
          weighted by work counts. The embeddings step is the last bootstrap step and runs once,
          after every institution&apos;s stats step.
        </p>
      </section>
    </div>
  );
}
