import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchEntityTitle } from "@/lib/entity-title";

describe("fetchEntityTitle", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("resolves to empty metadata instead of throwing when the API call fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network down")));

    await expect(
      fetchEntityTitle<{ name?: string }>("/journals/jb", (d) => d.name),
    ).resolves.toEqual({});
  });
});
