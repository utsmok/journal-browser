export type SourceRow = {
  id: string;
  name: string;
};

// The provides / transport / usedBy prose for each source lives in
// frontend/messages/en/dataPipeline.json under
// sources.<id>Provides / <id>Transport / <id>UsedBy.
export const SOURCES: SourceRow[] = [
  { id: "openalex", name: "OpenAlex" },
  { id: "crossref", name: "Crossref" },
  { id: "openaire", name: "OpenAIRE Graph API" },
  { id: "pureOai", name: "Pure OAI-PMH (ris.utwente.nl)" },
  { id: "openaccessNl", name: "openaccess.nl" },
  { id: "jct", name: "JCT (cOAlition S)" },
  { id: "openapc", name: "OpenAPC" },
  { id: "doaj", name: "DOAJ" },
  { id: "scimago", name: "Scimago Journal Rank" },
  { id: "jisc", name: "Jisc Open Policy Finder" },
  { id: "ipApi", name: "ip-api.com" },
  { id: "purePortal", name: "Pure portal (research.utwente.nl)" },
  { id: "utMetadata", name: "ut-metadata platform" },
  { id: "embeddings", name: "BAAI/bge-small-en-v1.5" },
];
