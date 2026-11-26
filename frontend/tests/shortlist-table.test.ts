import { describe, expect, it } from "vitest";

import robots from "@/app/robots";
import {
  apcText,
  shortlistCsv,
  type ShortlistLabels,
  type ShortlistRow,
} from "@/components/shortlist/shortlist-table";
import { journalWorksRequest, similarRequest, type JournalBatchItem } from "@/lib/api";

function parseCsvLine(line: string): string[] {
  const cells: string[] = [];
  let i = 0;
  while (i <= line.length) {
    if (line[i] === '"') {
      let end = i + 1;
      while (end < line.length) {
        if (line[end] === '"' && line[end + 1] === '"') {
          end += 2;
          continue;
        }
        if (line[end] === '"') break;
        end += 1;
      }
      cells.push(line.slice(i + 1, end).replaceAll('""', '"'));
      i = end + 2;
    } else {
      const comma = line.indexOf(",", i);
      if (comma === -1) {
        cells.push(line.slice(i));
        break;
      }
      cells.push(line.slice(i, comma));
      i = comma + 1;
    }
  }
  return cells;
}

const LABELS: ShortlistLabels = {
  columns: {
    journal: "Journal",
    issnL: "ISSN-L",
    remove: "Remove",
    publisher: "Publisher",
    deal: "Deal",
    dealName: "Deal name",
    oaType: "OA type",
    apc: "APC",
    quartile: "Quartile",
    works: "UT works",
    doaj: "DOAJ",
    greenOa: "Green OA",
    added: "Added",
  },
  yes: "Yes",
  no: "No",
  none: "—",
  paid: "paid",
  noDeal: "No deal",
  unknownPublisher: "Unknown",
  dealFallback: (id) => `Deal ${id}`,
  oaType: (type) => type,
  greenOa: (route) => route ?? "None",
};

function makeItem(overrides: Partial<JournalBatchItem> = {}): JournalBatchItem {
  return {
    issn_l: "0034-4257",
    title: "Remote Sensing",
    publisher_name: "Elsevier",
    publisher_canonical: "Elsevier",
    deal_covered: true,
    deal_cap_reached: false,
    deals: [{ id: 1, publisher_name: "Elsevier", duration_text: null }],
    oa_type: "hybrid",
    is_oa: false,
    is_in_doaj: false,
    in_scimago: false,
    apc_stats: [],
    apc_source: "openalex",
    apc_currency: "EUR",
    apc_price: 2200,
    apc_low: null,
    apc_high: null,
    quartile: "Q1",
    works: 12,
    green_oa: "accepted",
    ...overrides,
  };
}

describe("shortlist table helpers", () => {
  it("formats DOAJ list prices and OpenAPC paid ranges", () => {
    expect(apcText(makeItem({ apc_source: "doaj", apc_currency: "USD", apc_price: 1500 }))).toBe(
      "$1,500",
    );
    expect(
      apcText(makeItem({ apc_source: "openapc", apc_price: null, apc_low: 900, apc_high: 1400 })),
    ).toBe("€900 to €1,400");
  });

  it("aligns header and row columns when addedAt is absent (shared lists)", () => {
    const rows: ShortlistRow[] = [
      {
        issnL: "0034-4257",
        savedTitle: "Remote Sensing",
        addedAt: null,
        item: makeItem({ apc_source: "openapc", apc_price: null, apc_low: 1200, apc_high: 1200 }),
      },
      {
        issnL: "9999-9999",
        savedTitle: "Missing Journal",
        addedAt: null,
        item: null,
      },
    ];
    const lines = shortlistCsv(rows, LABELS).split("\r\n");
    expect(lines).toHaveLength(3);
    const cols = lines.map((line) => parseCsvLine(line).length);
    expect(cols).toEqual([11, 11, 11]);
    expect(lines[1]).toContain("€1,200 (paid)");
  });

  it("includes the Added column when at least one row has addedAt", () => {
    const rows: ShortlistRow[] = [
      {
        issnL: "0034-4257",
        savedTitle: "Remote Sensing",
        addedAt: "2026-11-25T10:00:00.000Z",
        item: makeItem({ apc_source: "doaj", apc_currency: "EUR", apc_price: 800 }),
      },
    ];
    const lines = shortlistCsv(rows, LABELS).split("\r\n");
    expect(parseCsvLine(lines[0])).toHaveLength(12);
    expect(parseCsvLine(lines[1])).toHaveLength(12);
    expect(lines[1]).toContain("€800");
  });
});

describe("api requests and robots", () => {
  it("encodes issnL in journalWorksRequest and similarRequest", () => {
    expect(journalWorksRequest("ut", "1234/5678", 1).path).toBe("/ut/journals/1234%2F5678/works");
    expect(similarRequest("ut", "1234/5678").path).toBe("/ut/journals/1234%2F5678/similar");
  });

  it("exposes public API documentation endpoints while blocking /api", () => {
    const config = robots();
    const rule = Array.isArray(config.rules) ? config.rules[0] : config.rules;
    expect(rule.allow).toEqual(["/", "/api/v1/api-docs", "/api/v1/openapi.json"]);
    expect(rule.disallow).toEqual(["/admin", "/*/admin", "/api"]);
  });
});
