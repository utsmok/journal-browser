import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it } from "vitest";
import "@testing-library/jest-dom/vitest";

import { PureRegisteredBadge } from "@/components/badges";
import { GapEntryList, GapEntryTableRows, PartsToggle } from "@/components/gap-entries";
import { Table, TableBody } from "@/components/ui/table";
import { entriesTotal, type GapEntry, type GapGroup, type GapSingle } from "@/lib/gap-entries";
import authors from "@/messages/en/authors.json";
import common from "@/messages/en/common.json";

// The gap renderers read the common badges/workParts labels and the
// author-table strings.
function renderWithMessages(ui: React.ReactNode) {
  return render(
    <NextIntlClientProvider locale="en" messages={{ common, authors }}>
      {ui}
    </NextIntlClientProvider>,
  );
}

function single(overrides: Partial<GapSingle> = {}): GapSingle {
  return {
    kind: "single",
    title: "A lone gap work",
    year: 2024,
    doi: "10.1234/lone",
    ut_authors: [],
    parent_works: [],
    is_part: false,
    ...overrides,
  };
}

function group(overrides: Partial<GapGroup> = {}): GapGroup {
  return {
    kind: "group",
    parent: {
      w_id: "W-host",
      name: "Host Book",
      work_type: "book",
      doi: "10.1234/host",
      pure_registered: false,
    },
    parts: [
      {
        title: "Chapter one",
        year: 2024,
        is_part: true,
        ut_authors: [],
        parent_works: [{ id: "W-host", name: "Host Book", rel: "volume" }],
      },
      {
        title: "Chapter two",
        year: 2023,
        is_part: true,
        ut_authors: [],
        parent_works: [{ id: "W-host", name: "Host Book", rel: "volume" }],
      },
    ],
    parts_total: 2,
    ...overrides,
  };
}

afterEach(cleanup);

describe("<PureRegisteredBadge>", () => {
  it.each([
    [true, "In Pure", "text-emerald-700"],
    [false, "Not in Pure", "text-red-700"],
    [null, "Not checked yet", "text-[var(--muted-foreground)]"],
  ] as const)("pure_registered=%s renders %s with %s", (registered, label, colorClass) => {
    renderWithMessages(<PureRegisteredBadge registered={registered} />);
    const badge = screen.getByText(label);
    expect(badge).toBeInTheDocument();
    expect(badge.className).toContain(colorClass);
  });
});

describe("<PartsToggle>", () => {
  it("announces its expanded state", () => {
    const { rerender } = renderWithMessages(
      <PartsToggle open={false} onToggle={() => {}} count={2} />,
    );
    expect(screen.getByRole("button", { name: "2 parts" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );

    rerender(
      <NextIntlClientProvider locale="en" messages={{ common, authors }}>
        <PartsToggle open onToggle={() => {}} count={2} />
      </NextIntlClientProvider>,
    );
    expect(screen.getByRole("button", { name: "2 parts" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("pluralizes the part count", () => {
    renderWithMessages(<PartsToggle open onToggle={() => {}} count={1} />);
    expect(screen.getByRole("button", { name: "1 part" })).toBeInTheDocument();
  });
});

describe("<GapEntryList> singles", () => {
  it("renders a standalone single as a linked row without a foldout", () => {
    renderWithMessages(<GapEntryList entries={[single()]} inst="ut" untitledLabel="Untitled" />);
    const link = screen.getByRole("link", { name: /A lone gap work/ });
    expect(link).toHaveAttribute("href", "https://doi.org/10.1234/lone");
    expect(screen.getByText("2024")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("keeps the part chip on an ungrouped part single", () => {
    renderWithMessages(
      <GapEntryList
        entries={[
          single({
            is_part: true,
            parent_works: [{ id: "W-book", name: "Some Book", rel: null }],
          }),
        ]}
        inst="ut"
        untitledLabel="Untitled"
      />,
    );
    expect(screen.getByText("Part of Some Book")).toBeInTheDocument();
  });
});

describe("<GapEntryList> groups", () => {
  it("renders the group header with parent, type, badge and count, collapsed", () => {
    renderWithMessages(<GapEntryList entries={[group()]} inst="ut" untitledLabel="Untitled" />);
    expect(screen.getByText("Host Book")).toBeInTheDocument();
    expect(screen.getByText("Book")).toBeInTheDocument();
    expect(screen.getByText("Not in Pure")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "2 parts" })).toBeInTheDocument();
    expect(screen.queryByText("Chapter one")).not.toBeInTheDocument();
  });

  it("reveals the parts on toggle and drops their PartChip", () => {
    renderWithMessages(<GapEntryList entries={[group()]} inst="ut" untitledLabel="Untitled" />);
    fireEvent.click(screen.getByRole("button", { name: "2 parts" }));

    expect(screen.getByText("Chapter one")).toBeInTheDocument();
    expect(screen.getByText("Chapter two")).toBeInTheDocument();
    // The group hierarchy makes the chip redundant; its absence is the
    // regression guard.
    expect(screen.queryByText("Part of Host Book")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "2 parts" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("shows the unchecked badge while the parent backfill is pending", () => {
    renderWithMessages(
      <GapEntryList
        entries={[group({ parent: { ...group().parent, pure_registered: null } })]}
        inst="ut"
        untitledLabel="Untitled"
      />,
    );
    expect(screen.getByText("Not checked yet")).toBeInTheDocument();
  });

  it("counts parts_total, not the carried parts, in the foldout label", () => {
    renderWithMessages(
      <GapEntryList entries={[group({ parts_total: 9 })]} inst="ut" untitledLabel="Untitled" />,
    );
    expect(screen.getByRole("button", { name: "9 parts" })).toBeInTheDocument();
  });

  it("falls back to the carried part count without parts_total", () => {
    renderWithMessages(
      <GapEntryList
        entries={[group({ parts_total: undefined })]}
        inst="ut"
        untitledLabel="Untitled"
      />,
    );
    expect(screen.getByRole("button", { name: "2 parts" })).toBeInTheDocument();
  });

  it("renders the untitled label for a parent without a name", () => {
    renderWithMessages(
      <GapEntryList
        entries={[group({ parent: { ...group().parent, name: null, doi: null } })]}
        inst="ut"
        untitledLabel="Untitled work"
      />,
    );
    expect(screen.getByText("Untitled work")).toBeInTheDocument();
  });

  it("keeps singles and groups interleaved in the given order", () => {
    const entries: GapEntry[] = [group(), single({ title: "Second entry" })];
    renderWithMessages(<GapEntryList entries={entries} inst="ut" untitledLabel="Untitled" />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Host Book");
    expect(items[1]).toHaveTextContent("Second entry");
  });
});

describe("<GapEntryTableRows>", () => {
  it("renders a single as one plain row", () => {
    renderWithMessages(
      <Table>
        <TableBody>
          <GapEntryTableRows entries={[single()]} inst="ut" />
        </TableBody>
      </Table>,
    );
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("A lone gap work");
    expect(rows[0]).toHaveTextContent("OpenAlex only");
  });

  it("renders a group as a parent row and reveals part rows on toggle", () => {
    renderWithMessages(
      <Table>
        <TableBody>
          <GapEntryTableRows entries={[group()]} inst="ut" />
        </TableBody>
      </Table>,
    );
    expect(screen.getAllByRole("row")).toHaveLength(1);
    expect(screen.getByText("Host Book")).toBeInTheDocument();
    expect(screen.getByText("Not in Pure")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "2 parts" }));

    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(rows[1]).toHaveTextContent("Chapter one");
    expect(rows[2]).toHaveTextContent("Chapter two");
    // The parent row keeps the badge visible; part rows carry no chip.
    expect(screen.queryByText("Part of Host Book")).not.toBeInTheDocument();
  });

  it("uses the newest part year in the parent row's year column", () => {
    renderWithMessages(
      <Table>
        <TableBody>
          <GapEntryTableRows entries={[group()]} inst="ut" />
        </TableBody>
      </Table>,
    );
    expect(screen.getAllByRole("row")[0]).toHaveTextContent("2024");
  });
});

describe("entriesTotal", () => {
  it("prefers entries_total when the payload carries it", () => {
    expect(entriesTotal({ items: [1, 2, 3], entries_total: 9 })).toBe(9);
  });

  it("falls back to the item count while entries_total is absent", () => {
    expect(entriesTotal({ items: [1, 2, 3] })).toBe(3);
  });
});
