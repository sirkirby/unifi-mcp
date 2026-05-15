// src/types.ts
// All TypeScript interfaces and constants for the UniFi MCP relay worker.

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const PROTOCOL_VERSION = 1;
export const TOOL_CALL_TIMEOUT_MS = 30_000;
export const HEARTBEAT_INTERVAL_MS = 30_000;
export const HEARTBEAT_ACK_TIMEOUT_MS = 10_000;
export const PROJECT_WEBSITE_URL = "https://github.com/sirkirby/unifi-mcp";

export interface IconInfo {
  src: string;
  mimeType?: string;
  sizes?: string[];
}

const RELAY_ICON_SRC =
  "data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%20192%20192%22%3E%3Crect%20width%3D%22192%22%20height%3D%22192%22%20rx%3D%2238%22%20fill%3D%22%23111827%22%2F%3E%3Cpath%20d%3D%22M54%2096h84M96%2054v84%22%20stroke%3D%22%2338bdf8%22%20stroke-width%3D%2214%22%20stroke-linecap%3D%22round%22%2F%3E%3Ccircle%20cx%3D%2254%22%20cy%3D%2296%22%20r%3D%2218%22%20fill%3D%22%2322c55e%22%2F%3E%3Ccircle%20cx%3D%22138%22%20cy%3D%2296%22%20r%3D%2218%22%20fill%3D%22%2322c55e%22%2F%3E%3Ccircle%20cx%3D%2296%22%20cy%3D%2254%22%20r%3D%2218%22%20fill%3D%22%2322c55e%22%2F%3E%3Ccircle%20cx%3D%2296%22%20cy%3D%22138%22%20r%3D%2218%22%20fill%3D%22%2322c55e%22%2F%3E%3C%2Fsvg%3E";

export const RELAY_SERVER_ICONS: IconInfo[] = [
  {
    src: RELAY_ICON_SRC,
    mimeType: "image/svg+xml",
    sizes: ["192x192"],
  },
];

// ---------------------------------------------------------------------------
// Environment (Cloudflare bindings)
// ---------------------------------------------------------------------------

export interface Env {
  RELAY: DurableObjectNamespace;
  AGENT_TOKEN: string;
  ADMIN_TOKEN: string;
  TOOL_REGISTRATION_MODE: string;
}

// ---------------------------------------------------------------------------
// Tool metadata
// ---------------------------------------------------------------------------

export interface ToolAnnotations {
  readOnlyHint?: boolean;
  destructiveHint?: boolean;
  idempotentHint?: boolean;
  openWorldHint?: boolean;
}

export interface ToolInfo {
  name: string;
  title?: string;
  description: string;
  inputSchema?: Record<string, unknown>;
  input_schema?: Record<string, unknown>;
  annotations?: ToolAnnotations;
  serverOrigin?: string;
  server_origin?: string;
}

// ---------------------------------------------------------------------------
// WebSocket messages — relay client → worker (inbound)
// ---------------------------------------------------------------------------

export interface RegisterMessage {
  type: "register";
  protocol_version: number;
  token: string;
  location_name: string;
  tools: ToolInfo[];
  capabilities: string[];
}

export interface ToolCallResponse {
  type: "tool_result";
  call_id: string;
  result?: unknown;
  error?: string;
}

export interface CatalogUpdateMessage {
  type: "catalog_update";
  tools: ToolInfo[];
  capabilities: string[];
}

export interface HeartbeatMessage {
  type: "heartbeat";
}

export type InboundMessage =
  | RegisterMessage
  | ToolCallResponse
  | CatalogUpdateMessage
  | HeartbeatMessage;

// ---------------------------------------------------------------------------
// WebSocket messages — worker → relay client (outbound)
// ---------------------------------------------------------------------------

export interface RegisteredMessage {
  type: "registered";
  location_id: string;
  location_name: string;
}

export interface ToolCallRequest {
  type: "tool_call";
  call_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  timeout_ms: number;
}

export interface HeartbeatAckMessage {
  type: "heartbeat_ack";
}

export interface ErrorMessage {
  type: "error";
  message: string;
  code?: string;
}

export type OutboundMessage =
  | RegisteredMessage
  | ToolCallRequest
  | HeartbeatAckMessage
  | ErrorMessage;

// ---------------------------------------------------------------------------
// MCP JSON-RPC
// ---------------------------------------------------------------------------

export interface JsonRpcRequest {
  jsonrpc: "2.0";
  id: string | number;
  method: string;
  params?: Record<string, unknown>;
}

export interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: string | number;
  result?: unknown;
  error?: unknown;
}

// ---------------------------------------------------------------------------
// Durable Object internal state
// ---------------------------------------------------------------------------

export interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (reason: unknown) => void;
  timeout: ReturnType<typeof setTimeout>;
  locationId: string;
}

export interface LocationInfo {
  locationId: string;
  locationName: string;
  relayTokenHash: string;
  lastSeen: number;
}

// ---------------------------------------------------------------------------
// Fan-out / aggregated responses
// ---------------------------------------------------------------------------

export interface FanOutResult {
  location_id: string;
  location_name: string;
  data?: unknown;
  error?: string;
}

export interface AggregatedResponse {
  success: boolean;
  results: FanOutResult[];
  partial: boolean;
  locations_total: number;
  locations_responded: number;
}
