import { afterEach, describe, expect, it, vi } from "vitest";

import { apiGet, authorsRequest, fetchCollaborationMap, getRequest } from "@/lib/api";

describe("authorsRequest query building", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("pipe-joins array filters and skips empty params", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ total: 0 }), {}));
    vi.stubGlobal("fetch", fetchMock);

    await getRequest(
      authorsRequest(
        "ut",
        "smith",
        { faculty: ["fw", "et"], topic: ["a"] },
        {
          sort: "name_asc",
          year_from: 2020,
          year_to: 2025,
          limit: 10,
        },
      ),
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

    await getRequest(authorsRequest("ut"));
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/ut/authors");
  });

  it("forwards an AbortSignal to fetch and suppresses console.error when aborted by caller", async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
      expect(init?.signal).toBeInstanceOf(AbortSignal);
      return Promise.reject(new DOMException("Aborted", "AbortError"));
    });
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal("fetch", fetchMock);

    controller.abort();
    await expect(apiGet("/ut/journals", undefined, controller.signal)).rejects.toThrow();
    expect(errorSpy).not.toHaveBeenCalled();
    errorSpy.mockRestore();
  });
});

describe("fetchCollaborationMap decoding", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("turns each row the API sends into a point with named fields", async () => {
    // ror, name, country_code, city, org_type, lat, lng, works,
    // corresponding_works, home_corresponding_works, oa_share
    const rows = [
      ["01a2b3c04", "Alpha University", "NL", null, "education", 52.2, 6.9, 3, 1, 0, 0.5],
      ["03c4d5e06", "Alpha College", "US", "Alpha", "education", 41, -74, 1, 0, 0, null],
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: rows, unmapped: 2 }), {})),
    );

    const map = await fetchCollaborationMap("ut", {});

    expect(map).toEqual({
      items: [
        {
          ror: "01a2b3c04",
          name: "Alpha University",
          country_code: "NL",
          city: null,
          org_type: "education",
          lat: 52.2,
          lng: 6.9,
          works: 3,
          corresponding_works: 1,
          home_corresponding_works: 0,
          oa_share: 0.5,
        },
        {
          ror: "03c4d5e06",
          name: "Alpha College",
          country_code: "US",
          city: "Alpha",
          org_type: "education",
          lat: 41,
          lng: -74,
          works: 1,
          corresponding_works: 0,
          home_corresponding_works: 0,
          oa_share: null,
        },
      ],
      unmapped: 2,
    });
  });
});
