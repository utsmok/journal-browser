import Link from "next/link";
import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type FlowStep = {
  title: string;
  subtitle: string;
  accent?: "primary" | "secondary" | "muted" | "deal";
};

/** Clean horizontal (desktop) / vertical (mobile) SVG-free step flowchart that
 * scales cleanly at any viewport width, supports dark mode, and prints cleanly. */
function ProcessFlow({ steps, label }: { steps: FlowStep[]; label: string }) {
  return (
    <ol aria-label={label} className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-4">
      {steps.map((step, idx) => {
        const accentClass =
          step.accent === "primary"
            ? "border-[var(--primary)]/50 bg-[var(--primary)]/8"
            : step.accent === "secondary"
              ? "border-[var(--secondary)]/30 bg-[var(--secondary)]/8 dark:border-sky-400/30 dark:bg-sky-400/10"
              : step.accent === "deal"
                ? "border-emerald-600/35 bg-emerald-600/8 dark:border-emerald-400/35 dark:bg-emerald-400/10"
                : "border-[var(--border)] bg-[var(--muted)]/40";
        return (
          <li
            key={step.title}
            className={`relative rounded-[var(--radius)] border p-3.5 ${accentClass}`}
          >
            <div className="mb-1 flex items-center gap-2">
              <span className="inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-[var(--secondary)] text-[11px] font-bold text-[var(--secondary-foreground)]">
                {idx + 1}
              </span>
              <span className="text-sm font-semibold leading-snug">{step.title}</span>
            </div>
            <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
              {step.subtitle}
            </p>
          </li>
        );
      })}
    </ol>
  );
}

function RuleCard({
  id,
  badge,
  title,
  lead,
  flowLabel,
  steps,
  facts,
  extra,
}: {
  id: string;
  badge: string;
  title: string;
  lead: string;
  flowLabel: string;
  steps: FlowStep[];
  facts: { q: string; a: ReactNode }[];
  extra?: ReactNode;
}) {
  return (
    <Card id={id} className="scroll-mt-20 space-y-5 p-6">
      <div className="space-y-1.5">
        <span className="inline-block rounded-full bg-[var(--muted)] px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
          {badge}
        </span>
        <h3 className="text-xl font-bold tracking-tight">{title}</h3>
        <p className="max-w-3xl text-sm leading-relaxed text-[var(--muted-foreground)]">{lead}</p>
      </div>

      <ProcessFlow steps={steps} label={flowLabel} />

      <dl className="grid grid-cols-1 gap-4 border-t border-[var(--border)] pt-4 md:grid-cols-2">
        {facts.map((item) => (
          <div key={item.q} className="space-y-1">
            <dt className="text-xs font-semibold uppercase tracking-wide text-[var(--primary-text)]">
              {item.q}
            </dt>
            <dd className="text-sm leading-relaxed text-[var(--foreground)]">{item.a}</dd>
          </div>
        ))}
      </dl>

      {extra}
    </Card>
  );
}

const JUMP_LINKS: { id: string; label: string }[] = [
  { id: "how-authors", label: "Author publications & Pure gaps" },
  { id: "how-journals", label: "Journal search & OA types" },
  { id: "how-deals", label: "OA deals, caps & imprints" },
  { id: "how-apc", label: "APC & publication costs" },
  { id: "how-green-funder", label: "Green OA & funder fit" },
  { id: "how-works", label: "Journal works & OA conflicts" },
  { id: "how-guided-finder", label: "Semantic search & Guided Finder" },
  { id: "how-safeguards", label: "Safeguards & fixes catalogue" },
];

const SAFEGUARDS: { area: string; problem: string; fix: string }[] = [
  {
    area: "Journal OA type",
    problem:
      "OpenAlex missed DOAJ membership for genuine OA journals (e.g., MDPI Water), dropping them into subscription.",
    fix: "OA evidence combines DOAJ bulk CSV (canon), OpenAlex is_oa, and OpenAIRE isInDiamondJournal; unverified OA falls into Generic instead of overeager Diamond.",
  },
  {
    area: "Jisc Green OA",
    problem:
      "~12,000 published-version routes in Jisc OPF require an OA fee and were previously counted as free green OA.",
    fix: "Per-entry fee inspection marks fee-only routes and excludes them from free self-archiving; open_access_prohibited overrides all routes.",
  },
  {
    area: "Pure CRIS gap lists",
    problem:
      "OpenAlex indexes the university's own Pure RIS as a repository, making Pure works appear 'missing from Pure'.",
    fix: "The not_repository() gate drops repository-primary OpenAlex records (Pure RIS, Zenodo, institutional repos) from every gap list.",
  },
  {
    area: "Excluded work types",
    problem:
      "Preprints, datasets, software, errata, and peer reviews inflated OA counts, while excluding chapters dropped conference proceedings.",
    fix: "17 non-journal types are excluded uniformly across all counts, charts, and CSVs; book-chapter and book-part are deliberately kept in.",
  },
  {
    area: "Book chapters in gaps",
    problem:
      "Multi-chapter books multiplied missing-work counts and hid whether the parent book was already registered.",
    fix: "OpenAlex parent_works (rel=volume) and DOI _segment stems roll chapters under their parent volume and tag whether the book is already in Pure.",
  },
  {
    area: "Non-journal venues",
    problem:
      "Major conference/book series such as Lecture Notes in Computer Science (1,300+ UT works) were invisible in journal search.",
    fix: "Any non-journal venue type with ≥1 institutional work enters search; proceedings-titled venues stay hidden unless deal-covered or locally used.",
  },
  {
    area: "Author identity matching",
    problem:
      "Name-only matching produced 21,541 false candidates; CJK surnames and fragmented profiles collapsed distinct people (e.g. 5 'Xiang Zhang' profiles).",
    fix: "Work-anchored 5-rung deterministic cascade + CJK homonym guard + fragmentation-twin ledger (never co-occur, single ORCID) + OpenAIRE orcid_pending rejection.",
  },
  {
    area: "Author topic profiles",
    problem:
      "Mega-journals (IEEE Access, Scientific Reports, Sensors) stamped 'Advanced Neural Network Applications' onto 439 unrelated authors.",
    fix: "Each journal's work count is distributed proportionally across its OpenAlex topic counts and aggregated at the subfield level.",
  },
  {
    area: "Deals & Emerald contract",
    problem:
      "JCT upstream linked the Dutch Emerald agreement to Elsevier's UKB sheet; re-scrapes forked duplicate rows and wiped curation notes.",
    fix: "Rebuilt all 311 Emerald titles from the signed contract; reconcile folds scrape-forks by URL; JCT merges provenance; manual_overrides and excluded tombstones survive harvests.",
  },
  {
    area: "Publisher imprints",
    problem:
      "Sub-imprints (e.g. LWW, IEEE ComSoc) fragmented publisher totals and misattributed agreements.",
    fix: "OpenAlex publisher lineage maps imprints to canonical parent publishers; post-contract publisher transfers flag explicitly as deal_discrepancies.",
  },
  {
    area: "Card vs. works tab counts",
    problem:
      "Filling missing Pure years from OpenAlex made cards show 1,112 where the publications tab showed 1,018 (LNCS).",
    fix: "Search cards, detail totals, FWCI/retracted tiles, and works tabs all read the exact same Pure canon population; OpenAlex filter stays a labeled cross-check.",
  },
  {
    area: "Work OA status conflicts",
    problem:
      "OpenAlex and OpenAIRE disagree on some works, and early Pure OAI sweeps overwrote OpenAlex colors.",
    fix: "OpenAlex wins work-level OA ties (most-open across duplicate W-IDs); Pure rights fill in only when OpenAlex has no row; OpenAIRE stays display-only comparison.",
  },
];

export function HowItWorks() {
  return (
    <section id="how-each-view" className="scroll-mt-20 space-y-6">
      <div className="space-y-3">
        <h2 className="text-2xl font-bold tracking-tight">
          How Every List, Badge, and Metric Is Built
        </h2>
        <p className="max-w-3xl text-sm leading-relaxed text-[var(--muted-foreground)]">
          Open Journal Browser never treats external databases as black boxes. Every upstream file
          or API response is archived verbatim before processing, every matching rule favors{" "}
          <strong className="text-[var(--foreground)]">precision over recall</strong>, and whenever
          two sources disagree the primary source and conflict rule are explicit. Pick any surface
          below to trace exactly how its numbers come to be.
        </p>
        <div className="flex flex-wrap gap-2">
          {JUMP_LINKS.map((item) => (
            <a
              key={item.id}
              href={`#${item.id}`}
              className="rounded-full border border-[var(--border)] bg-[var(--card)] px-3 py-1 text-xs font-medium text-[var(--primary-text)] transition-colors hover:bg-[var(--muted)]"
            >
              {item.label}
            </a>
          ))}
        </div>
      </div>

      <RuleCard
        id="how-authors"
        badge="Authors & CRIS Gaps"
        title="Author Roster, Publications List, and 'Not in Pure' Gaps"
        lead="How a single researcher's profile, canonical publication list, OA trend, topics, and OpenAlex-only gap list are assembled from Pure, OpenAlex, and OpenAIRE."
        flowLabel="Author data processing flow"
        steps={[
          {
            title: "1. Pure OAI-PMH (Primary)",
            subtitle:
              "CERIF publications, persons, and org units define the canonical author roster and publication list.",
            accent: "primary",
          },
          {
            title: "2. Org-Tree & Type Filters",
            subtitle:
              "Org closure (depth ≤ 30) confirms institution ROR affiliation; 17 non-journal types are excluded (book chapters kept).",
          },
          {
            title: "3. 5-Rung Identity Cascade",
            subtitle:
              "Matches Pure authors to OpenAlex/OpenAIRE per shared work: ORCID → exact name → initials → unique surname → strict fuzzy.",
            accent: "secondary",
          },
          {
            title: "4. Enrich & Compute Gaps",
            subtitle:
              "Canonical list gets OpenAlex/OpenAIRE metrics by DOI; gap list anti-joins Pure DOIs and drops repository-only copies.",
            accent: "deal",
          },
        ]}
        facts={[
          {
            q: "Which source is primary?",
            a: "Your university's public Pure OAI-PMH repository is the canonical list of publications. OpenAlex and OpenAIRE enrich those records by DOI and power the separate 'Found in OpenAlex, not in Pure' gap card — the two populations are never silently mixed.",
          },
          {
            q: "What is filtered out (and what stays in)?",
            a: (
              <>
                17 non-journal types are excluded from every count, list, chart, and export:{" "}
                <code className="rounded bg-[var(--muted)] px-1 text-xs">
                  preprint, posted-content, working-paper, book, monograph, dataset, software,
                  other, erratum, supplementary-materials, peer-review, paratext, reference-entry,
                  book-review, retraction, libguides, standard
                </code>
                . <strong>Book chapters and book parts stay in</strong> because conference
                proceedings often hide there.
              </>
            ),
          },
          {
            q: "How are Pure authors matched without false merges?",
            a: "Only per shared work — never global name-only matching. Exact ORCID (rejecting OpenAIRE's inferred orcid_pending) and conflict-free deterministic name/initials rungs auto-confirm; CJK surnames block surname-only and fuzzy rungs; multiple OpenAlex A-IDs auto-link as fragmentation twins only if they never co-occur on a work and share at most one ORCID. Fuzzy or conflicting matches wait in admin review.",
          },
          {
            q: "Why don't Pure's own records show up as 'missing from Pure'?",
            a: "The OpenAlex-only gap list applies three gates: active year window, the 17-type exclusion list, and the not_repository() gate (dropping works whose OpenAlex primary source is a repository such as Zenodo or the institution's own Pure RIS). Chapters roll up under their parent book via OpenAlex parent_works and DOI stems.",
          },
        ]}
      />

      <RuleCard
        id="how-journals"
        badge="Journals & Search"
        title="Journal Universe, Search Ranking, and OA Classification"
        lead="How ~177,700 OpenAlex venues are filtered into the searchable catalogue and classified at query time into Diamond, Gold, Hybrid, Generic, or Subscription."
        flowLabel="Journal universe and OA classification flow"
        steps={[
          {
            title: "1. OpenAlex Universe",
            subtitle:
              "~268k raw OpenAlex sources normalized by canonical ISSN-L into ~177.7k journals with topics, counts, and publishers.",
            accent: "primary",
          },
          {
            title: "2. Corpus & Noise Cutoffs",
            subtitle:
              "Keep journals with >3 works in window + non-journal venues with ≥1 inst work (e.g. LNCS); hide unused proceedings titles & ignored ISSNs.",
          },
          {
            title: "3. Multi-Source OA Evidence",
            subtitle:
              "Combine DOAJ bulk CSV (canon), OpenAlex is_oa/APCs, OpenAPC spend, OpenAIRE diamond flags, observed recent OA, and active deals.",
            accent: "secondary",
          },
          {
            title: "4. Query-Time Ranking",
            subtitle:
              "6-tier oa_type rule runs live; FTS keyword rank boosts journals your institution publishes in, with trigram fuzzy fallback (≥0.3).",
            accent: "deal",
          },
        ]}
        facts={[
          {
            q: "How is Diamond vs. Gold vs. Hybrid decided?",
            a: "First match wins in strict order: (1) OA evidence + any charge evidence (DOAJ APC, OpenAPC payment, or OpenAlex list price) → Gold; (2) DOAJ with explicit no-APC OR OpenAIRE isInDiamondJournal → Diamond; (3) modal observed OA color of 20 recent works if gold/diamond/hybrid; (4) active institutional deal → Hybrid; (5) OA evidence with no fee data → Generic ('OA status unknown'); (6) else Subscription.",
          },
          {
            q: "What if DOAJ says no APC but OpenAPC shows payments?",
            a: "Observed OpenAPC payments win (Tier 1 beats Tier 2), so the journal classifies as Gold — real paid APCs outweigh a stale no-APC flag.",
          },
          {
            q: "Why are some conferences/book series shown while others are hidden?",
            a: "Venues with proceedings-like titles (conference, proceedings, symposium, workshop, abstracts, meetings) are hidden unless covered by an active deal (like ACM) or containing at least one institutional publication. Any non-journal venue type with ≥1 institutional work (such as LNCS) is explicitly admitted.",
          },
          {
            q: "Why does the DOAJ source use a bulk CSV instead of the DOAJ API?",
            a: "The public DOAJ search API caps pagination at 1,000 results. Downloading doaj.org/csv guarantees 100% coverage (~23,500 journals) and stamps a tri-state flag (in DOAJ / checked & absent / not an OA candidate).",
          },
        ]}
      />

      <RuleCard
        id="how-deals"
        badge="Deals & Publishers"
        title="Open Access Deals, Caps, Overrides, and Publisher Lineage"
        lead="How Dutch national and institutional publishing agreements are assembled from openaccess.nl and JCT/ESAC while keeping curator corrections intact."
        flowLabel="Deal register reconciliation flow"
        steps={[
          {
            title: "1. openaccess.nl (Canon)",
            subtitle:
              "Scrapes publisher & deal pages for existence, duration, conditions, cap text, and contract PDFs. Ambiguous caps flag curation.",
            accent: "primary",
          },
          {
            title: "2. JCT / ESAC (Enrichment)",
            subtitle:
              "Ingests cOAlition S Google-Sheets CSVs for ESAC IDs and ISSN lists. JCT absence never erases a valid openaccess.nl deal.",
            accent: "secondary",
          },
          {
            title: "3. Reconcile & Dedupe",
            subtitle:
              "Folds scrape-forked duplicates by URL, merges provenance instead of overwriting, and resolves ISSNs via issn_map.",
          },
          {
            title: "4. Sticky Curation & Lineage",
            subtitle:
              "Re-applies manual_overrides & excluded tombstones; maps publisher imprints to parent publishers and flags publisher flips.",
            accent: "deal",
          },
        ]}
        facts={[
          {
            q: "What happens when openaccess.nl and JCT disagree?",
            a: "openaccess.nl wins for deal existence, terms, and caps; JCT supplies machine-readable ISSN lists. Conflicts flag needs_curation instead of silently picking a winner, and contract PDFs are never auto-parsed without human confirmation.",
          },
          {
            q: "How did OJB catch and fix the Emerald deal?",
            a: "The upstream JCT dump mistakenly linked the Dutch Emerald agreement to Elsevier's UKB sheet. OJB's overlap guard flagged it, and all 311 Emerald titles were reconstructed from the signed SURF–Emerald contract.",
          },
          {
            q: "How does multi-institution deal scoping work?",
            a: "Shared deals are stored once. Each hosted university links only the agreements it participates in via deal_institutions (absence means non-participation), and can attach a local journal_override title list or exclude specific ISSNs without affecting other universities.",
          },
          {
            q: "How are publisher imprints and transfers handled?",
            a: "OpenAlex publisher lineage maps sub-brands (e.g., LWW → Wolters Kluwer) under their root publisher. When a journal moves to a new publisher after a contract was signed, it surfaces explicitly as a deal discrepancy.",
          },
        ]}
      />

      <RuleCard
        id="how-apc"
        badge="Costs"
        title="APC & Observed Publication Cost Evidence"
        lead="How publication costs combine declared publisher list prices with real-world institutional APC payments."
        flowLabel="APC evidence precedence flow"
        steps={[
          {
            title: "1. OpenAlex List Price",
            subtitle:
              "Primary price display: selects EUR first, then USD, then first listed currency from OpenAlex apc_prices.",
            accent: "primary",
          },
          {
            title: "2. ECB EUR Conversion",
            subtitle:
              "Non-EUR list prices convert at the ECB January 1 exchange rate of the current year for consistent sorting.",
          },
          {
            title: "3. OpenAPC Fallback",
            subtitle:
              "If no list price exists, displays observed min–max EUR paid across the newest two OpenAPC release periods.",
            accent: "secondary",
          },
          {
            title: "4. DOAJ Corroboration",
            subtitle:
              "DOAJ has_apc drives the Gold vs. Diamond split; DOAJ declared max APC shows separately on detail pages with caveats.",
            accent: "deal",
          },
        ]}
        facts={[
          {
            q: "Why does APC sorting use the newest period's maximum?",
            a: "OpenAPC period means average multi-article discounts and waivers across institutions. Sorting by the newest period's highest observed euro_max gives a realistic upper-bound expectation of list cost.",
          },
          {
            q: "What if a journal is covered by an active deal?",
            a: "List and observed APCs remain visible for transparency (showing what publishing would otherwise cost), while the deal panel and Guided Finder highlight €0 / discounted author cost under the agreement.",
          },
        ]}
      />

      <RuleCard
        id="how-green-funder"
        badge="Policies & Funders"
        title="Green OA Self-Archiving and Funder Compliance"
        lead="How publisher self-archiving rules from Jisc Open Policy Finder combine with funder mandates to classify compliance."
        flowLabel="Green OA and funder compliance flow"
        steps={[
          {
            title: "1. Jisc OPF Harvest",
            subtitle:
              "Full sweep of publications, policies, publishers, repositories, and 202 funders, matched strictly by validated 8-char ISSN.",
            accent: "primary",
          },
          {
            title: "2. Fee-Only & Prohibition Guard",
            subtitle:
              "Excludes routes where all fee statements require payment (~12k published routes); open_access_prohibited overrides everything.",
          },
          {
            title: "3. Best Free Route",
            subtitle:
              "Buckets journals by freest permitted version (submitted > accepted > published); policy text & licenses stay verbatim (CC BY-NC-ND).",
            accent: "secondary",
          },
          {
            title: "4. 5-Tier Funder Fit",
            subtitle:
              "Shared Python + SQL rules: Prohibited → No; Gold/Diamond → Compliant; Active Deal → Compliant; Green route → Check; else No.",
            accent: "deal",
          },
        ]}
        facts={[
          {
            q: "Why does a journal with a 'published' route sometimes show 'No green route'?",
            a: "Many hybrid journals only allow depositing the published PDF after paying an OA fee. OJB inspects per-entry additional_oa_fee flags and marks fee-only routes ineligible as free green OA.",
          },
          {
            q: "What happens for funders without machine-readable policies?",
            a: "Structured OPF archiving policies (201 of 202 funders) receive automated Compliant / Check / Not compliant badges; text-only funder policies intentionally show no automated tier and prompt manual checking.",
          },
        ]}
      />

      <RuleCard
        id="how-works"
        badge="Journal Works & Metrics"
        title="Journal Publications, Institutional Totals, and Work OA Conflicts"
        lead="Why journal pages report a Pure canonical total alongside an OpenAlex cross-check, and how work-level OA status conflicts are resolved."
        flowLabel="Journal works and OA conflict flow"
        steps={[
          {
            title: "1. Pure Canonical Corpus",
            subtitle:
              "All non-retired Pure works in the active data window (excluding the 17 non-journal types) drive journal totals and tabs.",
            accent: "primary",
          },
          {
            title: "2. DOI → Journal Ladder",
            subtitle:
              "Resolves journal ISSN-L via OpenAlex ($0 singleton GET) → Crossref polite pool → Pure CERIF ISSN fallback via issn_map.",
          },
          {
            title: "3. OA-Color Precedence",
            subtitle:
              "OpenAlex wins work-level OA (most-open across duplicate W-IDs); Pure rights fill in when unmatched; OpenAIRE stays comparison.",
            accent: "secondary",
          },
          {
            title: "4. Dual-Population Labels",
            subtitle:
              "FWCI & retracted tiles run on Pure canon + DOI metrics; OpenAlex institution filter stays separate as a labeled cross-check.",
            accent: "deal",
          },
        ]}
        facts={[
          {
            q: "Why do ~60% of Pure works have no journal link?",
            a: "Dissertations, conference papers without journal ISSNs, reports, and book chapters legitimately have no journal ISSN anywhere. Journal statistics therefore aggregate from pre-computed stats tables rather than naive table joins.",
          },
          {
            q: "How are OpenAlex vs. OpenAIRE OA-status disagreements handled?",
            a: "A 94-work ground-truth evaluation found OpenAIRE (53.3%) and OpenAlex (44.8%) statistically tied. OpenAlex is the consistent tie-breaker for works.oa_status, while OpenAIRE's OA classification stays visible on the journal's OpenAIRE comparison card.",
          },
        ]}
      />

      <RuleCard
        id="how-guided-finder"
        badge="Embeddings & Guided Finder"
        title="Semantic Search, Similar Journals, and the Guided Journal Finder"
        lead="How plain-language abstracts match journals privately on-server without external LLMs, and how the Guided Finder ranks recommendations."
        flowLabel="Semantic embedding and guided recommendation flow"
        steps={[
          {
            title: "1. Journal Vector Text",
            subtitle:
              "Each journal is embedded from its cleaned title (boilerplate stripped) + top 5 OpenAlex topics + 3 most-cited work titles.",
            accent: "primary",
          },
          {
            title: "2. Local ONNX Encoding",
            subtitle:
              "BAAI/bge-small-en-v1.5 (384-dim) runs locally on CPU via fastembed. Your abstract never leaves the server and is never logged.",
            accent: "secondary",
          },
          {
            title: "3. pgvector HNSW Recall",
            subtitle:
              "Retrieves nearest semantic candidates in cosine space (strict_order iterative scan) respecting corpus & venue filters.",
          },
          {
            title: "4. Deterministic Ranking",
            subtitle:
              "Applies transparent boosts (Diamond > Deal > Gold in budget > Funder compliant > Inst history) with plain-language reasons.",
            accent: "deal",
          },
        ]}
        facts={[
          {
            q: "Is any generative AI or external LLM used?",
            a: "No. Everything is deterministic vector similarity plus structured SQL/Python rules over open datasets. Recommendations cannot hallucinate journals, fake deals, or leak unpublished manuscripts to third-party APIs.",
          },
          {
            q: "What happens if strict filters leave fewer than 3 matches?",
            a: "Instead of returning a blank screen, the Guided Finder shows any strict matches first and lists the closest relaxed alternatives separately — explicitly stating which constraint (budget, funder tier, or green OA) was relaxed.",
          },
        ]}
      />

      <div id="how-safeguards" className="scroll-mt-20 space-y-3">
        <div className="space-y-1">
          <h3 className="text-xl font-bold tracking-tight">
            Documented Safeguards, Edge Cases, and Real-World Fixes
          </h3>
          <p className="max-w-3xl text-sm text-[var(--muted-foreground)]">
            Every rule below originated from a real data anomaly observed during harvesting and
            validation, and is permanently encoded in the pipeline and regression test suite.
          </p>
        </div>
        <Card>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-44">Area</TableHead>
                  <TableHead>Upstream issue observed</TableHead>
                  <TableHead>Safeguard built into OJB</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {SAFEGUARDS.map((row) => (
                  <TableRow key={row.area}>
                    <TableCell className="whitespace-nowrap font-semibold text-xs">
                      {row.area}
                    </TableCell>
                    <TableCell className="text-xs leading-relaxed text-[var(--muted-foreground)]">
                      {row.problem}
                    </TableCell>
                    <TableCell className="text-xs leading-relaxed">{row.fix}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </Card>
        <p className="text-xs text-[var(--muted-foreground)]">
          Full technical deep-dive (sources, bootstrap DAG, API calls, storage layers, and database
          schema) follows below, or read the printable prose version in the{" "}
          <Link href="/" className="text-[var(--primary-text)] underline-offset-2 hover:underline">
            institution docs
          </Link>{" "}
          (<em>How Data Is Ingested, Matched, Filtered, and Processed</em>).
        </p>
      </div>
    </section>
  );
}
