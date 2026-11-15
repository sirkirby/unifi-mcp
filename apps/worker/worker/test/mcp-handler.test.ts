// test/mcp-handler.test.ts
import { describe, it, expect, vi } from "vitest";
import { handleMcpRequest, type RelayStub } from "../src/mcp-handler";
import type { JsonRpcRequest, ToolInfo } from "../src/types";
import { FULL_AGENT_SCOPE } from "../src/types";

function mockStub(overrides: Partial<RelayStub> = {}): RelayStub {
  return {
    getToolList: vi.fn().mockResolvedValue([]),
    handleToolCall: vi.fn().mockResolvedValue({ success: true }),
    isMultiLocation: vi.fn().mockResolvedValue(false),
    ...overrides,
  };
}

function req(method: string, params?: Record<string, unknown>): JsonRpcRequest {
  return { jsonrpc: "2.0", id: 1, method, params };
}

// ---------------------------------------------------------------------------
// initialize
// ---------------------------------------------------------------------------
describe("initialize", () => {
  it("returns server info with protocol version", async () => {
    const stub = mockStub();
    const response = await handleMcpRequest(req("initialize"), stub, "lazy");

    expect(response!.jsonrpc).toBe("2.0");
    expect(response!.id).toBe(1);
    expect(response!.error).toBeUndefined();

    const result = response!.result as Record<string, unknown>;
    expect(result.protocolVersion).toBe("2025-03-26");
    const serverInfo = result.serverInfo as Record<string, unknown>;
    expect(serverInfo.name).toBe("unifi-mcp-relay");
    expect(serverInfo.version).toBe("1.0.0");
    expect(serverInfo.websiteUrl).toBe("https://github.com/sirkirby/unifi-mcp");
    expect(serverInfo.icons).toEqual([
      expect.objectContaining({
        src: expect.stringMatching(/^data:image\/svg\+xml,/),
        mimeType: "image/svg+xml",
        sizes: ["192x192"],
      }),
    ]);
    expect(result.capabilities).toEqual({ tools: {} });
  });
});

// ---------------------------------------------------------------------------
// notifications/initialized
// ---------------------------------------------------------------------------
describe("notifications", () => {
  it.each(["notifications/initialized", "notifications/cancelled", "notifications/roots/list_changed", "notifications/unknown", "tools/call"])("returns null for idless %s without calling the relay", async (method) => {
    const stub = mockStub();
    const body = { jsonrpc: "2.0" as const, method, params: { requestId: 42, reason: "User cancelled", name: "list_clients" } };
    expect(await handleMcpRequest(body, stub, "lazy")).toBeNull();
    expect(stub.getToolList).not.toHaveBeenCalled();
    expect(stub.handleToolCall).not.toHaveBeenCalled();
    expect(stub.isMultiLocation).not.toHaveBeenCalled();
  });

  it("responds to an unknown request with id zero", async () => {
    const response = await handleMcpRequest({ ...req("notifications/unknown"), id: 0 }, mockStub(), "lazy");
    expect(response).toMatchObject({ id: 0, error: { code: -32601 } });
  });
});

// ---------------------------------------------------------------------------
// tools/list
// ---------------------------------------------------------------------------
describe("tools/list", () => {
  it("calls stub.getToolList with the provided mode when single-location", async () => {
    const tools: ToolInfo[] = [
      { name: "list_clients", title: "List Clients", description: "List all clients" },
    ];
    const stub = mockStub({
      getToolList: vi.fn().mockResolvedValue(tools),
      isMultiLocation: vi.fn().mockResolvedValue(false),
    });

    const response = await handleMcpRequest(req("tools/list"), stub, "eager");

    expect(stub.isMultiLocation).toHaveBeenCalled();
    expect(stub.getToolList).toHaveBeenCalledWith("eager", FULL_AGENT_SCOPE);

    const result = response!.result as Record<string, unknown>;
    expect(result.tools).toEqual(tools);
    expect(response!.error).toBeUndefined();
  });

  it("forces lazy mode when multi-location regardless of mode param", async () => {
    const stub = mockStub({
      getToolList: vi.fn().mockResolvedValue([]),
      isMultiLocation: vi.fn().mockResolvedValue(true),
    });

    await handleMcpRequest(req("tools/list"), stub, "eager");

    expect(stub.getToolList).toHaveBeenCalledWith("lazy", FULL_AGENT_SCOPE);
  });

  it("uses lazy mode when mode param is already lazy (single-location)", async () => {
    const stub = mockStub({
      isMultiLocation: vi.fn().mockResolvedValue(false),
    });

    await handleMcpRequest(req("tools/list"), stub, "lazy");

    expect(stub.getToolList).toHaveBeenCalledWith("lazy", FULL_AGENT_SCOPE);
  });
});

// ---------------------------------------------------------------------------
// tools/call
// ---------------------------------------------------------------------------
describe("tools/call", () => {
  it("forwards tool call to stub and wraps result in MCP content format", async () => {
    const toolResult = { success: true, data: { count: 42 } };
    const stub = mockStub({
      handleToolCall: vi.fn().mockResolvedValue(toolResult),
    });

    const response = await handleMcpRequest(
      req("tools/call", { name: "list_clients", arguments: { site: "default" } }),
      stub,
      "lazy",
    );

    expect(stub.handleToolCall).toHaveBeenCalledWith("list_clients", { site: "default" }, FULL_AGENT_SCOPE);
    expect(response!.error).toBeUndefined();

    const result = response!.result as Record<string, unknown>;
    const content = result.content as Array<Record<string, unknown>>;
    expect(content).toHaveLength(1);
    expect(content[0].type).toBe("text");
    expect(JSON.parse(content[0].text as string)).toEqual(toolResult);
  });

  it("defaults arguments to empty object when not provided", async () => {
    const stub = mockStub();

    await handleMcpRequest(
      req("tools/call", { name: "list_clients" }),
      stub,
      "lazy",
    );

    expect(stub.handleToolCall).toHaveBeenCalledWith("list_clients", {}, FULL_AGENT_SCOPE);
  });

  it("passes the caller's scope to the stub", async () => {
    const stub = mockStub();
    const scope = { readOnly: true, locations: ["loc-1"] };

    await handleMcpRequest(req("tools/list"), stub, "eager", scope);
    await handleMcpRequest(req("tools/call", { name: "list_clients" }), stub, "lazy", scope);

    expect(stub.isMultiLocation).toHaveBeenCalledWith(scope);
    expect(stub.getToolList).toHaveBeenCalledWith("eager", scope);
    expect(stub.handleToolCall).toHaveBeenCalledWith("list_clients", {}, scope);
  });

  it("returns -32000 error when stub throws", async () => {
    const stub = mockStub({
      handleToolCall: vi.fn().mockRejectedValue(new Error("Controller unreachable")),
    });

    const response = await handleMcpRequest(
      req("tools/call", { name: "list_clients", arguments: {} }),
      stub,
      "lazy",
    );

    expect(response!.result).toBeUndefined();
    const error = response!.error as Record<string, unknown>;
    expect(error.code).toBe(-32000);
    expect(error.message).toBe("Controller unreachable");
  });

  it("returns 'Unknown error' when stub throws a non-Error value", async () => {
    const stub = mockStub({
      handleToolCall: vi.fn().mockRejectedValue("raw string error"),
    });

    const response = await handleMcpRequest(
      req("tools/call", { name: "list_clients", arguments: {} }),
      stub,
      "lazy",
    );

    const error = response!.error as Record<string, unknown>;
    expect(error.code).toBe(-32000);
    expect(error.message).toBe("Unknown error");
  });

  it("returns -32602 error when tool name is missing", async () => {
    const stub = mockStub();

    const response = await handleMcpRequest(
      req("tools/call", { arguments: { foo: "bar" } }),
      stub,
      "lazy",
    );

    expect(response!.result).toBeUndefined();
    const error = response!.error as Record<string, unknown>;
    expect(error.code).toBe(-32602);
    expect(error.message).toBe("Missing tool name");
    expect(stub.handleToolCall).not.toHaveBeenCalled();
  });

  it("returns -32602 error when params is undefined", async () => {
    const stub = mockStub();

    const response = await handleMcpRequest(req("tools/call"), stub, "lazy");

    const error = response!.error as Record<string, unknown>;
    expect(error.code).toBe(-32602);
    expect(error.message).toBe("Missing tool name");
  });
});

// ---------------------------------------------------------------------------
// Unknown method
// ---------------------------------------------------------------------------
describe("unknown method", () => {
  it("returns -32601 error for an unrecognized method", async () => {
    const stub = mockStub();

    const response = await handleMcpRequest(req("resources/list"), stub, "lazy");

    expect(response!.result).toBeUndefined();
    const error = response!.error as Record<string, unknown>;
    expect(error.code).toBe(-32601);
    expect((error.message as string)).toContain("resources/list");
  });
});
