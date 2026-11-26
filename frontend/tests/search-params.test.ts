import { describe, expect, it } from "vitest";

import { publisherDirectoryParams } from "@/app/[inst]/publisher/params";
import { journalsLandingParams } from "@/components/search/params";
import { publishersRequest } from "@/lib/api";

describe("journalsLandingParams multi-select filters", () => {
  it("parses pipe- and comma-delimited multi-select filters and keeps commas inside values", () => {
    const sp = new URLSearchParams({
      quartile: "Q1|Q2",
      topic: "Artificial Intelligence, Robotics|Computational Mechanics",
      publisher: "Elsevier, Inc.|Springer Nature",
      pub_type: "journal|book series",
      green_oa: "submitted|accepted",
      funder_fit: "compliant|check",
      oa_type: "diamond,gold",
      language: "en,de",
    });

    const parsed = journalsLandingParams(sp, "browse");

    expect(parsed.quartiles).toEqual(["Q1", "Q2"]);
    expect(parsed.topics).toEqual(["Artificial Intelligence, Robotics", "Computational Mechanics"]);
    expect(parsed.publishers).toEqual(["Elsevier, Inc.", "Springer Nature"]);
    expect(parsed.pubTypes).toEqual(["journal", "book series"]);
    expect(parsed.greenOas).toEqual(["submitted", "accepted"]);
    expect(parsed.funderFits).toEqual(["compliant", "check"]);
    expect(parsed.oaTypes).toEqual(["diamond", "gold"]);
    expect(parsed.languages).toEqual(["en", "de"]);

    expect(parsed.query.quartile).toBe("Q1|Q2");
    expect(parsed.query.topic).toBe("Artificial Intelligence, Robotics|Computational Mechanics");
    expect(parsed.query.publisher).toBe("Elsevier, Inc.|Springer Nature");
    expect(parsed.query.pub_type).toBe("journal|book series");
    expect(parsed.query.green_oa).toBe("submitted|accepted");
    expect(parsed.query.funder_fit).toBe("compliant|check");
    expect(parsed.query.oa_type).toBe("diamond,gold");
    expect(parsed.query.language).toBe("en,de");
  });

  it("also accepts legacy comma-separated enum values", () => {
    const sp = new URLSearchParams({
      quartile: "Q1,Q3",
      green_oa: "published,none",
      funder_fit: "check,no",
      language: "en|nl",
    });

    const parsed = journalsLandingParams(sp, "browse");

    expect(parsed.quartiles).toEqual(["Q1", "Q3"]);
    expect(parsed.greenOas).toEqual(["published", "none"]);
    expect(parsed.funderFits).toEqual(["check", "no"]);
    expect(parsed.languages).toEqual(["en", "nl"]);
  });
});

describe("publisherDirectoryParams multi-select topic", () => {
  it("parses multiple topics and preserves commas inside topic names", () => {
    const sp = new URLSearchParams({
      topic: "Artificial Intelligence, Robotics|Water Science",
      quartile: "Q1|Q2",
    });

    const state = publisherDirectoryParams(sp);

    expect(state.topics).toEqual(["Artificial Intelligence, Robotics", "Water Science"]);
    expect(state.params.topic).toEqual(["Artificial Intelligence, Robotics", "Water Science"]);
    expect(publishersRequest("ut", state.params).query).toMatchObject({
      topic: "Artificial Intelligence, Robotics|Water Science",
      quartile: "Q1|Q2",
    });
  });
});
