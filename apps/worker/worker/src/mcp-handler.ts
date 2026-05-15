// src/mcp-handler.ts
import type { JsonRpcRequest, JsonRpcResponse, ToolInfo, AggregatedResponse } from "./types";
import { PROJECT_WEBSITE_URL, RELAY_SERVER_ICONS } from "./types";

/** Interface that the Durable Object will implement */
export interface RelayStub {
  getToolList(mode: string): Promise<ToolInfo[]>;
  handleToolCall(toolName: string, args: Record<string, unknown>): Promise<Record<string, unknown> | AggregatedResponse>;
  isMultiLocation(): Promise<boolean>;
}

function jsonRpcError(id: string | number, code: number, message: string): JsonRpcResponse {
  return { jsonrpc: "2.0", id, error: { code, message } };
}

function jsonRpcResult(id: string | number, result: unknown): JsonRpcResponse {
  return { jsonrpc: "2.0", id, result };
}

export async function handleMcpRequest(
  body: JsonRpcRequest,
  stub: RelayStub,
  mode: string,
): Promise<JsonRpcResponse> {
  const { method, params, id } = body;

  if (method === "initialize") {
    return jsonRpcResult(id, {
      protocolVersion: "2025-03-26",
      serverInfo: {
        name: "unifi-mcp-relay",
        version: "1.0.0",
        websiteUrl: PROJECT_WEBSITE_URL,
        icons: RELAY_SERVER_ICONS,
      },
      capabilities: { tools: {} },
    });
  }

  if (method === "notifications/initialized") {
    // Notification, no response needed — but we return a result for simplicity
    return jsonRpcResult(id, {});
  }

  if (method === "tools/list") {
    const multiLocation = await stub.isMultiLocation();
    const effectiveMode = multiLocation ? "lazy" : mode;
    const tools = await stub.getToolList(effectiveMode);
    return jsonRpcResult(id, { tools });
  }

  if (method === "tools/call") {
    const toolName = (params as Record<string, unknown>)?.name as string;
    const args = ((params as Record<string, unknown>)?.arguments ?? {}) as Record<string, unknown>;

    if (!toolName) {
      return jsonRpcError(id, -32602, "Missing tool name");
    }

    try {
      const result = await stub.handleToolCall(toolName, args);
      return jsonRpcResult(id, {
        content: [{ type: "text", text: JSON.stringify(result) }],
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      return jsonRpcError(id, -32000, msg);
    }
  }

  return jsonRpcError(id, -32601, `Method not found: ${method}`);
}
