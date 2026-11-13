import { afterEach, describe, expect, it, vi } from "vitest";

import { beginPageView, initUsageTracking, trackSearch } from "@/lib/usage/tracker";

describe("trackSearch", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.dispatchEvent(new Event("visibilitychange"));
  });

  it("enqueues the measured duration_ms on the flushed search event", () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    initUsageTracking();
    beginPageView("/journals");
    trackSearch({
      query: "crispr",
      results_count: 7,
      duration_ms: 123,
      search_scope: "journals",
    });

    // A hidden tab forces the batch flush through fetch.
    Object.defineProperty(document, "hidden", { value: true, configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/usage/events");
    const body = JSON.parse(init.body as string);
    expect(body.events).toHaveLength(1);
    expect(body.events[0]).toMatchObject({
      type: "search",
      path: "/journals",
      query: "crispr",
      results_count: 7,
      duration_ms: 123,
      search_scope: "journals",
    });
  });
});
