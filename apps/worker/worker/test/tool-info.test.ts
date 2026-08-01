import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  buildToolIndexEntries,
  MAX_TOOL_SEARCH_RESULTS,
  rankToolsBySearch,
  TOOL_INDEX_META_TOOL,
} from "../src/tool-info";
import type { ToolInfo } from "../src/types";

interface SearchFixture {
  tools: ToolInfo[];
  cases: Array<{ search: string; expected: string[] }>;
}

const fixturePath = fileURLToPath(
  String(new URL("../../../../tests/fixtures/tool_search_cases.json", import.meta.url)),
);
const fixture = JSON.parse(readFileSync(fixturePath, "utf8")) as SearchFixture;

describe("rankToolsBySearch", () => {
  for (const testCase of fixture.cases) {
    it(`matches the shared contract for ${JSON.stringify(testCase.search)}`, () => {
      expect(rankToolsBySearch(fixture.tools, testCase.search).map((tool) => tool.name)).toEqual(
        testCase.expected,
      );
    });
  }

  it("prioritizes an exact phrase", () => {
    const tools: ToolInfo[] = [
      { name: "unifi_firewall_policy_update", description: "Modify policy configuration" },
      { name: "unifi_exact_wall_policy", description: "Apply the wall policy update workflow" },
    ];

    expect(rankToolsBySearch(tools, "wall policy update").map((tool) => tool.name)).toEqual([
      "unifi_exact_wall_policy",
      "unifi_firewall_policy_update",
    ]);
  });

  it("does not create an exact phrase across name and description", () => {
    const tools: ToolInfo[] = [
      { name: "unifi_wall_alpha", description: "Configure policy update" },
      { name: "unifi_wall", description: "Policy update settings" },
    ];

    expect(rankToolsBySearch(tools, "wall policy update").map((tool) => tool.name)).toEqual([
      "unifi_wall_alpha",
      "unifi_wall",
    ]);
  });

  it("preserves source order for ties", () => {
    const tools: ToolInfo[] = [
      { name: "unifi_alpha", description: "Inspect client details" },
      { name: "unifi_beta", description: "Inspect client details" },
    ];

    expect(rankToolsBySearch(tools, "inspect client").map((tool) => tool.name)).toEqual([
      "unifi_alpha",
      "unifi_beta",
    ]);
  });

  it("caps broad searches", () => {
    const tools: ToolInfo[] = Array.from({ length: 25 }, (_, index) => ({
      name: `unifi_client_${String(index).padStart(2, "0")}`,
      description: "Inspect a client",
    }));

    expect(rankToolsBySearch(tools, "client").map((tool) => tool.name)).toEqual(
      tools.slice(0, MAX_TOOL_SEARCH_RESULTS).map((tool) => tool.name),
    );
  });
});

describe("buildToolIndexEntries", () => {
  const locationTools = new Map([["location-1", fixture.tools]]);
  const toolToLocations = new Map(fixture.tools.map((tool) => [tool.name, ["location-1"]]));

  it("applies the production catalog search path", () => {
    expect(
      buildToolIndexEntries(locationTools, toolToLocations, { search: "update tx power" }).map(
        (tool) => tool.name,
      ),
    ).toEqual(["unifi_update_device_radio", "unifi_get_device_radio"]);
  });

  it("treats an empty search as no filter", () => {
    expect(buildToolIndexEntries(locationTools, toolToLocations, { search: "" })).toHaveLength(
      fixture.tools.length,
    );
  });
});

describe("TOOL_INDEX_META_TOOL", () => {
  it("describes ranked token search in its public schema", () => {
    const properties = TOOL_INDEX_META_TOOL.inputSchema?.properties as Record<
      string,
      Record<string, unknown>
    >;
    const description = properties.search.description as string;

    expect(description).toContain("token search");
    expect(description).toContain("at most 20");
    expect(description).toContain("no usable terms returns no tools");
  });
});
