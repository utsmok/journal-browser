import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchForRender } from "@/lib/server-fetch";

describe("fetchForRender", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("resolves to null instead of throwing when the API call fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network down")));

    await expect(fetchForRender<{ name?: string }>({ path: "/journals/jb" })).resolves.toBe(null);
  });

  it("resolves to null when the API answers with an error status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("nope", { status: 404 })));

    await expect(fetchForRender({ path: "/journals/jb" })).resolves.toBeNull();
  });

  it("sends the query values the browser fetch would send, and drops empty ones", async () => {
    const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async () =>
      Response.json({ journal: { title: "Remote Sensing of Environment" } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const doc = await fetchForRender<{ journal: { title: string } }>({
      path: "/ut/journals/0034-4257",
      query: { include_gaps: "false", year_from: undefined, funder: null, parts: "" },
    });

    expect(doc?.journal.title).toBe("Remote Sensing of Environment");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "http://localhost:8000/api/v1/ut/journals/0034-4257?include_gaps=false",
    );
    expect(fetchMock.mock.calls[0]?.[1]).toEqual({ next: { revalidate: 300 } });
  });
});
