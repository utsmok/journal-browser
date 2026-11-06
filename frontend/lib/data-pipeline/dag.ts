import planJson from "@/lib/data-pipeline-plan.json";

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

export type PlanStep = {
  id: string;
  band: DagBand;
  script: string;
  deps: string[];
};

export const PLAN = planJson as { generatedAt: string; steps: PlanStep[] };

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

// Presentation only: display labels, source dots, and coordinates. Step ids,
// bands, scripts, and dependencies come from the generated plan JSON and are
// verified against the drawn edges below.
const LAYOUT: Record<
  string,
  { label: string; sources: SourceKey[]; x: number; y: number; jobSuffix?: string }
> = {
  journals: { label: "Journal sweep", sources: ["openalex"], x: 40, y: 70 },
  publishers: { label: "Publisher lineage", sources: ["openalex"], x: 40, y: 170 },
  "deals-openaccess-nl": { label: "openaccess.nl deals", sources: ["register"], x: 240, y: 70 },
  "deals-jct": { label: "JCT sheets", sources: ["register"], x: 440, y: 70 },
  openapc: { label: "OpenAPC", sources: ["register"], x: 640, y: 70 },
  "deals-reconcile": { label: "Deal reconcile", sources: ["db"], x: 840, y: 70 },
  "deals-issn-l": { label: "Deal ISSN-L", sources: ["db"], x: 40, y: 240 },
  scimagojr: { label: "Scimago quartiles", sources: ["register"], x: 240, y: 170 },
  flags: { label: "Corpus flags", sources: ["db"], x: 440, y: 170 },
  doaj: { label: "DOAJ canon", sources: ["register"], x: 628, y: 170 },
  "oa-colors": { label: "OA color sample", sources: ["openalex"], x: 824, y: 170 },
  pure: { label: "Pure works sweep", sources: ["pure"], x: 40, y: 390 },
  "pure-cerif": {
    label: "CERIF authors",
    sources: ["pure"],
    x: 240,
    y: 340,
    jobSuffix: " --cerif",
  },
  "pure-entities": { label: "Orgs and persons", sources: ["pure"], x: 240, y: 520 },
  enrich: { label: "Enrich works", sources: ["openalex", "crossref"], x: 240, y: 430 },
  openaire: { label: "OpenAIRE products", sources: ["openaire"], x: 240, y: 610 },
  stats: { label: "Institution stats", sources: ["openalex"], x: 440, y: 430 },
  "openalex-works": { label: "Works store", sources: ["db"], x: 640, y: 530 },
  "pure-authors": { label: "Pure author edges", sources: ["db"], x: 640, y: 440 },
  reconcile: {
    label: "Coverage flags",
    sources: ["db"],
    x: 840,
    y: 340,
    jobSuffix: " --institution",
  },
  "author-ids": { label: "Author identity cascade", sources: ["openalex"], x: 840, y: 430 },
  authors: { label: "Author roster", sources: ["db"], x: 840, y: 520 },
  embeddings: { label: "Journal embeddings", sources: ["db"], x: 440, y: 760 },
};

export const DAG_STEPS: DagStep[] = PLAN.steps.map((step) => {
  const lay = LAYOUT[step.id];
  if (!lay) {
    throw new Error(
      `plan step ${step.id} has no layout entry; regenerate or fix lib/data-pipeline/dag.ts`,
    );
  }
  return {
    id: step.id,
    label: lay.label,
    job: step.script + (lay.jobSuffix ?? ""),
    band: step.band,
    sources: lay.sources,
    deps: step.deps,
    x: lay.x,
    y: lay.y,
  };
});

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

// Build-time drift check: the drawn arrows must be exactly the plan's
// dependency pairs, and every layout entry must map to a real plan step.
{
  const planPairs = PLAN.steps
    .flatMap((step) => step.deps.map((dep) => `${dep}->${step.id}`))
    .sort();
  const drawnPairs = DAG_EDGES.map((edge) => `${edge.from}->${edge.to}`).sort();
  const missing = planPairs.filter((pair) => !drawnPairs.includes(pair));
  const extra = drawnPairs.filter((pair) => !planPairs.includes(pair));
  const orphanLayouts = Object.keys(LAYOUT).filter(
    (id) => !PLAN.steps.some((step) => step.id === id),
  );
  const problems = [
    ...missing.map((pair) => `plan edge not drawn: ${pair}`),
    ...extra.map((pair) => `drawn edge not in plan: ${pair}`),
    ...orphanLayouts.map((id) => `layout entry without plan step: ${id}`),
  ];
  if (problems.length > 0) {
    throw new Error(`harvest plan drift detected:\n${problems.join("\n")}`);
  }
}
