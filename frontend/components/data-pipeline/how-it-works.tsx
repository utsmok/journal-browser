import { ChevronDown } from "lucide-react";

import { Card } from "@/components/ui/card";

type Pillar = {
  step: string;
  title: string;
  body: string;
};

const PILLARS: Pillar[] = [
  {
    step: "1",
    title: "Open sources only",
    body: "All data comes from public sources, including Pure OAI-PMH, OpenAlex, DOAJ, OpenAIRE, Crossref, openaccess.nl, JCT, OpenAPC, Scimago, and Jisc Open Policy Finder. The pipeline stores each raw file before parsing it.",
  },
  {
    step: "2",
    title: "Conservative matching",
    body: "Only exact identifiers such as DOI, ORCID, ISSN-L, and ROR confirm a match automatically. Authors are matched per shared publication with guards against namesakes, and uncertain matches wait for human review.",
  },
  {
    step: "3",
    title: "Fixed conflict rules",
    body: "When two sources disagree, the browser does not blend them silently. DOAJ decides gold versus diamond, Pure defines institutional publications, and OpenAlex breaks ties over OpenAIRE for work-level open access status.",
  },
  {
    step: "4",
    title: "Saved curator edits",
    body: "Manual deal fixes, excluded journal titles, and admin identity decisions are stored in separate tables and re-applied after every harvest.",
  },
];

type TopicGuide = {
  id: string;
  title: string;
  summary: string;
  steps: string[];
  details: { label: string; text: string }[];
};

const TOPICS: TopicGuide[] = [
  {
    id: "how-authors",
    title: "Author publications and works not in Pure",
    summary:
      "Pure OAI-PMH provides the canonical list of publications for an author. OpenAlex adds citations and feeds the separate list of works that may be missing from Pure.",
    steps: [
      "The pipeline harvests publications, persons, and organisation units from Pure OAI-PMH.",
      "It confirms institutional affiliation by walking the Pure organisation tree up to the institution ROR.",
      "It removes 17 non-journal work types from counts and lists, while keeping book chapters so conference proceedings remain included.",
      "It matches Pure authors to OpenAlex and OpenAIRE per shared publication, checking ORCID first and then exact name or initials.",
    ],
    details: [
      {
        label: "Filtered work types",
        text: "Preprints, posted content, working papers, books, monographs, datasets, software, errata, peer reviews, paratext, reference entries, book reviews, retractions, libguides, standards, supplementary materials, and items typed as other are excluded from every count and list. Book chapters and book parts stay in because conference proceedings often appear under those types.",
      },
      {
        label: "Guards against wrong author matches",
        text: "The matcher never merges people globally by name alone. For CJK surnames, surname-only and fuzzy matching are disabled. Co-authorship-inferred ORCIDs from OpenAIRE (orcid_pending) are ignored. Multiple OpenAlex profiles link to one person automatically only when they never co-occur on the same paper and share at most one ORCID.",
      },
      {
        label: "Excluding Pure from its own gap list",
        text: "The OpenAlex-only list drops works whose primary OpenAlex source is a repository, such as Zenodo or the university's own Pure system. Book chapters are grouped under their parent book.",
      },
    ],
  },
  {
    id: "how-journals",
    title: "Journal catalogue, search, and open access types",
    summary:
      "OpenAlex supplies about 177,700 venues, filtered to active journals and classified at query time into diamond, gold, hybrid, unknown open access, or subscription.",
    steps: [
      "The harvest collects all OpenAlex sources and groups them by canonical ISSN-L.",
      "Search shows journals with more than 3 works in the institution's year window, plus any book series or conference where the institution publishes.",
      "Unused venues with proceedings words in their title and ISSNs on the admin ignore list are hidden from browse results.",
      "Each query calculates open access type live from DOAJ, OpenAPC, OpenAIRE, recent work samples, and active deals.",
    ],
    details: [
      {
        label: "How open access type is chosen",
        text: "The query checks six rules in order and takes the first match. First, open access evidence with any APC charge marks gold, so observed OpenAPC payments override a no-APC claim. Second, DOAJ listing with no APC, or an OpenAIRE diamond flag, marks diamond. Third, the modal open access color of 20 recent works applies when it is gold, diamond, or hybrid. Fourth, an active institutional deal marks hybrid. Fifth, open access evidence with no fee data marks open access with unknown model. Sixth, all other journals are marked subscription.",
      },
      {
        label: "Search ranking",
        text: "Keyword search combines text relevance with the institution's own publication count, so journals where local researchers publish rank above same-named titles with no local works. Queries with zero exact hits fall back to trigram fuzzy matching.",
      },
    ],
  },
  {
    id: "how-deals",
    title: "Open access deals, caps, and publishers",
    summary:
      "openaccess.nl is the canonical source for Dutch deal terms and caps. JCT/ESAC supplies machine-readable journal lists, and manual edits survive refreshes.",
    steps: [
      "The scraper reads openaccess.nl pages for deal existence, dates, terms, caps, and contract PDFs.",
      "The JCT job imports cOAlition S agreement sheets for ESAC identifiers and journal ISSN lists.",
      "Reconciliation merges duplicate rows by page URL and reapplies manual overrides and excluded journal tombstones.",
      "OpenAlex publisher lineage groups sub-imprints under parent publishers and flags journals that changed publisher after signing.",
    ],
    details: [
      {
        label: "Conflicts and curation",
        text: "openaccess.nl takes precedence for deal existence and terms, and absence from JCT never removes a local deal such as UT's ACM agreement. Ambiguous cap text sets a curation flag instead of guessing from PDFs. After the pipeline detected that JCT linked Emerald to Elsevier's sheet, all 311 Emerald titles were rebuilt from the signed contract.",
      },
      {
        label: "Multiple universities on one instance",
        text: "Shared deals are stored once. Each university links only the agreements it joins and can keep its own journal list override or exclusions without changing other universities.",
      },
    ],
  },
  {
    id: "how-apc",
    title: "APC and publication cost data",
    summary:
      "Displayed prices combine declared publisher list prices in OpenAlex with actual fees reported by institutions to OpenAPC.",
    steps: [
      "The display checks OpenAlex list prices first, preferring EUR, then USD, then the first listed currency.",
      "Non-EUR list prices convert to euros at the January 1 ECB exchange rate for the current year.",
      "If no list price exists, the display shows the observed OpenAPC euro range across the two newest reporting periods.",
      "Journal detail pages also display DOAJ declared maximum APCs separately with caveats.",
    ],
    details: [
      {
        label: "Why sorting uses the period maximum",
        text: "OpenAPC period averages blend multi-article discounts and waivers across institutions. Sorting by the newest period's highest reported price gives a more realistic upper bound for list costs.",
      },
    ],
  },
  {
    id: "how-green-funder",
    title: "Green open access policies and funder compliance",
    summary:
      "Self-archiving policies come verbatim from the Jisc Open Policy Finder and feed a five-rule funder compliance check.",
    steps: [
      "The harvest fetches publications, policies, publishers, repositories, and 202 funders from Jisc Open Policy Finder by exact ISSN.",
      "Normalization excludes routes where every fee entry requires payment, removing about 12,000 paid published-version routes.",
      "Each journal receives its freest allowed version, preferring submitted over accepted over published, while prohibition overrides all routes.",
      "Search facets, detail pages, and the journal finder run the same five-rule funder check.",
    ],
    details: [
      {
        label: "Funder compliance rules",
        text: "First, journals where the publisher prohibits archiving are marked not compliant. Second, gold and diamond journals are marked compliant. Third, journals covered by an active institutional deal are marked compliant for structured funder policies. Fourth, journals with a free green route are marked check embargo. Fifth, all remaining journals are marked not compliant. Funders with text-only policies show no automated tier.",
      },
    ],
  },
  {
    id: "how-works",
    title: "Journal publication counts and open access conflicts",
    summary:
      "Pure canonical counts and OpenAlex cross-checks stay separate so each number on a journal page has one clear source.",
    steps: [
      "Pure works link to journals through OpenAlex DOI lookup, then Crossref, and finally Pure CERIF ISSNs.",
      "Journal totals and publication tabs count active Pure works in the selected years, excluding the 17 non-journal types.",
      "OpenAlex institution-filter totals appear alongside Pure totals as a separate cross-check.",
      "Work-level open access status uses OpenAlex first (taking the most open record per DOI) and falls back to Pure rights when unmatched.",
    ],
    details: [
      {
        label: "OpenAlex versus OpenAIRE",
        text: "A 94-work ground-truth sample showed OpenAIRE (53.3%) and OpenAlex (44.8%) in a statistical tie. OpenAlex is used consistently for work-level open access status, and OpenAIRE's classification remains visible on the OpenAIRE comparison card.",
      },
      {
        label: "Works without a journal link",
        text: "About 60% of Pure records have no journal ISSN because they are dissertations, reports, or non-ISSN conference outputs. Journal statistics therefore read from pre-computed aggregate tables.",
      },
    ],
  },
  {
    id: "how-guided-finder",
    title: "Semantic search, similar journals, and the journal finder",
    summary:
      "A local CPU embedding model matches text to journals on the server without sending data to external AI services.",
    steps: [
      "Each journal is embedded from its cleaned title, its top five OpenAlex topics, and the titles of its three most cited works.",
      "Search queries and paper abstracts are encoded locally on CPU with bge-small-en-v1.5 and are never logged or stored.",
      "PostgreSQL pgvector retrieves the closest journals by cosine similarity.",
      "The journal finder ranks matching journals with fixed bonuses for diamond open access, active deals, gold open access within budget, and funder compliance.",
    ],
    details: [
      {
        label: "No generative AI",
        text: "Recommendations use deterministic vector similarity and structured policy rules over open datasets. The system cannot invent journals or deals, and every ranking factor is listed on the results screen.",
      },
    ],
  },
];

const SAFEGUARDS: [string, string][] = [
  [
    "DOAJ bulk CSV and MDPI fix",
    "The DOAJ search API caps results at 1,000 rows, and OpenAlex misses DOAJ flags for some open access journals such as MDPI Water. The pipeline downloads the full DOAJ CSV and combines OpenAlex is_oa with OpenAIRE diamond flags.",
  ],
  [
    "Jisc fee-only routes",
    "About 12,000 published-version routes in Jisc Open Policy Finder require an open access fee. Normalization marks those routes as fee-only so they do not appear as free green open access.",
  ],
  [
    "Pure excluded from its own gap list",
    "OpenAlex indexes Pure repositories as repository sources. The gap query drops repository-primary OpenAlex works so Pure records do not appear as missing from Pure.",
  ],
  [
    "Book chapters and LNCS",
    "Book chapters stay in publication counts because conference proceedings often use that type. In gap lists, chapters roll up under their parent book, and non-journal venues with local works such as LNCS remain searchable.",
  ],
  [
    "Author matching guards",
    "CJK surnames disable surname-only and fuzzy matching. OpenAIRE's inferred orcid_pending values are ignored, and multiple OpenAlex profiles link automatically only when they never co-occur on a work and share at most one ORCID.",
  ],
  [
    "Author topic weighting",
    "Mega-journals previously stamped generic neural-network topics onto hundreds of unrelated authors. Author topics are now weighted proportionally by each journal's per-topic counts at the subfield level.",
  ],
  [
    "Emerald contract and deal overrides",
    "When JCT linked the Dutch Emerald agreement to Elsevier's sheet, all 311 Emerald titles were rebuilt from the signed contract. Re-scrapes fold duplicate deal rows by URL and preserve manual overrides and excluded titles.",
  ],
  [
    "Publisher lineage and transfers",
    "Sub-imprints map to their parent publisher through OpenAlex lineage. Journals whose current publisher differs from their signed agreement appear as explicit deal discrepancies.",
  ],
];

export function HowItWorks() {
  return (
    <section id="how-each-view" className="scroll-mt-20 space-y-6">
      <div className="space-y-2">
        <h2 className="text-2xl font-bold tracking-tight">How the data is processed</h2>
        <p className="max-w-4xl text-sm leading-relaxed text-[var(--muted-foreground)]">
          This section explains how records are collected, matched, filtered, and reconciled across
          sources. Open any topic below to see the exact rules, or scroll down for the harvest jobs
          and database tables.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {PILLARS.map((p) => (
          <Card key={p.step} className="space-y-2 p-5">
            <div className="flex items-center gap-2.5">
              <span className="inline-flex size-6 shrink-0 items-center justify-center rounded-full bg-[var(--secondary)] text-xs font-bold text-[var(--secondary-foreground)]">
                {p.step}
              </span>
              <h3 className="text-sm font-semibold">{p.title}</h3>
            </div>
            <p className="text-sm leading-relaxed text-[var(--muted-foreground)]">{p.body}</p>
          </Card>
        ))}
      </div>

      <div className="space-y-3">
        {TOPICS.map((topic) => (
          <details
            key={topic.id}
            id={topic.id}
            className="group scroll-mt-20 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] shadow-sm"
          >
            <summary className="flex cursor-pointer list-none items-start justify-between gap-4 p-5 [&::-webkit-details-marker]:hidden">
              <div className="space-y-1">
                <h3 className="text-base font-semibold tracking-tight">{topic.title}</h3>
                <p className="text-sm text-[var(--muted-foreground)]">{topic.summary}</p>
              </div>
              <ChevronDown
                aria-hidden
                className="mt-1 size-4 shrink-0 text-[var(--muted-foreground)] transition-transform duration-150 group-open:rotate-180"
              />
            </summary>

            <div className="space-y-5 border-t border-[var(--border)] px-5 pb-5 pt-4">
              <ol className="grid grid-cols-1 gap-2.5 md:grid-cols-2 lg:grid-cols-4">
                {topic.steps.map((step, i) => (
                  <li
                    key={step}
                    className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--muted)] p-3 text-xs leading-relaxed"
                  >
                    <span className="mb-1 block font-semibold text-[var(--primary-text)]">
                      Step {i + 1}
                    </span>
                    <span>{step}</span>
                  </li>
                ))}
              </ol>

              <dl className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {topic.details.map((d) => (
                  <div key={d.label} className="space-y-1">
                    <dt className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                      {d.label}
                    </dt>
                    <dd className="text-sm leading-relaxed">{d.text}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </details>
        ))}

        <details
          id="how-safeguards"
          className="group scroll-mt-20 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] shadow-sm"
        >
          <summary className="flex cursor-pointer list-none items-start justify-between gap-4 p-5 [&::-webkit-details-marker]:hidden">
            <div className="space-y-1">
              <h3 className="text-base font-semibold tracking-tight">
                Data fixes and safeguards ({SAFEGUARDS.length})
              </h3>
              <p className="text-sm text-[var(--muted-foreground)]">
                Specific upstream data problems found during validation, including the Emerald JCT
                sheet mix-up, fee-only green open access routes, and Pure repository self-matches.
              </p>
            </div>
            <ChevronDown
              aria-hidden
              className="mt-1 size-4 shrink-0 text-[var(--muted-foreground)] transition-transform duration-150 group-open:rotate-180"
            />
          </summary>

          <div className="border-t border-[var(--border)] px-5 pb-5 pt-4">
            <dl className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {SAFEGUARDS.map(([title, desc]) => (
                <div
                  key={title}
                  className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--muted)] p-3.5"
                >
                  <dt className="text-sm font-semibold">{title}</dt>
                  <dd className="mt-1 text-xs leading-relaxed text-[var(--muted-foreground)]">
                    {desc}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </details>
      </div>
    </section>
  );
}
