// test/relay-object.test.ts
//
// Unit tests for RelayObject pure-logic methods and the RelayStub interface.
// We cannot instantiate a real Durable Object or use SQLite/WebSockets in
// vitest (that requires miniflare), so we test the exported pure functions
// and validate the meta-tool definitions and routing logic indirectly.

import { describe, it, expect, vi } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { ToolInfo, AggregatedResponse } from "../src/types";

// ---------------------------------------------------------------------------
// Since RelayObject depends on Cloudflare Durable Object runtime, we extract
// and test the logic that can be exercised without the DO context.
// We import the class type for interface verification and test the RelayStub
// contract through the MCP handler integration.
// ---------------------------------------------------------------------------

import { handleMcpRequest, type RelayStub } from "../src/mcp-handler";
import { toolInputSchema, toolServerOrigin } from "../src/tool-info";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Create a minimal RelayStub mock backed by an in-memory tool map */
function createMockRelay(
  locationToolsMap: Map<string, ToolInfo[]> = new Map(),
): RelayStub & {
  locationTools: Map<string, ToolInfo[]>;
  getAggregatedTools: () => ToolInfo[];
} {
  const locationTools = locationToolsMap;

  // Build toolToLocations from locationTools
  const toolToLocations = new Map<string, string[]>();
  for (const [locId, tools] of locationTools) {
    for (const tool of tools) {
      if (!toolToLocations.has(tool.name)) {
        toolToLocations.set(tool.name, []);
      }
      const locs = toolToLocations.get(tool.name)!;
      if (!locs.includes(locId)) {
        locs.push(locId);
      }
    }
  }

  function getAggregatedTools(): ToolInfo[] {
    const seen = new Set<string>();
    const tools: ToolInfo[] = [];
    for (const locationToolList of locationTools.values()) {
      for (const tool of locationToolList) {
        if (!seen.has(tool.name)) {
          seen.add(tool.name);
          tools.push(tool);
        }
      }
    }
    return tools;
  }

  const stub: RelayStub & {
    locationTools: Map<string, ToolInfo[]>;
    getAggregatedTools: () => ToolInfo[];
  } = {
    locationTools,
    getAggregatedTools,

    async getToolList(mode: string): Promise<ToolInfo[]> {
      if (mode === "lazy" || mode === "meta_only") {
        // Return meta-tools
        return [
          {
            name: "unifi_tool_index",
            title: "UniFi Tool Index",
            description: "List all available UniFi tools",
            annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
          },
          {
            name: "unifi_execute",
            title: "UniFi Execute",
            description: "Execute a UniFi tool by name",
            annotations: { readOnlyHint: false, openWorldHint: false },
          },
          {
            name: "unifi_batch",
            title: "UniFi Batch",
            description: "Execute multiple UniFi tools in a single request",
            annotations: { readOnlyHint: false, openWorldHint: false },
          },
        ];
      }
      return getAggregatedTools();
    },

    async handleToolCall(
      toolName: string,
      args: Record<string, unknown>,
    ): Promise<Record<string, unknown> | AggregatedResponse> {
      if (toolName === "unifi_tool_index") {
        const allTools = getAggregatedTools();
        const includeSchemas = Boolean(args.include_schemas);
        let filtered = allTools.map((t) => {
          const entry: Record<string, unknown> = {
            name: t.name,
            description: t.description,
            locations: toolToLocations.get(t.name) || [],
            annotations: t.annotations,
          };
          if (t.title) {
            entry.title = t.title;
          }
          if (includeSchemas && t.inputSchema) {
            entry.inputSchema = t.inputSchema;
          }
          return entry;
        });
        const category = args.category as string | undefined;
        const search = args.search as string | undefined;
        if (category) {
          const cat = category.toLowerCase();
          filtered = filtered.filter(
            (t) =>
              (t.name as string).toLowerCase().includes(cat) ||
              (t.description as string).toLowerCase().includes(cat),
          );
        }
        if (search) {
          const term = search.toLowerCase();
          filtered = filtered.filter(
            (t) =>
              (t.name as string).toLowerCase().includes(term) ||
              (t.description as string).toLowerCase().includes(term),
          );
        }
        return { success: true, data: { tools: filtered, total: filtered.length, multi_location: locationTools.size > 1 } };
      }
      return { success: false, error: `Tool not found: ${toolName}` };
    },

    async isMultiLocation(): Promise<boolean> {
      return locationTools.size > 1;
    },
  };

  return stub;
}

function sampleTools(): ToolInfo[] {
  return [
    {
      name: "list_clients",
      title: "List Clients",
      description: "List all connected clients",
      inputSchema: { type: "object", properties: { site: { type: "string" } } },
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    {
      name: "list_devices",
      title: "List Devices",
      description: "List all network devices",
      inputSchema: { type: "object", properties: { type: { type: "string" } } },
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    {
      name: "restart_device",
      title: "Restart Device",
      description: "Restart a network device",
      inputSchema: { type: "object", properties: { mac: { type: "string" } } },
      annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
    },
  ];
}

function relayRegisterFixture(): Record<string, unknown> {
  const fixturePath = fileURLToPath(
    String(new URL("../../../../tests/fixtures/relay_register_with_metadata.json", import.meta.url)),
  );
  return JSON.parse(
    readFileSync(fixturePath, "utf8"),
  ) as Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// getAggregatedTools
// ---------------------------------------------------------------------------
describe("getAggregatedTools", () => {
  it("returns empty array when no locations are registered", () => {
    const relay = createMockRelay(new Map());
    expect(relay.getAggregatedTools()).toEqual([]);
  });

  it("returns all tools from a single location", () => {
    const tools = sampleTools();
    const relay = createMockRelay(new Map([["loc-1", tools]]));
    const result = relay.getAggregatedTools();
    expect(result).toHaveLength(3);
    expect(result.map((t) => t.name)).toEqual(["list_clients", "list_devices", "restart_device"]);
    expect(result.map((t) => t.title)).toEqual(["List Clients", "List Devices", "Restart Device"]);
  });

  it("deduplicates tools that appear in multiple locations", () => {
    const tools1: ToolInfo[] = [
      { name: "list_clients", description: "List all connected clients" },
      { name: "list_devices", description: "List all network devices" },
    ];
    const tools2: ToolInfo[] = [
      { name: "list_clients", description: "List all connected clients" },
      { name: "get_system_info", description: "Get system information" },
    ];

    const relay = createMockRelay(
      new Map([
        ["loc-1", tools1],
        ["loc-2", tools2],
      ]),
    );

    const result = relay.getAggregatedTools();
    expect(result).toHaveLength(3);
    const names = result.map((t) => t.name);
    expect(names).toContain("list_clients");
    expect(names).toContain("list_devices");
    expect(names).toContain("get_system_info");
  });

  it("keeps the first occurrence when tools are duplicated across locations", () => {
    const tools1: ToolInfo[] = [{ name: "list_clients", description: "From location 1" }];
    const tools2: ToolInfo[] = [{ name: "list_clients", description: "From location 2" }];

    const relay = createMockRelay(
      new Map([
        ["loc-1", tools1],
        ["loc-2", tools2],
      ]),
    );

    const result = relay.getAggregatedTools();
    expect(result).toHaveLength(1);
    expect(result[0].description).toBe("From location 1");
  });

  it("keeps title metadata when tools are aggregated", () => {
    const relay = createMockRelay(
      new Map([["loc-1", [{ name: "list_clients", title: "List Clients", description: "List clients" }]]]),
    );

    expect(relay.getAggregatedTools()[0].title).toBe("List Clients");
  });
});

// ---------------------------------------------------------------------------
// Python relay wire contract
// ---------------------------------------------------------------------------
describe("Python relay wire contract", () => {
  it("accepts relay register tool metadata fields serialized as snake_case", () => {
    const fixture = relayRegisterFixture();
    const tools = fixture.tools as ToolInfo[];
    const tool = tools[0];

    expect(tool.title).toBe("List Devices");
    expect(toolInputSchema(tool)).toEqual({ type: "object", properties: { site: { type: "string" } } });
    expect(toolServerOrigin(tool)).toBe("unifi-network-mcp");
  });
});

// ---------------------------------------------------------------------------
// getToolList
// ---------------------------------------------------------------------------
describe("getToolList", () => {
  it("returns meta-tools in lazy mode", async () => {
    const relay = createMockRelay(new Map([["loc-1", sampleTools()]]));
    const tools = await relay.getToolList("lazy");

    expect(tools).toHaveLength(3);
    const names = tools.map((t) => t.name);
    expect(names).toContain("unifi_tool_index");
    expect(names).toContain("unifi_execute");
    expect(names).toContain("unifi_batch");
    expect(tools.find((tool) => tool.name === "unifi_tool_index")?.title).toBe("UniFi Tool Index");
  });

  it("returns meta-tools in meta_only mode", async () => {
    const relay = createMockRelay(new Map([["loc-1", sampleTools()]]));
    const tools = await relay.getToolList("meta_only");

    expect(tools).toHaveLength(3);
    const names = tools.map((t) => t.name);
    expect(names).toContain("unifi_tool_index");
    expect(names).toContain("unifi_execute");
    expect(names).toContain("unifi_batch");
  });

  it("returns all aggregated tools in eager mode", async () => {
    const relay = createMockRelay(new Map([["loc-1", sampleTools()]]));
    const tools = await relay.getToolList("eager");

    expect(tools).toHaveLength(3);
    const names = tools.map((t) => t.name);
    expect(names).toContain("list_clients");
    expect(names).toContain("list_devices");
    expect(names).toContain("restart_device");
  });

  it("returns deduplicated tools in eager mode for multi-location", async () => {
    const tools1: ToolInfo[] = [{ name: "list_clients", description: "List clients" }];
    const tools2: ToolInfo[] = [
      { name: "list_clients", description: "List clients" },
      { name: "list_devices", description: "List devices" },
    ];

    const relay = createMockRelay(
      new Map([
        ["loc-1", tools1],
        ["loc-2", tools2],
      ]),
    );

    const tools = await relay.getToolList("eager");
    expect(tools).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// isMultiLocation
// ---------------------------------------------------------------------------
describe("isMultiLocation", () => {
  it("returns false when no locations are registered", async () => {
    const relay = createMockRelay(new Map());
    expect(await relay.isMultiLocation()).toBe(false);
  });

  it("returns false for a single location", async () => {
    const relay = createMockRelay(new Map([["loc-1", sampleTools()]]));
    expect(await relay.isMultiLocation()).toBe(false);
  });

  it("returns true for multiple locations", async () => {
    const relay = createMockRelay(
      new Map([
        ["loc-1", [{ name: "list_clients", description: "List clients" }]],
        ["loc-2", [{ name: "list_devices", description: "List devices" }]],
      ]),
    );
    expect(await relay.isMultiLocation()).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// MCP handler integration with RelayStub
// ---------------------------------------------------------------------------
describe("MCP handler with relay stub", () => {
  it("tools/list forces lazy mode for multi-location", async () => {
    const relay = createMockRelay(
      new Map([
        ["loc-1", sampleTools()],
        ["loc-2", sampleTools()],
      ]),
    );

    const spyGetToolList = vi.spyOn(relay, "getToolList");

    const response = await handleMcpRequest(
      { jsonrpc: "2.0", id: 1, method: "tools/list" },
      relay,
      "eager",
    );

    // Multi-location should force lazy mode regardless of the mode param
    expect(spyGetToolList).toHaveBeenCalledWith("lazy");
    expect(response.error).toBeUndefined();

    const result = response.result as Record<string, unknown>;
    const tools = result.tools as ToolInfo[];
    expect(tools).toHaveLength(3);
    expect(tools.map((t) => t.name)).toContain("unifi_tool_index");
  });

  it("tools/list uses the configured mode for single location", async () => {
    const relay = createMockRelay(new Map([["loc-1", sampleTools()]]));
    const spyGetToolList = vi.spyOn(relay, "getToolList");

    await handleMcpRequest(
      { jsonrpc: "2.0", id: 1, method: "tools/list" },
      relay,
      "eager",
    );

    expect(spyGetToolList).toHaveBeenCalledWith("eager");
  });

  it("tools/call dispatches unifi_tool_index and returns tool catalog", async () => {
    const relay = createMockRelay(new Map([["loc-1", sampleTools()]]));

    const response = await handleMcpRequest(
      {
        jsonrpc: "2.0",
        id: 1,
        method: "tools/call",
        params: { name: "unifi_tool_index", arguments: {} },
      },
      relay,
      "lazy",
    );

    expect(response.error).toBeUndefined();
    const result = response.result as Record<string, unknown>;
    const content = result.content as Array<Record<string, unknown>>;
    expect(content).toHaveLength(1);

    const parsed = JSON.parse(content[0].text as string);
    expect(parsed.success).toBe(true);
    expect(parsed.data.tools).toHaveLength(3);
    expect(parsed.data.tools[0].title).toBe("List Clients");
    expect(parsed.data.multi_location).toBe(false);
  });

  it("unifi_tool_index omits schemas by default", async () => {
    const relay = createMockRelay(new Map([["loc-1", sampleTools()]]));

    const response = await handleMcpRequest(
      {
        jsonrpc: "2.0",
        id: 1,
        method: "tools/call",
        params: { name: "unifi_tool_index", arguments: {} },
      },
      relay,
      "lazy",
    );

    const result = response.result as Record<string, unknown>;
    const content = result.content as Array<Record<string, unknown>>;
    const parsed = JSON.parse(content[0].text as string);
    const tools = parsed.data.tools as Array<Record<string, unknown>>;
    expect(tools).toHaveLength(3);
    for (const tool of tools) {
      expect(tool.inputSchema).toBeUndefined();
    }
  });

  it("unifi_tool_index includes schemas when include_schemas=true", async () => {
    const relay = createMockRelay(new Map([["loc-1", sampleTools()]]));

    const response = await handleMcpRequest(
      {
        jsonrpc: "2.0",
        id: 1,
        method: "tools/call",
        params: { name: "unifi_tool_index", arguments: { include_schemas: true } },
      },
      relay,
      "lazy",
    );

    const result = response.result as Record<string, unknown>;
    const content = result.content as Array<Record<string, unknown>>;
    const parsed = JSON.parse(content[0].text as string);
    const tools = parsed.data.tools as Array<Record<string, unknown>>;
    expect(tools).toHaveLength(3);
    for (const tool of tools) {
      expect(tool.inputSchema).toBeDefined();
    }
  });

  it("unifi_tool_index category filter narrows results", async () => {
    const relay = createMockRelay(new Map([["loc-1", sampleTools()]]));

    const response = await handleMcpRequest(
      {
        jsonrpc: "2.0",
        id: 1,
        method: "tools/call",
        params: { name: "unifi_tool_index", arguments: { search: "client" } },
      },
      relay,
      "lazy",
    );

    const result = response.result as Record<string, unknown>;
    const content = result.content as Array<Record<string, unknown>>;
    const parsed = JSON.parse(content[0].text as string);
    expect(parsed.data.tools).toHaveLength(1);
    expect(parsed.data.tools[0].name).toBe("list_clients");
  });

  it("tools/call returns error for unknown tool", async () => {
    const relay = createMockRelay(new Map([["loc-1", sampleTools()]]));

    const response = await handleMcpRequest(
      {
        jsonrpc: "2.0",
        id: 1,
        method: "tools/call",
        params: { name: "nonexistent_tool", arguments: {} },
      },
      relay,
      "lazy",
    );

    expect(response.error).toBeUndefined();
    const result = response.result as Record<string, unknown>;
    const content = result.content as Array<Record<string, unknown>>;
    const parsed = JSON.parse(content[0].text as string);
    expect(parsed.success).toBe(false);
    expect(parsed.error).toContain("not found");
  });
});

// ---------------------------------------------------------------------------
// Meta-tool definitions validation
// ---------------------------------------------------------------------------
describe("meta-tool definitions", () => {
  it("all three meta-tools have valid annotations", async () => {
    const relay = createMockRelay(new Map());
    const tools = await relay.getToolList("lazy");

    for (const tool of tools) {
      expect(tool.annotations).toBeDefined();
      expect(typeof tool.annotations!.readOnlyHint).toBe("boolean");
    }
  });

  it("unifi_tool_index is read-only", async () => {
    const relay = createMockRelay(new Map());
    const tools = await relay.getToolList("lazy");
    const index = tools.find((t) => t.name === "unifi_tool_index");

    expect(index).toBeDefined();
    expect(index!.annotations?.readOnlyHint).toBe(true);
    expect(index!.annotations?.idempotentHint).toBe(true);
  });

  it("unifi_execute and unifi_batch are not read-only", async () => {
    const relay = createMockRelay(new Map());
    const tools = await relay.getToolList("lazy");

    const execute = tools.find((t) => t.name === "unifi_execute");
    const batch = tools.find((t) => t.name === "unifi_batch");

    expect(execute).toBeDefined();
    expect(execute!.annotations?.readOnlyHint).toBe(false);

    expect(batch).toBeDefined();
    expect(batch!.annotations?.readOnlyHint).toBe(false);
  });
});
