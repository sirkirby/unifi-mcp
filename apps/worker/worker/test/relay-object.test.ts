// test/relay-object.test.ts
//
// Unit tests for RelayObject pure-logic methods and the RelayStub interface.
// We cannot instantiate a real Durable Object or use SQLite/WebSockets in
// vitest (that requires miniflare), so we test the exported pure functions
// and validate the meta-tool definitions and routing logic indirectly.

import { describe, it, expect, vi } from "vitest";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";
import type { ToolInfo, AggregatedResponse } from "../src/types";
import { FULL_AGENT_SCOPE } from "../src/types";

// ---------------------------------------------------------------------------
// Since RelayObject depends on Cloudflare Durable Object runtime, we extract
// and test the logic that can be exercised without the DO context.
// We import the class type for interface verification and test the RelayStub
// contract through the MCP handler integration.
// ---------------------------------------------------------------------------

import { handleMcpRequest, type RelayStub } from "../src/mcp-handler";
import { buildToolIndexResponse, toolInputSchema, toolServerOrigin } from "../src/tool-info";

// The lifecycle tests below instantiate the real RelayObject with a fake
// Durable Object context, so mock the Cloudflare runtime module the class
// imports. No network or real Cloudflare infrastructure is used.
vi.mock("cloudflare:workers", () => ({ DurableObject: class {} }));
import { RelayObject } from "../src/relay-object";

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
        return buildToolIndexResponse(locationTools, toolToLocations, args);
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
    const tools = await relay.getToolList("lazy", FULL_AGENT_SCOPE);

    expect(tools).toHaveLength(3);
    const names = tools.map((t) => t.name);
    expect(names).toContain("unifi_tool_index");
    expect(names).toContain("unifi_execute");
    expect(names).toContain("unifi_batch");
    expect(tools.find((tool) => tool.name === "unifi_tool_index")?.title).toBe("UniFi Tool Index");
  });

  it("returns meta-tools in meta_only mode", async () => {
    const relay = createMockRelay(new Map([["loc-1", sampleTools()]]));
    const tools = await relay.getToolList("meta_only", FULL_AGENT_SCOPE);

    expect(tools).toHaveLength(3);
    const names = tools.map((t) => t.name);
    expect(names).toContain("unifi_tool_index");
    expect(names).toContain("unifi_execute");
    expect(names).toContain("unifi_batch");
  });

  it("returns all aggregated tools in eager mode", async () => {
    const relay = createMockRelay(new Map([["loc-1", sampleTools()]]));
    const tools = await relay.getToolList("eager", FULL_AGENT_SCOPE);

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

    const tools = await relay.getToolList("eager", FULL_AGENT_SCOPE);
    expect(tools).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// isMultiLocation
// ---------------------------------------------------------------------------
describe("isMultiLocation", () => {
  it("returns false when no locations are registered", async () => {
    const relay = createMockRelay(new Map());
    expect(await relay.isMultiLocation(FULL_AGENT_SCOPE)).toBe(false);
  });

  it("returns false for a single location", async () => {
    const relay = createMockRelay(new Map([["loc-1", sampleTools()]]));
    expect(await relay.isMultiLocation(FULL_AGENT_SCOPE)).toBe(false);
  });

  it("returns true for multiple locations", async () => {
    const relay = createMockRelay(
      new Map([
        ["loc-1", [{ name: "list_clients", description: "List clients" }]],
        ["loc-2", [{ name: "list_devices", description: "List devices" }]],
      ]),
    );
    expect(await relay.isMultiLocation(FULL_AGENT_SCOPE)).toBe(true);
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
    expect(spyGetToolList).toHaveBeenCalledWith("lazy", FULL_AGENT_SCOPE);
    expect(response!.error).toBeUndefined();

    const result = response!.result as Record<string, unknown>;
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

    expect(spyGetToolList).toHaveBeenCalledWith("eager", FULL_AGENT_SCOPE);
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

    expect(response!.error).toBeUndefined();
    const result = response!.result as Record<string, unknown>;
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

    const result = response!.result as Record<string, unknown>;
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

    const result = response!.result as Record<string, unknown>;
    const content = result.content as Array<Record<string, unknown>>;
    const parsed = JSON.parse(content[0].text as string);
    const tools = parsed.data.tools as Array<Record<string, unknown>>;
    expect(tools).toHaveLength(3);
    for (const tool of tools) {
      expect(tool.inputSchema).toBeDefined();
    }
  });

  it("unifi_tool_index name returns the exact tool and rejects combined filters", async () => {
    const relay = createMockRelay(new Map([["loc-1", sampleTools()]]));
    const call = async (args: Record<string, unknown>) => {
      const response = await handleMcpRequest(
        { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "unifi_tool_index", arguments: args } },
        relay,
        "lazy",
      );
      const content = (response!.result as Record<string, unknown>).content as Array<Record<string, unknown>>;
      return JSON.parse(content[0].text as string);
    };

    const named = await call({ name: "list_clients", include_schemas: true });
    expect(named.data.tools.map((tool: Record<string, unknown>) => tool.name)).toEqual(["list_clients"]);
    expect(named.data.tools[0].inputSchema).toBeDefined();

    expect((await call({ name: "List_Clients" })).data.tools).toEqual([]);

    const conflict = await call({ name: "list_clients", category: "" });
    expect(conflict).toEqual({ success: false, error: "Tool index name cannot be combined with category or search." });
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

    const result = response!.result as Record<string, unknown>;
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

    expect(response!.error).toBeUndefined();
    const result = response!.result as Record<string, unknown>;
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
    const tools = await relay.getToolList("lazy", FULL_AGENT_SCOPE);

    for (const tool of tools) {
      expect(tool.annotations).toBeDefined();
      expect(typeof tool.annotations!.readOnlyHint).toBe("boolean");
    }
  });

  it("unifi_tool_index is read-only", async () => {
    const relay = createMockRelay(new Map());
    const tools = await relay.getToolList("lazy", FULL_AGENT_SCOPE);
    const index = tools.find((t) => t.name === "unifi_tool_index");

    expect(index).toBeDefined();
    expect(index!.annotations?.readOnlyHint).toBe(true);
    expect(index!.annotations?.idempotentHint).toBe(true);
  });

  it("unifi_execute and unifi_batch are not read-only", async () => {
    const relay = createMockRelay(new Map());
    const tools = await relay.getToolList("lazy", FULL_AGENT_SCOPE);

    const execute = tools.find((t) => t.name === "unifi_execute");
    const batch = tools.find((t) => t.name === "unifi_batch");

    expect(execute).toBeDefined();
    expect(execute!.annotations?.readOnlyHint).toBe(false);

    expect(batch).toBeDefined();
    expect(batch!.annotations?.readOnlyHint).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// RelayObject WebSocket lifecycle
//
// These tests exercise the real class methods (handleRegister,
// handleCatalogUpdate, rebuildInMemoryState, cleanupWebSocket,
// findWebSocketForLocation) against a minimal in-memory fake of the Durable
// Object state. getWebSockets() documents no iteration order, so the fixture
// deliberately returns the newer socket before the superseded one.
// ---------------------------------------------------------------------------

interface SocketAttachment {
  locationId?: string;
  locationName?: string;
  superseded?: boolean;
}

class FakeSocket {
  attachment: SocketAttachment;
  readyState: number;
  closed = false;
  sent: unknown[] = [];

  constructor(
    public name: string,
    attachment: SocketAttachment,
    readyState = 1,
  ) {
    this.attachment = attachment;
    this.readyState = readyState;
  }

  deserializeAttachment(): SocketAttachment {
    return this.attachment;
  }

  serializeAttachment(value: unknown): void {
    this.attachment = value as SocketAttachment;
  }

  close(): void {
    this.closed = true;
    this.readyState = 2;
  }

  send(data: string): void {
    this.sent.push(JSON.parse(data));
  }
}

function createLifecycleRelay(sockets: FakeSocket[]): any {
  const relay = Object.create(RelayObject.prototype) as any;
  relay.locationTools = new Map();
  relay.toolToLocations = new Map();
  relay.locationWebSockets = new Map();
  relay.pending = new Map();
  relay.stateRebuilt = true;
  relay.ctx = {
    getWebSockets: () => sockets,
    storage: {
      sql: {
        exec: (query: string) => ({
          toArray: () =>
            query.includes("WHERE relay_token_hash = ?")
              ? [{ location_id: "A", location_name: "A", relay_token_hash: "hash" }]
              : [],
        }),
      },
    },
  };
  return relay;
}

async function registerSocket(relay: any, ws: FakeSocket, locationName = "A"): Promise<void> {
  await relay.handleRegister(ws, {
    type: "register",
    protocol_version: 1,
    token: "synthetic-token",
    location_name: locationName,
    tools: [],
  });
}

describe("RelayObject WebSocket lifecycle", () => {
  it("keeps the newest registration when another location rebuilds the catalog", async () => {
    const fresh = new FakeSocket("newer-A", { locationId: "A" });
    const older = new FakeSocket("older-A", { locationId: "A" });
    const other = new FakeSocket("B", { locationId: "B" });
    const relay = createLifecycleRelay([fresh, older, other]);

    await registerSocket(relay, fresh);
    expect(relay.findWebSocketForLocation("A")).toBe(fresh);

    relay.handleCatalogUpdate(other, { type: "catalog_update", tools: [] });

    expect(relay.findWebSocketForLocation("A")).toBe(fresh);
  });

  it("keeps the replacement route when a superseded socket closes late", async () => {
    const fresh = new FakeSocket("newer-A", { locationId: "A" });
    const older = new FakeSocket("older-A", { locationId: "A" });
    const relay = createLifecycleRelay([fresh, older]);

    await registerSocket(relay, fresh);
    expect(relay.findWebSocketForLocation("A")).toBe(fresh);

    // A close/error event for the superseded connection arrives afterwards.
    older.readyState = 3;
    relay.cleanupWebSocket(older);

    expect(relay.findWebSocketForLocation("A")).toBe(fresh);
  });

  it("still clears the route when the active socket closes", async () => {
    const fresh = new FakeSocket("newer-A", { locationId: "A" });
    const relay = createLifecycleRelay([fresh]);

    await registerSocket(relay, fresh);
    expect(relay.findWebSocketForLocation("A")).toBe(fresh);

    fresh.readyState = 3;
    relay.cleanupWebSocket(fresh);

    expect(relay.findWebSocketForLocation("A")).toBeNull();
  });

  it("ignores a superseded CLOSING socket during an in-memory rebuild", () => {
    const fresh = new FakeSocket("newer-A", { locationId: "A" });
    // getWebSockets() may return a CLOSING socket; the superseded marker kept
    // in its attachment must keep it from reclaiming the active route.
    const older = new FakeSocket("older-A", { locationId: "A", superseded: true }, 2);
    const relay = createLifecycleRelay([fresh, older]);
    relay.stateRebuilt = false;

    relay.rebuildInMemoryState();

    expect(relay.findWebSocketForLocation("A")).toBe(fresh);
  });
});

// ---------------------------------------------------------------------------
// Scoped agent tokens
//
// These tests run the real admin handlers, scope resolution and routing
// against an in-memory SQLite database (node:sqlite) standing in for the
// Durable Object's storage. Tool calls stop at sendToolCall/fanOutToolCall,
// which are replaced with spies, so no WebSocket is needed.
// ---------------------------------------------------------------------------

const STATIC_AGENT_TOKEN = "static-agent-token-fixture";

function createScopedRelay(): any {
  const db = new DatabaseSync(":memory:");
  const relay = Object.create(RelayObject.prototype) as any;
  relay.locationTools = new Map();
  relay.toolToLocations = new Map();
  relay.locationWebSockets = new Map();
  relay.pending = new Map();
  relay.stateRebuilt = true;
  relay.env = { AGENT_TOKEN: STATIC_AGENT_TOKEN, TOOL_REGISTRATION_MODE: "lazy" };
  relay.ctx = {
    getWebSockets: () => [],
    storage: {
      sql: {
        exec: (query: string, ...bindings: any[]) => {
          const rows = db.prepare(query).all(...bindings);
          return { toArray: () => rows };
        },
      },
    },
  };
  relay.ensureTables();
  relay.sendToolCall = vi.fn(async (locationId: string, toolName: string) => ({
    success: true,
    data: { locationId, toolName },
  }));
  relay.fanOutToolCall = vi.fn(async (toolName: string, _args: unknown, locationIds: string[]) => ({
    success: true,
    results: locationIds.map((id) => ({ location_id: id, location_name: id, data: toolName })),
    partial: false,
    locations_total: locationIds.length,
    locations_responded: locationIds.length,
  }));
  return relay;
}

function addLocation(relay: any, locationId: string, locationName: string, tools: ToolInfo[]): void {
  relay.ctx.storage.sql.exec(
    `INSERT INTO locations (location_id, location_name, relay_token_hash, created_at, last_seen) VALUES (?, ?, ?, 0, 0)`,
    locationId,
    locationName,
    `hash-${locationId}`,
  );
  relay.locationTools.set(locationId, tools);
  for (const tool of tools) {
    const locs = relay.toolToLocations.get(tool.name) ?? [];
    locs.push(locationId);
    relay.toolToLocations.set(tool.name, locs);
  }
}

function adminRequest(method: string, path: string, body?: unknown): Request {
  return new Request(`https://relay-do${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : typeof body === "string" ? body : JSON.stringify(body),
  });
}

async function mintAgentToken(relay: any, body: Record<string, unknown>): Promise<Record<string, any>> {
  const res: Response = await relay.fetch(adminRequest("POST", "/api/agent-tokens", body));
  expect(res.status).toBe(201);
  return res.json();
}

function bearer(token: string): Request {
  return new Request("https://relay-do/mcp", { method: "POST", headers: { Authorization: `Bearer ${token}` } });
}

describe("scoped agent tokens: admin API", () => {
  it("mints a read-only token for every location by default and lists it without the secret", async () => {
    const relay = createScopedRelay();
    const minted = await mintAgentToken(relay, { name: "dashboards" });

    expect(minted).toMatchObject({ name: "dashboards", read_only: true, locations: null });
    expect(minted.token).toMatch(/^[A-Za-z0-9_-]{43}$/);

    const res: Response = await relay.fetch(adminRequest("GET", "/api/agent-tokens"));
    const listing: any = await res.json();
    expect(listing.agent_tokens).toEqual([
      { token_id: minted.token_id, name: "dashboards", read_only: true, locations: null, created_at: expect.any(Number) },
    ]);
    expect(JSON.stringify(listing)).not.toContain(minted.token);

    expect(await relay.resolveAgentScope(bearer(minted.token))).toEqual({ readOnly: true, locations: null });
  });

  it("resolves location names and IDs to location IDs", async () => {
    const relay = createScopedRelay();
    addLocation(relay, "loc-a", "Home", sampleTools());
    addLocation(relay, "loc-b", "Office", sampleTools());

    const minted = await mintAgentToken(relay, { name: "ops", read_only: false, locations: ["Home", "loc-b", "loc-a"] });

    expect(minted.locations).toEqual(["loc-a", "loc-b"]);
    expect(await relay.resolveAgentScope(bearer(minted.token))).toEqual({ readOnly: false, locations: ["loc-a", "loc-b"] });
  });

  it("resolves an exact location ID before a location named the same", async () => {
    const relay = createScopedRelay();
    // The decoy is stored first, so an unordered ID-or-name match would find it first.
    addLocation(relay, "loc-b", "loc-a", sampleTools());
    addLocation(relay, "loc-a", "Home", sampleTools());

    const minted = await mintAgentToken(relay, { name: "home-only", locations: ["loc-a"] });

    expect(minted.locations).toEqual(["loc-a"]);
    expect(await relay.resolveAgentScope(bearer(minted.token))).toEqual({ readOnly: true, locations: ["loc-a"] });
  });

  it.each([
    [{}, "Missing name"],
    [{ name: "x".repeat(129) }, "maximum length"],
    [{ name: "t", read_only: "false" }, "read_only must be a boolean"],
    [{ name: "t", locations: [] }, "non-empty array"],
    [{ name: "t", locations: "Home" }, "non-empty array"],
    [{ name: "t", locations: ["Nowhere"] }, "Unknown location: Nowhere"],
  ])("refuses %j", async (body, message) => {
    const relay = createScopedRelay();
    addLocation(relay, "loc-a", "Home", sampleTools());

    const res: Response = await relay.fetch(adminRequest("POST", "/api/agent-tokens", body));

    expect(res.status).toBe(400);
    expect(((await res.json()) as any).error).toContain(message);
    const listing = await (await relay.fetch(adminRequest("GET", "/api/agent-tokens"))).json();
    expect(listing.agent_tokens).toEqual([]);
  });

  it("rotates the secret and replaces the scope when a name is minted again", async () => {
    const relay = createScopedRelay();
    addLocation(relay, "loc-a", "Home", sampleTools());
    const first = await mintAgentToken(relay, { name: "ops", read_only: false });
    const second = await mintAgentToken(relay, { name: "ops", locations: ["Home"] });

    expect(second.token_id).toBe(first.token_id);
    expect(await relay.resolveAgentScope(bearer(first.token))).toBeNull();
    expect(await relay.resolveAgentScope(bearer(second.token))).toEqual({ readOnly: true, locations: ["loc-a"] });
  });

  it("revokes a token by ID or name", async () => {
    const relay = createScopedRelay();
    const byId = await mintAgentToken(relay, { name: "one" });
    const byName = await mintAgentToken(relay, { name: "two" });

    expect((await relay.fetch(adminRequest("DELETE", `/api/agent-tokens/${byId.token_id}`))).status).toBe(204);
    expect((await relay.fetch(adminRequest("DELETE", "/api/agent-tokens/two"))).status).toBe(204);
    expect((await relay.fetch(adminRequest("DELETE", "/api/agent-tokens/two"))).status).toBe(404);

    expect(await relay.resolveAgentScope(bearer(byId.token))).toBeNull();
    expect(await relay.resolveAgentScope(bearer(byName.token))).toBeNull();
  });

  it("revokes the token with a matching ID before a token named the same", async () => {
    const relay = createScopedRelay();
    // The decoy is stored first, so an unordered ID-or-name match would find it first.
    const decoy = await mintAgentToken(relay, { name: "decoy" });
    const target = await mintAgentToken(relay, { name: "compromised" });
    relay.ctx.storage.sql.exec(`UPDATE agent_tokens SET name = ? WHERE name = 'decoy'`, target.token_id);

    expect((await relay.fetch(adminRequest("DELETE", `/api/agent-tokens/${target.token_id}`))).status).toBe(204);

    expect(await relay.resolveAgentScope(bearer(target.token))).toBeNull();
    expect(await relay.resolveAgentScope(bearer(decoy.token))).toEqual({ readOnly: true, locations: null });
  });

  it("keeps the static AGENT_TOKEN at full scope and rejects unknown bearers", async () => {
    const relay = createScopedRelay();

    expect(await relay.resolveAgentScope(bearer(STATIC_AGENT_TOKEN))).toEqual(FULL_AGENT_SCOPE);
    expect(await relay.resolveAgentScope(bearer("not-a-token"))).toBeNull();
    expect(await relay.resolveAgentScope(new Request("https://relay-do/mcp", { method: "POST" }))).toBeNull();
  });

  it("does not match an empty AGENT_TOKEN", async () => {
    const relay = createScopedRelay();
    relay.env.AGENT_TOKEN = "";

    expect(await relay.resolveAgentScope(bearer("anything"))).toBeNull();
  });
});

describe("scoped agent tokens: enforcement", () => {
  const readOnly = { readOnly: true, locations: null };

  it("refuses a write tool for a read-only token at a single location and allows a read", async () => {
    const relay = createScopedRelay();
    addLocation(relay, "loc-a", "Home", sampleTools());

    const denied = await relay.handleToolCall("unifi_execute", { tool: "restart_device" }, readOnly);
    const allowed = await relay.handleToolCall("unifi_execute", { tool: "list_clients" }, readOnly);

    expect(denied).toEqual({ success: false, error: expect.stringContaining("read-only") });
    expect(allowed).toMatchObject({ success: true, data: { locationId: "loc-a", toolName: "list_clients" } });
    expect(relay.sendToolCall).toHaveBeenCalledTimes(1);
  });

  it("refuses every write in a batch for a read-only token", async () => {
    const relay = createScopedRelay();
    addLocation(relay, "loc-a", "Home", sampleTools());

    const result = await relay.handleToolCall(
      "unifi_batch",
      { calls: [{ tool: "list_devices" }, { tool: "restart_device" }] },
      readOnly,
    );

    expect(result.data.results[0].result).toMatchObject({ success: true });
    expect(result.data.results[1].result).toEqual({ success: false, error: expect.stringContaining("read-only") });
    expect(relay.sendToolCall).toHaveBeenCalledTimes(1);
  });

  it("refuses a write with __location for a read-only token across locations", async () => {
    const relay = createScopedRelay();
    addLocation(relay, "loc-a", "Home", sampleTools());
    addLocation(relay, "loc-b", "Office", sampleTools());

    const result = await relay.handleToolCall(
      "unifi_execute",
      { tool: "restart_device", __location: "loc-a" },
      readOnly,
    );

    expect(result).toEqual({ success: false, error: expect.stringContaining("read-only") });
    expect(relay.sendToolCall).not.toHaveBeenCalled();
  });

  it("refuses a read-only fan-out when any location annotates the tool as a write", async () => {
    const relay = createScopedRelay();
    addLocation(relay, "loc-a", "Home", sampleTools());
    addLocation(relay, "loc-b", "Office", [
      { name: "list_clients", description: "", annotations: { readOnlyHint: false } },
    ]);

    const result = await relay.handleToolCall("unifi_execute", { tool: "list_clients" }, readOnly);

    expect(result).toEqual({ success: false, error: expect.stringContaining("read-only") });
    expect(relay.fanOutToolCall).not.toHaveBeenCalled();
  });

  it("routes a location-scoped token as a single location and fans out only within the scope", async () => {
    const relay = createScopedRelay();
    addLocation(relay, "loc-a", "Home", sampleTools());
    addLocation(relay, "loc-b", "Office", sampleTools());
    addLocation(relay, "loc-c", "Lab", sampleTools());

    const single = { readOnly: false, locations: ["loc-b"] };
    const write = await relay.handleToolCall("restart_device", {}, single);
    expect(write).toMatchObject({ success: true, data: { locationId: "loc-b" } });

    const pair = { readOnly: false, locations: ["loc-a", "loc-c"] };
    await relay.handleToolCall("list_clients", {}, pair);
    expect(relay.fanOutToolCall).toHaveBeenCalledWith("list_clients", {}, ["loc-a", "loc-c"]);
  });

  it("refuses a write targeted at a location outside the scope", async () => {
    const relay = createScopedRelay();
    addLocation(relay, "loc-a", "Home", sampleTools());
    addLocation(relay, "loc-b", "Office", sampleTools());
    addLocation(relay, "loc-c", "Lab", sampleTools());

    const result = await relay.handleToolCall(
      "unifi_execute",
      { tool: "restart_device", __location: "loc-c" },
      { readOnly: false, locations: ["loc-a", "loc-b"] },
    );

    expect(result).toEqual({ success: false, error: expect.stringContaining("not available to this agent token") });
    expect(relay.sendToolCall).not.toHaveBeenCalled();
  });

  describe("a one-location scope on a two-location deployment", () => {
    const scope = { readOnly: false, locations: ["loc-a"] };

    function twoLocationRelay(): any {
      const relay = createScopedRelay();
      addLocation(relay, "loc-a", "Home", sampleTools());
      addLocation(relay, "loc-b", "Office", sampleTools());
      return relay;
    }

    it.each([
      ["an out-of-scope location", "loc-b"],
      ["an unknown location", "loc-z"],
    ])("refuses a write, a read and a batched call naming %s", async (_label, location) => {
      const relay = twoLocationRelay();
      const denied = { success: false, error: `Location not available to this agent token: ${location}` };

      const write = await relay.handleToolCall("unifi_execute", { tool: "restart_device", __location: location }, scope);
      const read = await relay.handleToolCall("unifi_execute", { tool: "list_clients", __location: location }, scope);
      const direct = await relay.handleToolCall("restart_device", { __location: location }, scope);
      const batch = await relay.handleToolCall(
        "unifi_batch",
        { calls: [{ tool: "restart_device", __location: location }] },
        scope,
      );

      expect(write).toEqual(denied);
      expect(read).toEqual(denied);
      expect(direct).toEqual(denied);
      expect(batch.data.results[0].result).toEqual(denied);
      expect(relay.sendToolCall).not.toHaveBeenCalled();
      expect(relay.fanOutToolCall).not.toHaveBeenCalled();
    });

    it("routes a write with the in-scope __location stripped, and one without __location", async () => {
      const relay = twoLocationRelay();

      const named = await relay.handleToolCall(
        "unifi_execute",
        { tool: "restart_device", arguments: { mac: "aa" }, __location: "loc-a" },
        scope,
      );
      const omitted = await relay.handleToolCall("unifi_execute", { tool: "restart_device", arguments: { mac: "aa" } }, scope);

      expect(named).toMatchObject({ success: true, data: { locationId: "loc-a", toolName: "restart_device" } });
      expect(omitted).toMatchObject({ success: true, data: { locationId: "loc-a", toolName: "restart_device" } });
      expect(relay.sendToolCall.mock.calls).toEqual([
        ["loc-a", "restart_device", { mac: "aa" }],
        ["loc-a", "restart_device", { mac: "aa" }],
      ]);
    });
  });

  it("reports a tool registered only outside the scope as not found", async () => {
    const relay = createScopedRelay();
    addLocation(relay, "loc-a", "Home", sampleTools());
    addLocation(relay, "loc-b", "Office", [{ name: "office_only", description: "", annotations: { readOnlyHint: true } }]);

    const result = await relay.handleToolCall("office_only", {}, { readOnly: false, locations: ["loc-a"] });

    expect(result).toEqual({ success: false, error: "Tool not found: office_only" });
  });

  it("limits the tool index, eager tool list and location count to what the token can call", async () => {
    const relay = createScopedRelay();
    addLocation(relay, "loc-a", "Home", sampleTools());
    addLocation(relay, "loc-b", "Office", [{ name: "office_only", description: "", annotations: { readOnlyHint: true } }]);
    const scope = { readOnly: true, locations: ["loc-a"] };

    const eager = (await relay.getToolList("eager", scope)).map((tool: ToolInfo) => tool.name);
    expect(eager.sort()).toEqual(["list_clients", "list_devices"]);
    expect(await relay.isMultiLocation(scope)).toBe(false);
    expect(await relay.isMultiLocation(FULL_AGENT_SCOPE)).toBe(true);

    const index = JSON.stringify(await relay.handleToolCall("unifi_tool_index", {}, scope));
    expect(index).toContain("list_clients");
    expect(index).not.toContain("restart_device");
    expect(index).not.toContain("office_only");
  });

  it("leaves the static token's routing unchanged", async () => {
    const relay = createScopedRelay();
    addLocation(relay, "loc-a", "Home", sampleTools());
    addLocation(relay, "loc-b", "Office", sampleTools());

    const missing = await relay.handleToolCall("restart_device", {}, FULL_AGENT_SCOPE);
    const targeted = await relay.handleToolCall("restart_device", { __location: "loc-b" }, FULL_AGENT_SCOPE);

    expect(missing).toEqual({ success: false, error: expect.stringContaining("requires __location") });
    expect(targeted).toMatchObject({ success: true, data: { locationId: "loc-b" } });
  });
});

describe("RelayObject /mcp authentication", () => {
  function mcpRequest(body: string, token?: string): Request {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (token) headers.Authorization = `Bearer ${token}`;
    return new Request("https://relay-do/mcp", { method: "POST", headers, body });
  }

  it("rejects a missing or unknown bearer before parsing the body", async () => {
    const relay = createScopedRelay();

    expect((await relay.fetch(mcpRequest("not json"))).status).toBe(401);
    expect((await relay.fetch(mcpRequest("not json", "unknown"))).status).toBe(401);
  });

  it("returns a JSON-RPC parse error to an authenticated caller", async () => {
    const relay = createScopedRelay();

    const res: Response = await relay.fetch(mcpRequest("not json", STATIC_AGENT_TOKEN));

    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } });
  });

  it("applies a scoped token's scope to tools/call", async () => {
    const relay = createScopedRelay();
    addLocation(relay, "loc-a", "Home", sampleTools());
    const minted = await mintAgentToken(relay, { name: "reader" });

    const body = JSON.stringify({ jsonrpc: "2.0", id: 7, method: "tools/call", params: { name: "restart_device" } });
    const res: Response = await relay.fetch(mcpRequest(body, minted.token));
    const rpc: any = await res.json();

    expect(res.status).toBe(200);
    expect(JSON.parse(rpc.result.content[0].text)).toEqual({ success: false, error: expect.stringContaining("read-only") });
    expect(relay.sendToolCall).not.toHaveBeenCalled();
  });
});
