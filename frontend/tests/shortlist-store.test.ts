import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import {
  addJournal,
  clearShortlist,
  csvCell,
  csvText,
  parseShareIssns,
  removeJournal,
  saveJournals,
  shareHref,
  useShortlist,
} from "@/lib/shortlist";
import { installMemoryStorage } from "@/tests/helpers/local-storage";

const KEY = "jb_shortlist_ut";

const REMOTE_SENSING = { issnL: "0034-4257", title: "Remote Sensing of Environment" };
const WATER_RESEARCH = { issnL: "0376-7388", title: "Water Resources Research" };

beforeEach(() => {
  // The store caches each institution's list; reset it on the fresh storage.
  installMemoryStorage();
  clearShortlist("ut");
});

describe("saved journals", () => {
  it("adds each journal once and writes the list to localStorage", () => {
    const { result } = renderHook(() => useShortlist("ut"));

    act(() => addJournal("ut", REMOTE_SENSING.issnL, REMOTE_SENSING.title));
    act(() => addJournal("ut", WATER_RESEARCH.issnL, WATER_RESEARCH.title));
    act(() => addJournal("ut", REMOTE_SENSING.issnL, REMOTE_SENSING.title));

    expect(result.current.map((entry) => entry.issnL)).toEqual([
      REMOTE_SENSING.issnL,
      WATER_RESEARCH.issnL,
    ]);
    const stored = JSON.parse(window.localStorage.getItem(KEY) ?? "null") as {
      issnL: string;
      title: string;
    }[];
    expect(stored.map((entry) => entry.issnL)).toEqual([
      REMOTE_SENSING.issnL,
      WATER_RESEARCH.issnL,
    ]);
    expect(stored[0].title).toBe(REMOTE_SENSING.title);
  });

  it("writes a bare ISSN-L in canonical form and ignores text that is not an ISSN", () => {
    const { result } = renderHook(() => useShortlist("ut"));

    act(() => addJournal("ut", "03767388", WATER_RESEARCH.title));
    act(() => addJournal("ut", "not an issn", "Nothing"));

    expect(result.current.map((entry) => entry.issnL)).toEqual([WATER_RESEARCH.issnL]);
  });

  it("drops invalid stored entries and orders a stored list by save date", () => {
    window.localStorage.setItem(
      "jb_shortlist_rug",
      JSON.stringify([
        { ...WATER_RESEARCH, addedAt: "2026-11-25T10:00:00.000Z" },
        { ...REMOTE_SENSING, addedAt: "2026-11-24T10:00:00.000Z" },
        { issnL: REMOTE_SENSING.issnL, title: "Duplicate", addedAt: "2026-11-26T10:00:00.000Z" },
        { issnL: "garbage", title: "Not an ISSN" },
        "not an object",
      ]),
    );
    const { result } = renderHook(() => useShortlist("rug"));

    expect(result.current.map((entry) => [entry.issnL, entry.title])).toEqual([
      [REMOTE_SENSING.issnL, REMOTE_SENSING.title],
      [WATER_RESEARCH.issnL, WATER_RESEARCH.title],
    ]);
  });

  it("treats corrupted storage as an empty list", () => {
    window.localStorage.setItem("jb_shortlist_jnc", "{not json");
    const { result } = renderHook(() => useShortlist("jnc"));

    expect(result.current).toEqual([]);
  });

  it("removes one journal even with bare lowercase input and clears the list", () => {
    const { result } = renderHook(() => useShortlist("ut"));
    act(() => addJournal("ut", REMOTE_SENSING.issnL, REMOTE_SENSING.title));
    act(() => addJournal("ut", WATER_RESEARCH.issnL, WATER_RESEARCH.title));

    act(() => removeJournal("ut", "00344257"));
    expect(result.current.map((entry) => entry.issnL)).toEqual([WATER_RESEARCH.issnL]);

    act(() => clearShortlist("ut"));
    expect(result.current).toEqual([]);
    expect(window.localStorage.getItem(KEY)).toBe("[]");
  });

  it("caps parseShareIssns at 200 unique entries", () => {
    const many = Array.from({ length: 250 }, (_, i) => {
      const n = String(i + 1000000).padStart(7, "0");
      return `${n.slice(0, 4)}-${n.slice(4)}X`;
    }).join(",");
    expect(parseShareIssns(many)).toHaveLength(200);
  });

  it("keeps the list for this page view when storage is blocked", () => {
    window.localStorage.setItem = () => {
      throw new DOMException("QuotaExceededError");
    };
    const { result } = renderHook(() => useShortlist("ut"));

    act(() => addJournal("ut", REMOTE_SENSING.issnL, REMOTE_SENSING.title));

    expect(result.current.map((entry) => entry.issnL)).toEqual([REMOTE_SENSING.issnL]);
  });

  it("reads an empty list when storage access is blocked", () => {
    window.localStorage.getItem = () => {
      throw new DOMException("SecurityError");
    };
    const { result } = renderHook(() => useShortlist("blk"));

    expect(result.current).toEqual([]);
  });
});

describe("share links", () => {
  it("reads the ISSN-Ls of a share link and builds one back", () => {
    const issnLs = parseShareIssns("0034-4257, 03767388,0376-7388,not-an-issn,");

    expect(issnLs).toEqual([REMOTE_SENSING.issnL, WATER_RESEARCH.issnL]);
    expect(shareHref("ut", issnLs)).toBe("/ut/shortlist?j=0034-4257,0376-7388");
    expect(parseShareIssns(null)).toEqual([]);
    expect(parseShareIssns(undefined)).toEqual([]);
  });

  it("saves a shared list without duplicating journals that are saved already", () => {
    const { result } = renderHook(() => useShortlist("ut"));
    act(() => addJournal("ut", REMOTE_SENSING.issnL, REMOTE_SENSING.title));
    const firstAddedAt = result.current[0].addedAt;

    act(() => {
      saveJournals("ut", [REMOTE_SENSING, WATER_RESEARCH, WATER_RESEARCH]);
    });

    expect(result.current.map((entry) => entry.issnL)).toEqual([
      REMOTE_SENSING.issnL,
      WATER_RESEARCH.issnL,
    ]);
    expect(result.current[0].addedAt).toBe(firstAddedAt);
  });
});

describe("other tabs", () => {
  it("follows a storage event for the institution's list and ignores other keys", () => {
    const { result } = renderHook(() => useShortlist("ut"));
    // A browser updates localStorage before it fires the storage event.
    const fromOtherTab = (entries: unknown) => {
      const newValue = JSON.stringify(entries);
      window.localStorage.setItem(KEY, newValue);
      return new StorageEvent("storage", { key: KEY, newValue });
    };

    act(() => {
      window.dispatchEvent(
        fromOtherTab([{ ...REMOTE_SENSING, addedAt: "2026-11-24T10:00:00.000Z" }]),
      );
    });
    expect(result.current.map((entry) => entry.issnL)).toEqual([REMOTE_SENSING.issnL]);

    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", { key: "jb_shortlist_rug", newValue: "[]" }),
      );
    });
    expect(result.current.map((entry) => entry.issnL)).toEqual([REMOTE_SENSING.issnL]);

    act(() => {
      window.dispatchEvent(fromOtherTab([]));
    });
    expect(result.current).toEqual([]);
  });
});

describe("CSV export", () => {
  it("prefixes text a spreadsheet would read as a formula", () => {
    expect(csvCell("=SUM(A1:A2)")).toBe("'=SUM(A1:A2)");
    expect(csvCell("+1|@cmd")).toBe("'+1|@cmd");
    expect(csvCell("-omics: a journal")).toBe("'-omics: a journal");
    expect(csvCell("@risk")).toBe("'@risk");
    expect(csvCell("\t=1")).toBe("'\t=1");
  });

  it("leaves plain text and numbers alone and quotes separators", () => {
    expect(csvCell("Remote Sensing of Environment")).toBe("Remote Sensing of Environment");
    expect(csvCell("Q1, 2024")).toBe('"Q1, 2024"');
    expect(csvCell('The "Journal"')).toBe('"The ""Journal"""');
    expect(csvCell("two\nlines")).toBe('"two\nlines"');
    expect(csvCell(2200)).toBe("2200");
    expect(csvCell(null)).toBe("");
    expect(csvCell(undefined)).toBe("");
    expect(
      csvText(
        ["Journal", "APC"],
        [
          ["=JOURNAL", 2200],
          ["-omics, a title", null],
        ],
      ),
    ).toBe("Journal,APC\r\n'=JOURNAL,2200\r\n\"'-omics, a title\",");
  });
});
