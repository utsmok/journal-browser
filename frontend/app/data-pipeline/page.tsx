import type { Metadata } from "next";
import type { ReactNode } from "react";

import { getTranslations } from "next-intl/server";

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

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("dataPipeline");
  return {
    title: t("metadata.title"),
    description: t("metadata.description"),
  };
}

const tableCount = schema.tables.length;
const columnCount = schema.tables.reduce((sum, table) => sum + table.columns.length, 0);
const institutionFkCount = schema.tables.reduce(
  (sum, table) => sum + table.foreignKeys.filter((fk) => fk.toTable === "institutions").length,
  0,
);

// [step, message key for the request shape, message key for the writes]
const OPENALEX_CALLS: [string, string, string][] = [
  ["journals", "calls.openalexJournalsRequest", "calls.openalexJournalsWrites"],
  ["publishers", "calls.openalexPublishersRequest", "calls.openalexPublishersWrites"],
  ["oa-colors", "calls.openalexOaColorsRequest", "calls.openalexOaColorsWrites"],
  ["stats", "calls.openalexStatsRequest", "calls.openalexStatsWrites"],
  ["enrich", "calls.openalexEnrichRequest", "calls.openalexEnrichWrites"],
  ["author-ids", "calls.openalexAuthorIdsRequest", "calls.openalexAuthorIdsWrites"],
];

const CROSSREF_CALLS: [string, string, string][] = [
  ["enrich", "calls.crossrefEnrichRequest", "calls.crossrefEnrichWrites"],
];

const PURE_CALLS: [string, string, string][] = [
  ["pure", "calls.pureWorksRequest", "calls.pureWorksWrites"],
  ["pure-cerif", "calls.pureCerifRequest", "calls.pureCerifWrites"],
  ["pure-entities", "calls.pureEntitiesRequest", "calls.pureEntitiesWrites"],
];

const OPENAIRE_CALLS: [string, string, string][] = [
  ["openaire", "calls.openaireRequest", "calls.openaireWrites"],
];

const DEAL_CALLS: [string, string, string][] = [
  ["deals-openaccess-nl", "calls.dealsOpenaccessRequest", "calls.dealsOpenaccessWrites"],
  ["deals-jct", "calls.dealsJctRequest", "calls.dealsJctWrites"],
  ["deals-reconcile", "calls.dealsReconcileRequest", "calls.dealsReconcileWrites"],
  ["deals-issn-l", "calls.dealsIssnLRequest", "calls.dealsIssnLWrites"],
];

const CSV_CALLS: [string, string, string][] = [
  ["openapc", "calls.openapcRequest", "calls.openapcWrites"],
  ["doaj", "calls.doajRequest", "calls.doajWrites"],
  ["scimagojr", "calls.scimagoRequest", "calls.scimagoWrites"],
];

// [job, message key for what it does, message key for the writes]
const MANUAL_JOBS: [string, string, string][] = [
  ["harvest_jisc + normalize_jisc", "manual.harvestJiscWhat", "manual.harvestJiscWrites"],
  [
    "harvest_openalex_funders",
    "manual.harvestOpenAlexFundersWhat",
    "manual.harvestOpenAlexFundersWrites",
  ],
  [
    "harvest_openaire_funders",
    "manual.harvestOpenaireFundersWhat",
    "manual.harvestOpenaireFundersWrites",
  ],
  ["harvest_work_funders", "manual.harvestWorkFundersWhat", "manual.harvestWorkFundersWrites"],
  ["import_pure_export", "manual.importPureExportWhat", "manual.importPureExportWrites"],
  ["harvest_pure_portal", "manual.harvestPurePortalWhat", "manual.harvestPurePortalWrites"],
  [
    "harvest_portal_persons",
    "manual.harvestPortalPersonsWhat",
    "manual.harvestPortalPersonsWrites",
  ],
  ["import_utmetadata_raw", "manual.importUtmetadataRawWhat", "manual.importUtmetadataRawWrites"],
  [
    "import_utmetadata_works",
    "manual.importUtmetadataWorksWhat",
    "manual.importUtmetadataWorksWrites",
  ],
  [
    "ingest_emerald_contract",
    "manual.ingestEmeraldContractWhat",
    "manual.ingestEmeraldContractWrites",
  ],
  ["enrich_usage_geo", "manual.enrichUsageGeoWhat", "manual.enrichUsageGeoWrites"],
  ["verify_utmetadata", "manual.verifyUtmetadataWhat", "manual.verifyUtmetadataWrites"],
  ["funder_link_matrix", "manual.funderLinkMatrixWhat", "manual.funderLinkMatrixWrites"],
];

// [message key of the section heading, anchor id]
const TOC: [string, string][] = [
  ["sources.heading", "sources"],
  ["dag.heading", "dag"],
  ["jobs.heading", "jobs"],
  ["scheduling.heading", "scheduling"],
  ["manual.heading", "manual"],
  ["config.heading", "config"],
  ["storage.heading", "storage"],
  ["database.heading", "database"],
  ["serving.heading", "serving"],
];

function Code({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-[var(--muted)] px-1 font-mono text-[0.875em]">{children}</code>
  );
}

function CallsTable({ head, rows }: { head: string[]; rows: [string, string, string][] }) {
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

export default async function DataPipelinePage() {
  const t = await getTranslations("dataPipeline");
  const code = (chunks: ReactNode) => <Code>{chunks}</Code>;
  return (
    <div className="mx-auto max-w-screen-2xl space-y-10 px-4 py-10">
      <header className="space-y-3">
        <h1 className="text-3xl font-bold">{t("intro.title")}</h1>
        <p className="max-w-prose">{t.rich("intro.lead", { code })}</p>
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
          {TOC.map(([labelKey, id]) => (
            <li key={id}>
              <a href={`#${id}`} className="text-[var(--primary-text)] hover:underline">
                {t(labelKey)}
              </a>
            </li>
          ))}
        </ul>
      </header>

      <section id="sources" className="space-y-4">
        <h2 className="mt-2 text-2xl font-semibold">{t("sources.heading")}</h2>
        <p className="max-w-prose">{t("sources.lead")}</p>
        <DataTable
          head={[
            t("sources.headSource"),
            t("sources.headProvides"),
            t("sources.headTransport"),
            t("sources.headUsedBy"),
          ]}
          rows={SOURCES.map((source) => [
            source.name,
            t(`sources.${source.id}Provides`),
            t(`sources.${source.id}Transport`),
            t(`sources.${source.id}UsedBy`),
          ])}
        />
      </section>

      <section id="dag" className="space-y-4">
        <h2 className="mt-2 text-2xl font-semibold">{t("dag.heading")}</h2>
        <p className="max-w-prose">{t.rich("dag.planLead", { code })}</p>
        <p className="max-w-prose">{t.rich("dag.clientLead", { code })}</p>
        <p className="max-w-prose">{t.rich("dag.modesLead", { code })}</p>
        <Card className="p-4">
          <DagDiagram />
        </Card>
        <p className="text-sm text-[var(--muted-foreground)]">{t("dag.perCodeCaption")}</p>
        <p className="max-w-prose text-sm text-[var(--muted-foreground)]">
          {t.rich("dag.generatedCaption", { code, date: PLAN.generatedAt })}
        </p>
        <details className="max-w-prose text-sm">
          <summary className="cursor-pointer text-[var(--muted-foreground)]">
            {t("dag.allEdges", {
              count: PLAN.steps.reduce((count, step) => count + step.deps.length, 0),
            })}
          </summary>
          <p className="mt-2 leading-6">
            {PLAN.steps.flatMap((step) => step.deps.map((dep) => `${dep} → ${step.id}`)).join("; ")}
          </p>
        </details>
      </section>

      <section id="jobs" className="space-y-6">
        <h2 className="mt-2 text-2xl font-semibold">{t("jobs.heading")}</h2>

        <div className="space-y-3">
          <h3 className="text-lg font-semibold">OpenAlex</h3>
          <p className="max-w-prose">{t.rich("jobs.openalexIntro", { code })}</p>
          <p className="max-w-prose">{t.rich("jobs.openalexInstitutionJobs", { code })}</p>
          <CallsTable
            head={[t("calls.headStep"), t("calls.headRequest"), t("calls.headWrites")]}
            rows={OPENALEX_CALLS}
          />
        </div>

        <div className="space-y-3">
          <h3 className="text-lg font-semibold">Crossref</h3>
          <p className="max-w-prose">{t.rich("jobs.crossrefIntro", { code })}</p>
          <CallsTable
            head={[t("calls.headStep"), t("calls.headRequest"), t("calls.headWrites")]}
            rows={CROSSREF_CALLS}
          />
        </div>

        <div className="space-y-3">
          <h3 className="text-lg font-semibold">Pure OAI-PMH</h3>
          <p className="max-w-prose">{t.rich("jobs.pureProtocol", { code })}</p>
          <p className="max-w-prose">{t.rich("jobs.purePasses", { code })}</p>
          <CallsTable
            head={[t("calls.headStep"), t("calls.headRequest"), t("calls.headWrites")]}
            rows={PURE_CALLS}
          />
        </div>

        <div className="space-y-3">
          <h3 className="text-lg font-semibold">OpenAIRE</h3>
          <p className="max-w-prose">{t.rich("jobs.openaireIntro", { code })}</p>
          <CallsTable
            head={[t("calls.headStep"), t("calls.headRequest"), t("calls.headWrites")]}
            rows={OPENAIRE_CALLS}
          />
        </div>

        <div className="space-y-3">
          <h3 className="text-lg font-semibold">{t("jobs.dealRegistersHeading")}</h3>
          <p className="max-w-prose">{t.rich("jobs.dealsHarvests", { code })}</p>
          <p className="max-w-prose">{t.rich("jobs.dealsMerge", { code })}</p>
          <CallsTable
            head={[t("calls.headStep"), t("calls.headRequest"), t("calls.headWrites")]}
            rows={DEAL_CALLS}
          />
        </div>

        <div className="space-y-3">
          <h3 className="text-lg font-semibold">OpenAPC, DOAJ, Scimago</h3>
          <p className="max-w-prose">{t.rich("jobs.openapcDoajScimagoIntro", { code })}</p>
          <CallsTable
            head={[t("calls.headStep"), t("calls.headRequest"), t("calls.headWrites")]}
            rows={CSV_CALLS}
          />
        </div>

        <div className="space-y-3">
          <h3 className="text-lg font-semibold">{t("jobs.identityRulesHeading")}</h3>
          <p className="max-w-prose">{t.rich("jobs.identityWorkIntro", { code })}</p>
          <p className="max-w-prose">{t.rich("jobs.identityAuthorIntro", { code })}</p>
        </div>
      </section>

      <section id="scheduling" className="space-y-4">
        <h2 className="mt-2 text-2xl font-semibold">{t("scheduling.heading")}</h2>
        <p className="max-w-prose">{t.rich("scheduling.lead", { code })}</p>
        <p className="max-w-prose">{t.rich("scheduling.loopsLead", { code })}</p>
        <p className="max-w-prose">{t.rich("scheduling.runbookLead", { code })}</p>
        <DataTable
          head={[
            t("scheduling.headStep"),
            t("scheduling.headScript"),
            t("scheduling.headBand"),
            t("scheduling.headDeps"),
          ]}
          rows={PLAN.steps.map((step) => [
            step.id,
            `jobs/${step.script}`,
            step.band,
            step.deps.length > 0 ? step.deps.join(", ") : t("scheduling.depsNone"),
          ])}
        />
      </section>

      <section id="manual" className="space-y-4">
        <h2 className="mt-2 text-2xl font-semibold">{t("manual.heading")}</h2>
        <p className="max-w-prose">{t("manual.lead")}</p>
        <DataTable
          head={[t("manual.headJob"), t("manual.headWhat"), t("manual.headWrites")]}
          rows={MANUAL_JOBS.map(([job, whatKey, writesKey]) => [job, t(whatKey), t(writesKey)])}
        />
      </section>

      <section id="config" className="space-y-4">
        <h2 className="mt-2 text-2xl font-semibold">{t("config.heading")}</h2>
        <p className="max-w-prose">{t.rich("config.lead", { code })}</p>
        <DataTable
          head={[t("config.headVariable"), t("config.headPurpose")]}
          rows={[
            ["JB_DATABASE_URL", t("config.purposeDatabaseUrl")],
            ["JB_UT_METADATA_DSN", t("config.purposeUtMetadataDsn")],
            ["JB_OPENALEX_API_KEY or OPENALEX_API_KEY", t("config.purposeOpenAlexApiKey")],
            ["JB_CONTACT_EMAIL", t("config.purposeContactEmail")],
            ["JB_JISC_API_KEY", t("config.purposeJiscApiKey")],
            ["JB_DATA_WINDOW_START / _END", t("config.purposeDataWindow")],
            ["JB_INSTITUTION_CODE / _NAME / _SHORT / _ROR", t("config.purposeInstitutionIdentity")],
            ["JB_OPENAIRE_ORG_ID", t("config.purposeOpenaireOrgId")],
            ["JB_PURE_OAI_BASE_URL", t("config.purposePureOaiUrl")],
            ["JB_LANDING_DIR", t("config.purposeLandingDir")],
            ["JB_ADMIN_PASSWORD", t("config.purposeAdminPassword")],
          ]}
        />
      </section>

      <section id="storage" className="space-y-4">
        <h2 className="mt-2 text-2xl font-semibold">{t("storage.heading")}</h2>
        <p className="max-w-prose">{t.rich("storage.leadRaw", { code })}</p>
        <p className="max-w-prose">{t.rich("storage.leadDerived", { code })}</p>
        <p className="max-w-prose">{t.rich("storage.leadSiteWrites", { code })}</p>
        <StorageFlow />
      </section>

      <section id="database" className="space-y-4">
        <h2 className="mt-2 text-2xl font-semibold">{t("database.heading")}</h2>
        <p className="max-w-prose">
          {t.rich("database.lead", {
            code,
            tables: tableCount,
            columns: columnCount,
            date: schema.generatedAt,
          })}
        </p>
        <p className="max-w-prose font-mono text-xs break-all">
          cd backend &amp;&amp; uv run python scripts/dump_db_schema.py --dsn &lt;read-only dsn&gt;{" "}
          --out ../frontend/lib/data-pipeline-schema.json
        </p>
        <Card className="p-4">
          <DomainMap />
        </Card>
        <p className="text-sm text-[var(--muted-foreground)]">
          {t("database.fkNote", { count: institutionFkCount })}
        </p>
        <DbReference />
        <p className="text-sm text-[var(--muted-foreground)]">
          {t("database.countSummary", { tables: tableCount, columns: columnCount })}
        </p>
      </section>

      <section id="serving" className="space-y-4">
        <h2 className="mt-2 text-2xl font-semibold">{t("serving.heading")}</h2>
        <p className="max-w-prose">{t.rich("serving.searchLead", { code })}</p>
        <p className="max-w-prose">{t.rich("serving.oaTypeLead", { code })}</p>
        <OaRules />
        <p className="max-w-prose">{t.rich("serving.oaStatusLead", { code })}</p>
        <p className="max-w-prose">{t.rich("serving.embeddingsLead", { code })}</p>
        <p className="max-w-prose">{t.rich("serving.apiContractLead", { code })}</p>
      </section>
    </div>
  );
}
