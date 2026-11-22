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
    body: "Every figure comes from public sources (Pure OAI-PMH, OpenAlex, DOAJ, OpenAIRE, Crossref, openaccess.nl, JCT, OpenAPC, Scimago, Jisc OPF). Raw copies are archived before processing.",
  },
  {
    step: "2",
    title: "Conservative matching",
    body: "Only exact identifiers (DOI, ORCID, ISSN-L, ROR) auto-confirm unconditionally. Authors are matched per shared publication with guards against namesakes; uncertain matches wait for human review.",
  },
  {
    step: "3",
    title: "Explicit conflict rules",
    body: "When two sources disagree, we never blend them silently. Primary sources and tie-breakers are fixed (for example, DOAJ for Gold vs. Diamond; Pure for institutional works; OpenAlex over OpenAIRE on work OA color).",
  },
  {
    step: "4",
    title: "Curator edits stick",
    body: "Manual deal fixes, excluded titles, and admin identity decisions are stored separately and automatically re-applied after every automated harvest.",
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
    title: "Author publications & 'Not in Pure' gaps",
    summary:
      "Pure OAI-PMH is the canonical publication list; OpenAlex supplies citations and the separate list of papers that may be missing from Pure.",
    steps: [
      "Start with Pure OAI-PMH (persons, org units, publications)",
      "Confirm affiliation via org-tree closure to the institution ROR",
      "Filter out 17 non-journal types (keep book chapters for proceedings)",
      "Match authors per shared paper (ORCID → exact name → initials → safeguards)",
    ],
    details: [
      {
        label: "What is filtered out",
        text: "Preprints, posted-content, working papers, books, monographs, datasets, software, errata, peer reviews, paratext, reference entries, book reviews, retractions, libguides, standards, supplementary materials, and 'other' are excluded from counts and lists. Book chapters and book parts stay in because conference proceedings often appear there.",
      },
      {
        label: "Safeguards against false author matches",
        text: "Global name-only matching is never used. CJK surnames disable surname-only and fuzzy matching; OpenAIRE's inferred orcid_pending IDs are rejected; multiple OpenAlex profiles link as fragmentation twins only when they never co-occur on the same paper and share at most one ORCID.",
      },
      {
        label: "Why Pure's own records don't appear as 'missing'",
        text: "The OpenAlex-only gap list drops works whose primary OpenAlex source is a repository (such as Zenodo or the university's own Pure RIS) and groups book chapters under their parent book.",
      },
    ],
  },
  {
    id: "how-journals",
    title: "Journal catalogue, search & OA types",
    summary:
      "~177,700 OpenAlex venues filtered for active journals and classified live into Diamond, Gold, Hybrid, OA status unknown, or Subscription.",
    steps: [
      "Collect all OpenAlex sources normalized by canonical ISSN-L",
      "Keep active journals (>3 works in window) + non-journal venues your university uses (e.g. LNCS)",
      "Hide unused proceedings-titled venues and admin-ignored ISSNs",
      "Compute OA type live from DOAJ, OpenAPC, OpenAIRE, recent works, and active deals",
    ],
    details: [
      {
        label: "How OA type is decided (first match wins)",
        text: "1) OA evidence + any APC charge (DOAJ, OpenAPC, or OpenAlex list price) → Gold (real OpenAPC payments override a no-APC claim). 2) DOAJ with no APC, or OpenAIRE diamond flag → Diamond. 3) Modal OA color of 20 recent works (gold/diamond/hybrid). 4) Active institutional deal → Hybrid. 5) OA evidence without fee info → OA status unknown. 6) Everything else → Subscription.",
      },
      {
        label: "Search ranking",
        text: "Keyword search ranks by text relevance plus your university's own publication count so locally used titles beat obscure homonyms. Zero-hit queries automatically fall back to fuzzy spelling matches.",
      },
    ],
  },
  {
    id: "how-deals",
    title: "Open access deals, caps & publishers",
    summary:
      "openaccess.nl is the canonical source for Dutch deal terms and caps; JCT/ESAC provides machine-readable journal lists, with sticky local curation.",
    steps: [
      "Scrape openaccess.nl for deal existence, terms, caps, and contract PDFs",
      "Enrich with cOAlition S JCT/ESAC journal ISSN lists",
      "Fold duplicate rows by URL and re-apply manual overrides & excluded tombstones",
      "Map publisher imprints to parent publishers and flag publisher transfers",
    ],
    details: [
      {
        label: "Conflicts & curation",
        text: "openaccess.nl wins for deal existence and terms; JCT absence never erases a local deal (like UT's ACM deal). Ambiguous caps flag for human curation instead of auto-parsing PDFs. When JCT linked Emerald to Elsevier's sheet, all 311 Emerald titles were rebuilt from the signed contract.",
      },
      {
        label: "Multi-university scoping",
        text: "Shared agreements are stored once; each university links only the deals it participates in and can maintain local title overrides or exclusions without affecting other universities.",
      },
    ],
  },
  {
    id: "how-apc",
    title: "APC & publication cost evidence",
    summary:
      "Combines publisher list prices (EUR-converted) with real institutional payments reported to OpenAPC.",
    steps: [
      "Check OpenAlex declared list price (EUR → USD → first currency)",
      "Convert to EUR using the Jan 1 ECB exchange rate",
      "If no list price exists, fall back to OpenAPC observed min–max over the newest 2 periods",
      "Show DOAJ declared APC separately on detail pages with caveats",
    ],
    details: [
      {
        label: "Sorting convention",
        text: "When sorting by APC, OpenAPC fallback uses the newest period's highest observed single price rather than an average, avoiding understated costs from institutional discounts.",
      },
    ],
  },
  {
    id: "how-green-funder",
    title: "Green OA policies & funder compliance",
    summary:
      "Verbatim publisher self-archiving rules from Jisc Open Policy Finder paired with a 5-tier funder compliance engine.",
    steps: [
      "Harvest Jisc Open Policy Finder policies, publishers, and 202 funders by exact ISSN",
      "Exclude fee-only routes (~12,000 published routes requiring an OA fee)",
      "Pick freest free version (submitted > accepted > published); prohibited overrides all",
      "Evaluate funder fit identically in search facets, detail pages, and the Guided Finder",
    ],
    details: [
      {
        label: "Funder fit rule order",
        text: "1) Publisher prohibits OA deposit → Not compliant. 2) Gold or Diamond journal → Compliant. 3) Active institutional deal (structured funder policy) → Compliant. 4) Free green route → Check embargo/timing. 5) Otherwise → Not compliant. Text-only funder policies prompt manual checking.",
      },
    ],
  },
  {
    id: "how-works",
    title: "Journal publication totals & work OA conflicts",
    summary:
      "Pure canonical counts and OpenAlex cross-checks are kept separate so every number on screen has one clear meaning.",
    steps: [
      "Link Pure works to journals via OpenAlex DOI → Crossref → Pure CERIF ISSN",
      "Count non-retired Pure works (excluding 17 non-journal types) for journal totals",
      "Keep OpenAlex institution-filter counts labeled separately as a cross-check",
      "Resolve work OA color: OpenAlex (most open per DOI) → Pure rights fallback",
    ],
    details: [
      {
        label: "OpenAlex vs. OpenAIRE disagreements",
        text: "Ground-truth evaluation showed OpenAlex and OpenAIRE tied in accuracy. OpenAlex is used consistently for work-level OA status, while OpenAIRE's status stays visible as a labeled comparison on journal pages.",
      },
      {
        label: "Why ~60% of Pure works have no journal link",
        text: "Dissertations, reports, and non-ISSN conference outputs legitimately have no journal ISSN. Journal statistics therefore use dedicated aggregate tables rather than naive table joins.",
      },
    ],
  },
  {
    id: "how-guided-finder",
    title: "Semantic search, similar journals & Guided Finder",
    summary:
      "Local CPU embeddings match manuscripts to journals privately with zero external LLMs and transparent, deterministic scoring.",
    steps: [
      "Embed every journal from cleaned title + top 5 topics + 3 most-cited paper titles",
      "Encode search queries or manuscript abstracts locally on CPU (never logged or sent out)",
      "Retrieve nearest topical matches via pgvector cosine similarity",
      "Rank with transparent boosts: Diamond > Active deal > Gold in budget > Funder fit",
    ],
    details: [
      {
        label: "Privacy & explainability",
        text: "The embedding model (BAAI/bge-small-en-v1.5) runs inside the application server. No generative AI is used, so recommendations cannot invent journals or deals, and every ranking reason is shown explicitly.",
      },
    ],
  },
];

const SAFEGUARDS: [string, string][] = [
  [
    "MDPI & DOAJ bulk CSV",
    "DOAJ's API caps at 1,000 rows and OpenAlex misses some DOAJ journals (e.g. MDPI Water); OJB ingests the full DOAJ CSV and combines OpenAlex is_oa + OpenAIRE diamond flags.",
  ],
  [
    "Jisc fee-only routes",
    "~12,000 paid published-version routes in Jisc OPF are filtered out so only genuinely free self-archiving routes count as Green OA.",
  ],
  [
    "Pure RIS in gap lists",
    "OpenAlex indexes Pure itself as a repository; repository-primary OpenAlex rows are excluded from all 'Not in Pure' gap lists.",
  ],
  [
    "Book chapters & LNCS",
    "Book chapters stay in work counts (conference proceedings hide there), chapters group under parent books in gap lists, and non-journal venues with institutional works (like LNCS) are searchable.",
  ],
  [
    "Author matching guards",
    "CJK homonym guard, fragmentation-twin ledger (never co-occur + single ORCID), and rejection of OpenAIRE's inferred orcid_pending prevent false merges.",
  ],
  [
    "Mega-journal topic bias",
    "Author research topics are weighted proportionally by each journal's topic counts at the subfield level instead of counting all 5 venue topics equally.",
  ],
  [
    "Emerald & deal overrides",
    "Rebuilt 311 Emerald titles from the signed contract after catching JCT's Elsevier mix-up; re-scrapes fold duplicates by URL and preserve manual_overrides + excluded titles.",
  ],
  [
    "Publisher lineage & flips",
    "Sub-imprints map to canonical parent publishers via OpenAlex lineage; post-contract publisher transfers surface as explicit deal discrepancies.",
  ],
];

export function HowItWorks() {
  return (
    <section id="how-each-view" className="scroll-mt-20 space-y-6">
      <div className="space-y-2">
        <h2 className="text-2xl font-bold tracking-tight">How the data is processed</h2>
        <p className="max-w-4xl text-sm leading-relaxed text-[var(--muted-foreground)]">
          A plain-language overview of how records are gathered, matched, filtered, and reconciled.
          Expand any topic below for the exact rules, or scroll further down for the full technical
          pipeline and database schema.
        </p>
      </div>

      {/* Clean 4-pillar summary */}
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

      {/* Calm, scannable expandable topic cards */}
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

        {/* Safeguards & edge-case fixes */}
        <details
          id="how-safeguards"
          className="group scroll-mt-20 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] shadow-sm"
        >
          <summary className="flex cursor-pointer list-none items-start justify-between gap-4 p-5 [&::-webkit-details-marker]:hidden">
            <div className="space-y-1">
              <h3 className="text-base font-semibold tracking-tight">
                Documented safeguards &amp; real-world fixes ({SAFEGUARDS.length})
              </h3>
              <p className="text-sm text-[var(--muted-foreground)]">
                Edge cases caught during validation — from the Emerald JCT contract mix-up to
                fee-only green OA routes and Pure repository self-matches.
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
