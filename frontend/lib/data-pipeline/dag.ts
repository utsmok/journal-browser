export type DagBand = "global" | "institution" | "final";

export type SourceKey = "openalex" | "crossref" | "openaire" | "pure" | "register" | "db";

export type DagStep = {
  id: string;
  label: string;
  job: string;
  band: DagBand;
  sources: SourceKey[];
  deps: string[];
  x: number;
  y: number;
};

export type DagBandRect = {
  id: DagBand;
  label: string;
  x: number;
  y: number;
  w: number;
  h: number;
};

export type DagEdge = {
  from: string;
  to: string;
  d: string;
};

export const NODE_W = 168;
export const NODE_H = 44;

export const VIEW_W = 1080;
export const VIEW_H = 860;

export const DAG_BANDS: DagBandRect[] = [
  { id: "global", label: "Global band", x: 20, y: 40, w: 1040, h: 250 },
  {
    id: "institution",
    label: "Institution band (per institution)",
    x: 20,
    y: 330,
    w: 1040,
    h: 370,
  },
  { id: "final", label: "Final step", x: 330, y: 740, w: 420, h: 90 },
];

export const DAG_STEPS: DagStep[] = [
  // Global band
  {
    id: "journals",
    label: "Journal sweep",
    job: "harvest_journals.py",
    band: "global",
    sources: ["openalex"],
    deps: [],
    x: 40,
    y: 70,
  },
  {
    id: "deals-openaccess-nl",
    label: "openaccess.nl deals",
    job: "scrape_openaccess_nl.py",
    band: "global",
    sources: ["register"],
    deps: [],
    x: 240,
    y: 70,
  },
  {
    id: "deals-jct",
    label: "JCT sheets",
    job: "ingest_jct.py",
    band: "global",
    sources: ["register"],
    deps: [],
    x: 440,
    y: 70,
  },
  {
    id: "openapc",
    label: "OpenAPC",
    job: "ingest_openapc.py",
    band: "global",
    sources: ["register"],
    deps: [],
    x: 640,
    y: 70,
  },
  {
    id: "deals-reconcile",
    label: "Deal reconcile",
    job: "reconcile.py",
    band: "global",
    sources: ["db"],
    deps: ["journals", "deals-openaccess-nl", "deals-jct"],
    x: 840,
    y: 70,
  },
  {
    id: "publishers",
    label: "Publisher lineage",
    job: "harvest_publishers.py",
    band: "global",
    sources: ["openalex"],
    deps: ["journals"],
    x: 40,
    y: 170,
  },
  {
    id: "scimagojr",
    label: "Scimago quartiles",
    job: "ingest_scimagojr.py",
    band: "global",
    sources: ["register"],
    deps: ["journals"],
    x: 240,
    y: 170,
  },
  {
    id: "flags",
    label: "Corpus flags",
    job: "backfill_flags.py",
    band: "global",
    sources: ["db"],
    deps: ["journals"],
    x: 440,
    y: 170,
  },
  {
    id: "doaj",
    label: "DOAJ canon",
    job: "harvest_doaj.py",
    band: "global",
    sources: ["register"],
    deps: ["journals"],
    x: 628,
    y: 170,
  },
  {
    id: "oa-colors",
    label: "OA color sample",
    job: "harvest_oa_colors.py",
    band: "global",
    sources: ["openalex"],
    deps: ["journals", "openapc"],
    x: 824,
    y: 170,
  },
  {
    id: "deals-issn-l",
    label: "Deal ISSN-L",
    job: "backfill_issn_l.py",
    band: "global",
    sources: ["db"],
    deps: ["deals-reconcile"],
    x: 40,
    y: 240,
  },
  // Institution band
  {
    id: "pure",
    label: "Pure works sweep",
    job: "harvest_pure.py",
    band: "institution",
    sources: ["pure"],
    deps: [],
    x: 40,
    y: 390,
  },
  {
    id: "pure-cerif",
    label: "CERIF authors",
    job: "harvest_pure.py --cerif",
    band: "institution",
    sources: ["pure"],
    deps: ["pure"],
    x: 240,
    y: 340,
  },
  {
    id: "enrich",
    label: "Enrich works",
    job: "enrich_works.py",
    band: "institution",
    sources: ["openalex", "crossref"],
    deps: ["pure"],
    x: 240,
    y: 430,
  },
  {
    id: "pure-entities",
    label: "Orgs and persons",
    job: "harvest_pure_entities.py",
    band: "institution",
    sources: ["pure"],
    deps: ["pure"],
    x: 240,
    y: 520,
  },
  {
    id: "openaire",
    label: "OpenAIRE products",
    job: "harvest_openaire.py",
    band: "institution",
    sources: ["openaire"],
    deps: ["pure", "deals-issn-l"],
    x: 240,
    y: 610,
  },
  {
    id: "stats",
    label: "Institution stats",
    job: "harvest_stats.py",
    band: "institution",
    sources: ["openalex"],
    deps: ["enrich", "openaire", "openapc", "scimagojr", "flags"],
    x: 440,
    y: 430,
  },
  {
    id: "pure-authors",
    label: "Pure author edges",
    job: "backfill_pure_authors.py",
    band: "institution",
    sources: ["db"],
    deps: ["pure-cerif", "openalex-works"],
    x: 640,
    y: 440,
  },
  {
    id: "openalex-works",
    label: "Works store",
    job: "build_openalex_works.py",
    band: "institution",
    sources: ["db"],
    deps: ["stats"],
    x: 640,
    y: 530,
  },
  {
    id: "reconcile",
    label: "Coverage flags",
    job: "reconcile.py --institution",
    band: "institution",
    sources: ["db"],
    deps: ["stats", "deals-reconcile"],
    x: 840,
    y: 340,
  },
  {
    id: "author-ids",
    label: "Author identity cascade",
    job: "resolve_author_ids.py",
    band: "institution",
    sources: ["openalex"],
    deps: ["openalex-works", "pure-entities", "pure-cerif", "pure-authors"],
    x: 840,
    y: 430,
  },
  {
    id: "authors",
    label: "Author roster",
    job: "ingest_authors.py",
    band: "institution",
    sources: ["db"],
    deps: ["author-ids", "reconcile"],
    x: 840,
    y: 520,
  },
  // Final band
  {
    id: "embeddings",
    label: "Journal embeddings",
    job: "embed_journals.py",
    band: "final",
    sources: ["db"],
    deps: ["stats"],
    x: 440,
    y: 760,
  },
];

// Hand-routed paths; sources exit right or bottom, targets enter left or top.
// A few long cross-band returns run in dedicated lanes to keep nodes clear.
export const DAG_EDGES: DagEdge[] = [
  { from: "journals", to: "publishers", d: "M 124 114 L 124 170" },
  { from: "journals", to: "scimagojr", d: "M 176 114 C 210 130 240 150 280 170" },
  { from: "journals", to: "flags", d: "M 208 92 C 290 130 380 150 460 170" },
  { from: "journals", to: "doaj", d: "M 208 96 C 300 150 600 155 690 170" },
  { from: "journals", to: "oa-colors", d: "M 208 104 C 350 165 700 168 900 170" },
  {
    from: "journals",
    to: "deals-reconcile",
    d: "M 208 78 C 240 64 300 58 360 58 L 800 58 C 856 58 910 60 930 70",
  },
  {
    from: "deals-openaccess-nl",
    to: "deals-reconcile",
    d: "M 324 70 C 340 56 360 46 400 46 L 760 46 C 812 46 848 54 856 70",
  },
  {
    from: "deals-jct",
    to: "deals-reconcile",
    d: "M 608 92 C 640 100 680 140 720 140 L 790 140 C 820 140 840 122 840 108",
  },
  {
    from: "openapc",
    to: "oa-colors",
    d: "M 808 108 C 830 118 850 130 880 145 C 895 152 900 158 900 170",
  },
  {
    from: "openapc",
    to: "stats",
    d: "M 656 114 C 640 140 618 170 618 220 L 618 400 C 618 425 580 425 560 430",
  },
  { from: "scimagojr", to: "stats", d: "M 400 214 C 400 300 430 360 470 430" },
  { from: "flags", to: "stats", d: "M 590 214 C 590 280 590 360 590 430" },
  {
    from: "deals-reconcile",
    to: "deals-issn-l",
    d: "M 840 80 C 806 80 806 52 776 52 L 60 52 C 40 52 30 58 30 90 L 30 230 C 30 248 32 262 40 262",
  },
  { from: "deals-reconcile", to: "reconcile", d: "M 1008 92 C 1044 92 1044 356 1008 356" },
  {
    from: "deals-issn-l",
    to: "openaire",
    d: "M 124 284 C 140 306 220 316 320 316 C 400 316 424 330 424 420 L 424 540 C 424 586 402 600 384 610",
  },
  { from: "pure", to: "pure-cerif", d: "M 208 400 C 224 400 224 362 240 362" },
  { from: "pure", to: "enrich", d: "M 208 410 C 224 410 224 452 240 452" },
  { from: "pure", to: "pure-entities", d: "M 208 420 C 224 420 224 542 240 542" },
  { from: "pure", to: "openaire", d: "M 208 430 C 224 430 224 618 240 618" },
  { from: "enrich", to: "stats", d: "M 408 452 C 424 452 424 460 440 460" },
  { from: "openaire", to: "stats", d: "M 408 632 C 424 632 424 470 440 470" },
  { from: "pure-cerif", to: "pure-authors", d: "M 408 362 C 500 362 640 380 700 440" },
  { from: "pure-cerif", to: "author-ids", d: "M 408 350 C 500 362 720 392 840 432" },
  {
    from: "pure-entities",
    to: "author-ids",
    d: "M 408 530 C 420 560 424 590 444 592 C 560 598 700 596 800 592 C 824 588 826 500 840 470",
  },
  { from: "openalex-works", to: "pure-authors", d: "M 720 530 C 720 515 720 499 720 484" },
  { from: "stats", to: "openalex-works", d: "M 600 474 C 600 500 640 530 700 530" },
  { from: "stats", to: "reconcile", d: "M 608 460 C 690 400 780 362 840 362" },
  { from: "stats", to: "embeddings", d: "M 560 474 C 560 500 560 600 560 760" },
  { from: "openalex-works", to: "author-ids", d: "M 808 552 C 824 552 824 460 840 460" },
  { from: "pure-authors", to: "author-ids", d: "M 808 452 C 824 452 824 448 840 448" },
  { from: "reconcile", to: "authors", d: "M 1008 368 C 1034 368 1034 542 1008 542" },
  { from: "author-ids", to: "authors", d: "M 900 474 C 900 490 900 504 900 520" },
];
