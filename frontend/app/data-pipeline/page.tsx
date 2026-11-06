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
import { PLAN } from "@/lib/data-pipeline/dag";
import { SOURCES } from "@/lib/data-pipeline/sources";
import schema from "@/lib/data-pipeline-schema.json";

export const metadata: Metadata = {
  title: "Data pipeline",
  description: "Where the site's data comes from, and how it is harvested and stored.",
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
    "GET /sources, one page of 100 at a time, following the cursor to the end. A batched request seeds the deal journals. The institution is found by searching for its ROR id.",
    "source_records, journals, issn_map",
  ],
  [
    "publishers",
    "GET /publishers in batches of 50 ids. A second request on demand fetches the top of the ownership chain.",
    "openalex_publishers, journals.publisher_canonical",
  ],
  [
    "oa-colors",
    "GET /works per journal, filtered to the primary location source, 20 newest works, 4 journals in parallel.",
    "journals.oa_status_observed",
  ],
  [
    "stats",
    "GET /works with cursor paging, filtered to the institution id and the data window. One count request per year counts works with a corresponding author from the institution.",
    "source_records, institution_works_stats, institution_trends",
  ],
  [
    "enrich",
    "GET /works/{doi}, one request per DOI, in chunks of 500 with 10 requests in flight.",
    "source_records, work_identity (confirmed), works fields",
  ],
  [
    "author-ids",
    "GET /authors with cursor paging, filtered by the institution's ROR, 200 per page. Then GET /works for 50 author ids per request.",
    "source_records, author_identities, openalex_works reproject",
  ],
];

const CROSSREF_CALLS: [string, string, string][] = [
  [
    "enrich",
    "GET /works with a doi filter listing 50 DOIs per request, sent through the polite pool.",
    "source_records, work_identity, works.journal_issn_l",
  ],
];

const PURE_CALLS: [string, string, string][] = [
  [
    "pure",
    "OAI ListRecords in the oai_dc metadata format, one OAI set per publication year in the data window.",
    "source_records, works (upsert, retire on full sweep)",
  ],
  [
    "pure-cerif",
    "OAI ListRecords in the oai_cerif_openaire format, set openaire_cris_publications.",
    "source_records, works.cerif_* columns, work_pure_authors",
  ],
  [
    "pure-entities",
    "OAI ListRecords in the same format, sets openaire_cris_orgunits and openaire_cris_persons.",
    "source_records, pure_orgs, pure_org_parents, pure_persons",
  ],
];

const OPENAIRE_CALLS: [string, string, string][] = [
  [
    "openaire",
    "GET /researchProducts through the aireloom client, 100 per page, filtered to the institution's org id.",
    "source_records, work_identity",
  ],
];

const DEAL_CALLS: [string, string, string][] = [
  [
    "deals-openaccess-nl",
    "GET the overview page, then each publisher page, then each deal page, one request at a time.",
    "raw_files, source_records, publishers, deals",
  ],
  [
    "deals-jct",
    "GET the index sheet as CSV, then one CSV per agreement, pausing 0.5 to 1.5 seconds between downloads.",
    "raw_files, source_records, deals, deal_journals, deal_institutions",
  ],
  [
    "deals-reconcile",
    "No network. Merges rows on ESAC id, enforces unique agreement data, writes a curation report to landing/reports.",
    "deals, deal_journals, deal_institutions, journal_flags",
  ],
  [
    "deals-issn-l",
    "No network. Fills missing coverage ISSNs from issn_map.",
    "deal_journals.issn_l, needs_curation flags",
  ],
];

const CSV_CALLS: [string, string, string][] = [
  [
    "openapc",
    "GET 5 CSV files from raw.githubusercontent.com/OpenAPC/openapc-de.",
    "raw_files, source_records, journal_apc_aggregates, apc_evidence, journals.latest_apc_euro",
  ],
  ["doaj", "GET the full CSV from https://doaj.org/csv.", "raw_files, journals doaj_* columns"],
  [
    "scimagojr",
    "No network. Unpacks the seed CSVs kept in the repository.",
    "scimagojr_metrics, journals.in_scimago, journals.latest_quartile",
  ],
];

// [job, what it does, writes]
const MANUAL_JOBS: [string, string, string][] = [
  [
    "harvest_jisc + normalize_jisc",
    "Sweeps the Jisc Open Policy Finder with an API key and normalizes the result into the canon tables. Stamps the journals.jisc_* policy columns.",
    "jisc_publications, jisc_publishers, jisc_policies, jisc_funders, jisc_funder_groups, jisc_repositories, journals.jisc_*",
  ],
  [
    "harvest_openalex_funders",
    "Sweeps all OpenAlex funders, 200 per page.",
    "openalex_funders, funder_links refresh",
  ],
  [
    "harvest_openaire_funders",
    "Writes a curated OpenAIRE funder canon (NWO, EC, Wellcome, NSF) and its top-level funding streams.",
    "openaire_funders, openaire_funder_streams",
  ],
  [
    "harvest_work_funders",
    "Fetches funder and grant rows for every work that has a DOI, one request per work in chunks of 500.",
    "work_funders",
  ],
  [
    "import_pure_export",
    "Imports a Pure backend OAI export file as full CERIF records.",
    "source_records (entity work_cerif_full)",
  ],
  [
    "harvest_pure_portal",
    "Fills missing pure_org_parents from the public portal RSS, 2 seconds between requests.",
    "pure_org_parents, source_records",
  ],
  [
    "harvest_portal_persons",
    "Binds portal person listings to persons and orgs.",
    "pure_person_orgs, source_records",
  ],
  [
    "import_utmetadata_raw",
    "One-time copy of ut-metadata raw works into the local landing store, then rebuilds the stats.",
    "source_records, institution_works_stats",
  ],
  ["import_utmetadata_works", "One-time copy of ut-metadata canonical works into works.", "works"],
  [
    "ingest_emerald_contract",
    "Rebuilds one deal's journal list from the signed contract spreadsheet.",
    "deal_journals (source manual), deal_institutions, deals",
  ],
  [
    "enrich_usage_geo",
    "Backfills usage_events.country from ip-api.com in batches of up to 100 IPs.",
    "usage_events.country",
  ],
  [
    "verify_utmetadata",
    "Development check that the local corpus matches ut-metadata. Writes a report, no data.",
    "nothing (report)",
  ],
  [
    "funder_link_matrix",
    "Reports how many Jisc funders have OpenAlex and OpenAIRE twins. Writes to stdout only.",
    "nothing (stdout)",
  ],
];

const TOC: [string, string][] = [
  ["External sources", "sources"],
  ["Harvest order", "dag"],
  ["How each source is harvested", "jobs"],
  ["Scheduling", "scheduling"],
  ["What bootstrap does not fetch", "manual"],
  ["Configuration", "config"],
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
          This page documents where the site&apos;s data comes from. It covers the external sources,
          the harvest jobs that fetch data from them, the order the jobs run in, and how the
          database stores the result. The text describes the working code, and the database section
          is generated from the live database, so the two cannot drift apart. The page shows no row
          counts, because counts change every time a job runs. To see current counts and harvest
          times, call <Code>GET /api/v1/{"{code}"}/meta/freshness</Code>.
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
          The database receives data from fourteen inputs. Eleven of them are services on the
          network. One is a set of CSV files kept in this repository. One is a read-only connection
          to the previous platform&apos;s Postgres database. One is a language model that runs
          locally. The Used by column names the harvest steps that read each source, and a step
          marked manual runs only when someone starts it by hand.
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
          Bootstrap is the script at <Code>backend/jobs/bootstrap.py</Code>. It plans the work in
          three groups, and this page calls the groups bands. The global band runs once for the
          whole deployment. The institution band runs once for every hosted institution. The final
          band holds one step, journal embeddings. Bootstrap starts each step as a separate process
          the moment that step&apos;s dependencies have finished, so independent branches run at the
          same time. When a step fails, bootstrap starts no new steps, lets the running steps
          finish, and exits with an error code. The deployment then refuses to start the backend,
          because the database is only partly filled.
        </p>
        <p className="max-w-prose">
          Every HTTP call in the harvest jobs uses the same client settings. A request times out
          after 120 seconds. When an API answers with 429 or a temporary server error, the client
          retries the request up to three times. It waits as long as the Retry-After header asks
          when the API sends one, and otherwise it waits longer after each attempt, up to 60
          seconds.
        </p>
        <p className="max-w-prose">
          Bootstrap has three run modes, and auto mode is the default. Auto mode skips the whole
          plan when two things are true. The journals table has rows, and the plan left its
          completion marker behind. The marker is one <Code>harvest_state</Code> row with source{" "}
          <Code>local</Code> and entity <Code>bootstrap_plan</Code>, and the plan runner writes it
          after the plan finishes without error. Journals without the marker mean an earlier
          bootstrap stopped partway. In that case auto mode refuses to run and exits with error 1
          instead of skipping. Repair mode, started with <Code>--from STEP</Code>, reruns the plan
          from one step onward, one step at a time. <Code>--institution CODE</Code> runs the plan
          for a single institution, which is how a new institution joins an existing deployment.
        </p>
        <Card className="p-4">
          <DagDiagram />
        </Card>
        <p className="text-sm text-[var(--muted-foreground)]">
          The institution band runs once per hosted code. Dependencies that cross bands read from
          the global band.
        </p>
        <p className="max-w-prose text-sm text-[var(--muted-foreground)]">
          The step list, scripts, and dependencies come from <Code>jobs/bootstrap.py</Code>.
          <Code>backend/scripts/dump_harvest_plan.py</Code> generated them on {PLAN.generatedAt}.
          The diagram checks its arrows against the same file when the site builds, so the picture
          and the list cannot disagree.
        </p>
        <details className="max-w-prose text-sm">
          <summary className="cursor-pointer text-[var(--muted-foreground)]">
            All {PLAN.steps.reduce((count, step) => count + step.deps.length, 0)} dependency edges
          </summary>
          <p className="mt-2 leading-6">
            {PLAN.steps.flatMap((step) => step.deps.map((dep) => `${dep} → ${step.id}`)).join("; ")}
          </p>
        </details>
      </section>

      <section id="jobs" className="space-y-6">
        <h2 className="mt-2 text-2xl font-semibold">How each source is harvested</h2>

        <div className="space-y-3">
          <h3 className="text-lg font-semibold">OpenAlex</h3>
          <p className="max-w-prose">
            The journals job walks the OpenAlex sources list with cursor pagination. In cursor
            pagination, each response carries a cursor, and the job follows it until the list ends.
            The job writes one row per journal into <Code>journals</Code>, keyed by ISSN-L. ISSN-L
            is the standard id that groups a journal&apos;s print, online, and variant ISSNs under
            one id, and the job maps every variant ISSN to it in <Code>issn_map</Code>. With{" "}
            <Code>--seed-deals-only</Code>, the same job does less. It writes only the journals
            covered by a deal, in batches of 50. The publishers job runs after it and resolves each
            journal&apos;s publisher lineage from OpenAlex publisher ids, 50 at a time. It makes a
            second pass for lineage roots, the publishers at the top of an ownership chain.
          </p>
          <p className="max-w-prose">
            Five institution-side jobs read OpenAlex. The stats job sweeps every work of the
            institution, 100 per page, and counts per year how many works had an institution author
            as the corresponding author. The enrich job asks OpenAlex about each work DOI, one DOI
            per request, in chunks of 500 with 10 requests in flight. That stays far below
            OpenAlex&apos;s published limit of 100 requests per second, and each single-work request
            costs 1 credit of the 100,000 credits a free key gets per day. When OpenAlex has no work
            for a DOI, the job records the identity as missing, so Crossref later sees only the DOIs
            worth trying. The author-ids job sweeps authors affiliated with the institution&apos;s
            ROR id, 200 per page, and then fetches the works of the authors it resolved, 50 author
            ids per request, up to 2000 authors per run. The OA color job samples the 20 newest
            works of each open-access journal, four journals at a time. It fills only colors it has
            not observed yet, so an interrupted run can continue.
          </p>
          <CallsTable rows={OPENALEX_CALLS} />
        </div>

        <div className="space-y-3">
          <h3 className="text-lg font-semibold">Crossref</h3>
          <p className="max-w-prose">
            DOIs that OpenAlex does not know go to Crossref next. The enrich job sends them in
            batches of 50. The contact email in each request tells Crossref who is asking, which
            puts the client in Crossref&apos;s polite pool, the pool with steadier response times. A
            confirmed match writes the same <Code>work_identity</Code> rows as OpenAlex and resolves
            the journal through <Code>issn_map</Code>. The third rung needs no network at all. Works
            that still have no journal are checked against the CERIF ISSN recorded on the work
            itself.
          </p>
          <CallsTable rows={CROSSREF_CALLS} />
        </div>

        <div className="space-y-3">
          <h3 className="text-lg font-semibold">Pure OAI-PMH</h3>
          <p className="max-w-prose">
            Three passes read the same Pure OAI-PMH endpoint at ris.utwente.nl. OAI-PMH is a
            standard XML protocol for harvesting repository content. The passes are anonymous, wait
            at least one second between requests, and walk each set page by page using resumption
            tokens, the continuation ids the protocol returns with every page. If a token goes
            stale, the pass restarts that set, at most twice.
          </p>
          <p className="max-w-prose">
            The works pass requests one OAI set per publication year in the data window, in a simple
            metadata format. A full sweep also retires works that have disappeared from Pure by
            stamping their <Code>retired_at</Code> time. The CERIF pass requests the CERIF
            publication set, which uses a richer metadata format. From it, the pass fills each
            work&apos;s CERIF ISSN, publisher, DOI, and open-access status, plus the work-to-author
            edges in <Code>work_pure_authors</Code>. The entities pass requests the org unit and
            person sets, and rebuilds <Code>pure_orgs</Code>, <Code>pure_org_parents</Code>, and{" "}
            <Code>pure_persons</Code> from the stored records.
          </p>
          <CallsTable rows={PURE_CALLS} />
        </div>

        <div className="space-y-3">
          <h3 className="text-lg font-semibold">OpenAIRE</h3>
          <p className="max-w-prose">
            The openaire job runs when the institution has an <Code>openaire_org_id</Code>. It walks
            the OpenAIRE Graph API&apos;s research products, 100 per page, which is the API&apos;s
            maximum, and stores every payload verbatim. When a product&apos;s DOI matches a local
            work, the job confirms that work&apos;s identity. When only the title matches, the job
            records a candidate row for a person to review, instead of claiming a match.
          </p>
          <CallsTable rows={OPENAIRE_CALLS} />
        </div>

        <div className="space-y-3">
          <h3 className="text-lg font-semibold">Deal registers</h3>
          <p className="max-w-prose">
            Two independent harvests feed one merged deal register. The openaccess.nl scraper reads
            the deal overview page, then each publisher page, then each deal page. It sends one
            request at a time, and it stores every HTML page before parsing it. The JCT job reads
            the published index sheet, and then one CSV per agreement. It waits a random 0.5 to 1.5
            seconds between downloads, because Google throttles rapid fetching.
          </p>
          <p className="max-w-prose">
            The reconcile job merges the two sources. It pairs an openaccess.nl row with a JCT row
            when the publisher names match ignoring case and the deal durations overlap, and it
            treats rows with the same ESAC id as the same agreement. The merge compares one field,
            the deal status. When the two sources disagree on status, the row gets{" "}
            <Code>needs_curation</Code> set, with both values in the reason. The other JCT fields,
            the ESAC id, the data URL, the corresponding-authors-only flag, and the last-reviewed
            date, are copied over as they are. Rows for foreign consortium partners never merge.
            Deals an admin removed stay excluded, and <Code>manual_overrides</Code> are reapplied
            after every run. A final pass resolves each deal journal&apos;s coverage ISSN to its
            ISSN-L through <Code>issn_map</Code> and flags the rows it cannot resolve.
          </p>
          <CallsTable rows={DEAL_CALLS} />
        </div>

        <div className="space-y-3">
          <h3 className="text-lg font-semibold">OpenAPC, DOAJ, Scimago</h3>
          <p className="max-w-prose">
            The OpenAPC job downloads five CSV files from the project&apos;s GitHub raw storage,
            keeps landing copies, and rebuilds two tables by replacing their contents. The tables
            are <Code>journal_apc_aggregates</Code>, one row per ISSN-L and period, and{" "}
            <Code>apc_evidence</Code> for the home institution. The job then refreshes{" "}
            <Code>journals.latest_apc_euro</Code>. The DOAJ job downloads the site&apos;s full
            journal CSV once and stamps journals with <Code>is_in_doaj</Code>, the DOAJ APC facts,
            and the DOAJ homepage, matching by ISSN. An open-access journal that DOAJ does not list
            gets <Code>is_in_doaj</Code> set to false explicitly. The Scimago job unpacks the seed
            CSVs kept in the repository, because the Scimago site blocks scripted downloads. It
            writes <Code>scimagojr_metrics</Code> rows per ISSN-L and year, and stamps{" "}
            <Code>journals.in_scimago</Code> and <Code>latest_quartile</Code>.
          </p>
          <CallsTable rows={CSV_CALLS} />
        </div>

        <div className="space-y-3">
          <h3 className="text-lg font-semibold">Identity resolution rules</h3>
          <p className="max-w-prose">
            Work identity follows simple rules. An exact DOI match confirms the row immediately,
            with matched_by <Code>doi</Code> and confidence 1.0. Title matching against OpenAIRE
            scores trigram similarity, needs at least 0.82, keeps only the best-scoring work per
            record, and always writes the row as <Code>candidate</Code> for a person to review. It
            never writes confirmed. A 404 from Crossref or OpenAlex writes <Code>missing</Code>,
            which means nothing was found, not that confidence was low. The only other way a row
            becomes <Code>confirmed</Code> is an admin flipping it in review, and harvest writes
            never overwrite that decision.
          </p>
          <p className="max-w-prose">
            Author identity checks five rungs in order, and each rung writes its own fixed
            confidence. An exact ORCID match scores 1.0. Equal normalized full names score 0.9.
            Matching initials forms score 0.8. A family name that is unique among the work&apos;s
            Pure authors scores 0.7. Fuzzy name similarity of at least 0.92 by Levenshtein ratio
            scores 0.6. A rung must find exactly one unambiguous hit. When a rung is ambiguous, the
            next rung tries.
          </p>
        </div>
      </section>

      <section id="scheduling" className="space-y-4">
        <h2 className="mt-2 text-2xl font-semibold">Scheduling</h2>
        <p className="max-w-prose">
          Nothing runs on a schedule. The only automatic invocation is the compose bootstrap
          service. Every <Code>docker compose up</Code> runs the alembic migrations and{" "}
          <Code>bootstrap.py</Code> before the backend starts, and auto mode exits in seconds once
          the plan-completion marker shows a completed run, so restarts are cheap.{" "}
          <Code>JB_BOOTSTRAP=always</Code> forces a full rerun, and repair mode reruns from one
          step. Any other fresh data arrives only when someone starts a job by hand. The manual
          table below is never run automatically.
        </p>
        <p className="max-w-prose">
          Two serving-side loops run continuously, and neither harvests anything. A nightly job
          nulls usage-event IP addresses older than 90 days, and an in-process loop refreshes deal
          coverage flags. For live freshness, <Code>GET /api/v1/{"{code}"}/meta/freshness</Code>{" "}
          reports each source&apos;s harvest state, which is the source, entity type, filter set,
          status, last finished time, and stats. It also reports the newest row timestamps for the
          main serving tables, and the degraded-source registry.
        </p>
        <p className="max-w-prose">
          The runbook below maps every bootstrap step to its script. The steps, scripts, and
          dependencies come from the generated plan, and institution-band steps run with{" "}
          <Code>--institution CODE</Code>.
        </p>
        <DataTable
          head={["Step", "Script", "Band", "Depends on"]}
          rows={PLAN.steps.map((step) => [
            step.id,
            `jobs/${step.script}`,
            step.band,
            step.deps.length > 0 ? step.deps.join(", ") : "none",
          ])}
        />
      </section>

      <section id="manual" className="space-y-4">
        <h2 className="mt-2 text-2xl font-semibold">What bootstrap does not fetch</h2>
        <p className="max-w-prose">
          These jobs live in the repository, and the bootstrap plan never calls them. Some repair
          one bad run. Some backfill data the pipeline does not cover. Some are development checks.
          A fresh deployment works without them until someone runs them by hand.
        </p>
        <DataTable head={["Job", "What it does", "Writes"]} rows={MANUAL_JOBS} />
      </section>

      <section id="config" className="space-y-4">
        <h2 className="mt-2 text-2xl font-semibold">Configuration</h2>
        <p className="max-w-prose">
          All configuration lives in environment variables that start with <Code>JB_</Code>. The
          first <Code>institutions</Code> row is also seeded from them. Migration 0019 inserts the
          default row when the database upgrades, and <Code>ensure_home_institution</Code>
          re-derives the same fields on the first harvest by matching on the ROR id. It fills the
          code, which is the lowercased <Code>JB_INSTITUTION_CODE</Code>, plus the names, the Pure
          OAI URL, the OpenAIRE org id, and the data window. To onboard another institution, create
          one <Code>institutions</Code> row and run <Code>bootstrap --institution CODE</Code>.
        </p>
        <DataTable
          head={["Variable", "Purpose"]}
          rows={[
            ["JB_DATABASE_URL", "The main Postgres connection string, using the asyncpg driver."],
            [
              "JB_UT_METADATA_DSN",
              "Read-only connection to the previous platform's Postgres. Without it, the authors job skips its ut-metadata source.",
            ],
            [
              "JB_OPENALEX_API_KEY or OPENALEX_API_KEY",
              "OpenAlex API key. Without a key, runs share the smaller keyless budget.",
            ],
            [
              "JB_CONTACT_EMAIL",
              "Contact email sent with requests, so Crossref and OpenAlex can identify the client.",
            ],
            [
              "JB_JISC_API_KEY",
              "API key for the Jisc Open Policy Finder, used by the manual Jisc jobs.",
            ],
            [
              "JB_DATA_WINDOW_START / _END",
              "The publication-year window the harvest covers. The start defaults to 2020, and an empty end means open ended. The window sets the Pure OAI year sets and the OpenAlex date filters.",
            ],
            [
              "JB_INSTITUTION_CODE / _NAME / _SHORT / _ROR",
              "The hosted institution's identity. The code may contain lowercase letters, digits, and hyphens.",
            ],
            [
              "JB_OPENAIRE_ORG_ID",
              "The institution's OpenAIRE organization id. It cannot be derived from the ROR id, and every institution other than the default needs one.",
            ],
            ["JB_PURE_OAI_BASE_URL", "The Pure OAI-PMH endpoint. Requests are anonymous."],
            [
              "JB_LANDING_DIR",
              "Where downloaded files are kept permanently. The default is landing/.",
            ],
            ["JB_ADMIN_PASSWORD", "The admin panel password. An empty value disables the panel."],
          ]}
        />
      </section>

      <section id="storage" className="space-y-4">
        <h2 className="mt-2 text-2xl font-semibold">How data is stored</h2>
        <p className="max-w-prose">
          Every harvested payload is stored twice, first as raw bytes and then as a parsed record.
          The download helper writes the bytes under <Code>landing/</Code> and adds a{" "}
          <Code>raw_files</Code> row. An ingest session then stores the parsed payload in{" "}
          <Code>source_records</Code>, and each record carries a SHA-256 hash of its content
          together with the source, entity type, and source key. When a re-harvest produces
          identical content, the job inserts nothing. When the content changed, the job adds a new
          version. Old versions are never deleted, so this history grows without limit. The
          normalized tables, such as journals, works, openalex_works, deals, the Pure tables, and
          the Jisc tables, are rebuilt from these stored copies. Because the copies are kept, every
          job can run again and reach the same result.
        </p>
        <p className="max-w-prose">
          A third layer precomputes the values the site reads on every page.{" "}
          <Code>journal_flags</Code> holds one row per journal per hosted institution. The layer
          also fills <Code>works_2020_plus</Code>, <Code>latest_apc_euro</Code>,{" "}
          <Code>publisher_canonical</Code>, <Code>oa_status_observed</Code>, the stored{" "}
          <Code>search_vector</Code> column, and the embedding vectors. Every run is recorded in{" "}
          <Code>harvest_runs</Code> and <Code>harvest_state</Code>, and every finished run,
          completed or failed, bumps <Code>cache_epoch</Code>, the single-row table that keys the
          site&apos;s in-process caches. A run bumps the epoch even when it fails, because a run
          commits its data page by page, and those pages can change what the site serves before the
          run closes. The facet and snapshot caches live for 24 hours and check this epoch on every
          read. The refresh jobs for the precomputed values bump the epoch directly as well.
        </p>
        <p className="max-w-prose">
          The site writes some tables itself, without any harvest. <Code>usage_events</Code> holds
          batched page views, searches, and errors. A nightly job nulls the raw IP addresses after
          90 days, and it keeps the rows and their country codes. <Code>feedback_items</Code> keeps
          the reporter&apos;s search state. <Code>doc_edits</Code> are admin edits applied over the
          served documents. <Code>manual_overrides</Code> are admin corrections that are reapplied
          after every harvest. <Code>author_identities</Code> and <Code>work_identity</Code> hold
          review decisions. <Code>status_changes</Code> is an append-only audit log.
        </p>
        <StorageFlow />
      </section>

      <section id="database" className="space-y-4">
        <h2 className="mt-2 text-2xl font-semibold">Database reference</h2>
        <p className="max-w-prose">
          {tableCount} tables and {columnCount} columns, generated from the live database on{" "}
          {schema.generatedAt} by <Code>backend/scripts/dump_db_schema.py</Code>. The
          alembic_version bookkeeping table is excluded. After a schema change, regenerate the file
          with this command.
        </p>
        <p className="max-w-prose font-mono text-xs break-all">
          cd backend &amp;&amp; uv run python scripts/dump_db_schema.py --dsn &lt;read-only dsn&gt;{" "}
          --out ../frontend/lib/data-pipeline-schema.json
        </p>
        <Card className="p-4">
          <DomainMap />
        </Card>
        <p className="text-sm text-[var(--muted-foreground)]">
          Most tables also carry an institution_id foreign key into institutions. Those{" "}
          {institutionFkCount} edges are left out of the map so it stays readable.
        </p>
        <DbReference />
        <p className="text-sm text-[var(--muted-foreground)]">
          {tableCount} tables, {columnCount} columns
        </p>
      </section>

      <section id="serving" className="space-y-4">
        <h2 className="mt-2 text-2xl font-semibold">How the site serves this data</h2>
        <p className="max-w-prose">
          Journal search runs every listing through one shared query, <Code>base_query</Code> in{" "}
          <Code>services/search/query.py</Code>. The query joins each journal to the
          institution&apos;s <Code>journal_flags</Code> row. It keeps journal-type venues with more
          than 3 works in the data window, and it keeps every other venue type with at least one
          institution work. Journals marked <Code>browse_excluded</Code> are never served. Relevance
          ranking uses three signals, in this order. A match on the title prefix ranks highest, the
          Postgres full-text rank comes next, and a small works count bonus breaks ties. Facets run
          over the same filtered set of journals and are cached for 24 hours, keyed on the cache
          epoch. The journal detail page assembles the journal row, its deal coverage, its per-year
          institution stats from both the Pure canon and OpenAlex, Scimago quartiles, APC aggregates
          and evidence, the raw venue record, and the works stored in <Code>openalex_works</Code>.
        </p>
        <p className="max-w-prose">
          The journal&apos;s <Code>oa_type</Code> is computed at query time and never stored. The
          rules below apply in order, and the first match wins.
        </p>
        <OaRules />
        <p className="max-w-prose">
          A missing flag is not treated as false. A NULL <Code>doaj_in_doaj</Code> means the DOAJ
          sweep never judged that journal. Work-level <Code>oa_status</Code> works differently. The
          harvest stores it, and the stored value comes from a fixed six-value vocabulary. The
          funder fit tiers build on <Code>oa_type</Code> and the Jisc green-route columns, which say
          whether a submitted, accepted, or published version may be posted, and after how many
          embargo months. One SQL expression computes the tiers, and the same expression is mirrored
          in Python.
        </p>
        <p className="max-w-prose">
          Journals are embedded as 384-dimension vectors built from the cleaned title, the top five
          topics, and the titles of up to three of the journal&apos;s most-cited works. The model is
          BAAI/bge-small-en-v1.5, running locally on CPU through fastembed and ONNX. A pgvector HNSW
          index serves similar-journal lists in three scopes, the institution, the deals, and
          everything, and it also serves semantic search. Author recommendations average the vectors
          of an author&apos;s venues, weighted by work counts. The embeddings step runs once, after
          every institution&apos;s stats step, and it is the last bootstrap step.
        </p>
        <p className="max-w-prose">
          The API contract is generated, not hand-written. <Code>openapi.json</Code> at the
          repository root is dumped from the routes, CI fails when it drifts, and the
          frontend&apos;s <Code>lib/api-types.ts</Code> is generated from it.
        </p>
      </section>
    </div>
  );
}
