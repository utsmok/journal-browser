import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { patchSearchParams, replaceSearchParams } from "@/lib/url-params";

describe("url-params helpers", () => {
  let replaceSpy: ReturnType<typeof vi.spyOn>;
  let originalPath = "/";

  beforeEach(() => {
    originalPath = `${window.location.pathname}${window.location.search}`;
    replaceSpy = vi.spyOn(window.history, "replaceState").mockImplementation((_s, _t, url) => {
      const next = new URL(String(url), window.location.origin);
      window.history.pushState(null, "", next.pathname + next.search);
    });
  });

  afterEach(() => {
    replaceSpy.mockRestore();
    window.history.pushState(null, "", originalPath);
  });

  it("replaceSearchParams omits trailing ? when params are empty", () => {
    replaceSearchParams("/ut", new URLSearchParams());
    expect(replaceSpy).toHaveBeenCalledWith(null, "", "/ut");

    const params = new URLSearchParams({ oa: "true", quartile: "Q1" });
    replaceSearchParams("/ut", params);
    expect(replaceSpy).toHaveBeenCalledWith(null, "", "/ut?oa=true&quartile=Q1");
  });

  it("patchSearchParams composes rapid sequential updates and drops requested keys", () => {
    window.history.pushState(null, "", "/ut?cursor=abc&p=2&oa=true");

    patchSearchParams("/ut", { doaj: "true" }, { drop: ["cursor", "p"] });
    expect(window.location.search).toBe("?oa=true&doaj=true");

    patchSearchParams("/ut", { oa: undefined, quartile: "Q1" }, { drop: ["cursor", "p"] });
    expect(window.location.search).toBe("?doaj=true&quartile=Q1");
  });
});
