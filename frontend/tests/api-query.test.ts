import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchAuthors } from "@/lib/api";

describe("fetchAuthors query building", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("pipe-joins array filters and skips empty params", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ total: 0 }), {}));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAuthors(
      "ut",
      "smith",
      { faculty: ["fw", "et"], topic: ["a"] },
      {
        sort: "name_asc",
        year_from: 2020,
        year_to: 2025,
        limit: 10,
      },
    );

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url.startsWith("/api/v1/ut/authors?")).toBe(true);
    const qs = new URLSearchParams(url.split("?")[1]);
    expect(qs.get("q")).toBe("smith");
    expect(qs.get("faculty")).toBe("fw|et");
    expect(qs.get("topic")).toBe("a");
    expect(qs.get("sort")).toBe("name_asc");
    expect(qs.get("year_from")).toBe("2020");
    expect(qs.get("year_to")).toBe("2025");
    expect(qs.get("limit")).toBe("10");
    expect(qs.has("offset")).toBe(false);
    expect(qs.has("org")).toBe(false);
  });

  it("omits the query string entirely when nothing is set", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ total: 0 }), {}));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAuthors("ut");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/ut/authors");
  });
});
