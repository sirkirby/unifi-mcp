// src/relay-object.ts
import { DurableObject } from "cloudflare:workers";
import type { RelayStub } from "./mcp-handler";
import { handleMcpRequest } from "./mcp-handler";
import { hashToken, generateToken, extractBearerToken, validateBearerToken } from "./auth";
import { collectIncidentEvidence } from "./incident-evidence";
import { buildToolIndexResponse, TOOL_INDEX_META_TOOL, toolInputSchema, toolServerOrigin } from "./tool-info";
import type {
  Env,
  ToolInfo,
  ToolAnnotations,
  RegisterMessage,
  ToolCallResponse,
  CatalogUpdateMessage,
  InboundMessage,
  RegisteredMessage,
  ToolCallRequest,
  HeartbeatAckMessage,
  ErrorMessage,
  PendingRequest,
  FanOutResult,
  AggregatedResponse,
  EvidenceTarget,
  AgentScope,
  JsonRpcRequest,
} from "./types";
import { FULL_AGENT_SCOPE, MAX_AGENT_TOKEN_NAME_LENGTH, PROTOCOL_VERSION, TOOL_CALL_TIMEOUT_MS } from "./types";
import LOCATION_TIMELINE_TOOL from "./location-timeline-tool.json";

// ---------------------------------------------------------------------------
// Meta-tool definitions (virtual tools served by the relay itself)
// ---------------------------------------------------------------------------

const MAX_LOCATION_NAME_LENGTH = 128;

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const META_TOOL_EXECUTE: ToolInfo = {
  name: "unifi_execute",
  title: "UniFi Execute",
  description:
    "Execute a UniFi tool by name. Use unifi_tool_index to discover available tools first. " +
    "Pass the tool name and its arguments.",
  inputSchema: {
    type: "object",
    properties: {
      tool: { type: "string", description: "Name of the tool to execute" },
      arguments: {
        type: "object",
        description: "Arguments to pass to the tool",
        additionalProperties: true,
      },
      __location: {
        type: "string",
        description: "Target location ID (required for multi-location write operations)",
      },
    },
    required: ["tool"],
  },
  annotations: {
    readOnlyHint: false,
    destructiveHint: false,
    idempotentHint: false,
    openWorldHint: false,
  },
};

const META_TOOL_BATCH: ToolInfo = {
  name: "unifi_batch",
  title: "UniFi Batch",
  description:
    "Execute multiple UniFi tools in a single request. Each call is an object with " +
    "'tool' and 'arguments'. Results are returned in order.",
  inputSchema: {
    type: "object",
    properties: {
      calls: {
        type: "array",
        items: {
          type: "object",
          properties: {
            tool: { type: "string" },
            arguments: { type: "object", additionalProperties: true },
            __location: { type: "string" },
          },
          required: ["tool"],
        },
        description: "Array of tool calls to execute",
      },
    },
    required: ["calls"],
  },
  annotations: {
    readOnlyHint: false,
    destructiveHint: false,
    idempotentHint: false,
    openWorldHint: false,
  },
};

// Defined in JSON so repository checks read the schema the worker serves.
const META_TOOL_LOCATION_TIMELINE: ToolInfo = LOCATION_TIMELINE_TOOL;

const META_TOOLS: ToolInfo[] = [
  TOOL_INDEX_META_TOOL,
  META_TOOL_EXECUTE,
  META_TOOL_BATCH,
  META_TOOL_LOCATION_TIMELINE,
];

// ---------------------------------------------------------------------------
// Agent scope helpers
// ---------------------------------------------------------------------------

function canSeeLocation(scope: AgentScope, locationId: string): boolean {
  return scope.locations === null || scope.locations.includes(locationId);
}

function locationDenied(locationId: string): Record<string, unknown> {
  return { success: false, error: `Location not available to this agent token: ${locationId}` };
}

function readOnlyDenied(toolName: string): Record<string, unknown> {
  return {
    success: false,
    error: `Tool ${toolName} is not read-only and this agent token is read-only`,
  };
}

// ---------------------------------------------------------------------------
// Relay Durable Object
// ---------------------------------------------------------------------------

export class RelayObject extends DurableObject<Env> implements RelayStub {
  /** location_id -> list of tools registered by that location */
  private locationTools = new Map<string, ToolInfo[]>();
  /** tool_name -> list of location_ids that provide it */
  private toolToLocations = new Map<string, string[]>();
  /** location_id -> active WebSocket for O(1) lookup */
  private locationWebSockets = new Map<string, WebSocket>();
  /** call_id -> pending promise waiting for a tool_result */
  private pending = new Map<string, PendingRequest>();
  /** Whether in-memory state has been rebuilt from SQLite since last wake */
  private stateRebuilt = false;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.ctx.blockConcurrencyWhile(() => this.ensureTables());
  }

  // -------------------------------------------------------------------------
  // SQLite schema
  // -------------------------------------------------------------------------

  private async ensureTables(): Promise<void> {
    this.ctx.storage.sql.exec(`
      CREATE TABLE IF NOT EXISTS locations (
        location_id TEXT PRIMARY KEY,
        location_name TEXT NOT NULL UNIQUE,
        relay_token_hash TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        last_seen INTEGER NOT NULL
      );
    `);
    this.ctx.storage.sql.exec(`
      CREATE TABLE IF NOT EXISTS location_tools (
        location_id TEXT NOT NULL,
        tool_name TEXT NOT NULL,
        title TEXT,
        description TEXT NOT NULL DEFAULT '',
        input_schema TEXT,
        annotations TEXT,
        server_origin TEXT,
        PRIMARY KEY (location_id, tool_name),
        FOREIGN KEY (location_id) REFERENCES locations(location_id)
      );
    `);
    this.ctx.storage.sql.exec(`
      CREATE TABLE IF NOT EXISTS agent_tokens (
        token_id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        token_hash TEXT NOT NULL UNIQUE,
        read_only INTEGER NOT NULL,
        locations TEXT,
        created_at INTEGER NOT NULL
      );
    `);
    this.ensureLocationToolsTitleColumn();
  }

  private ensureLocationToolsTitleColumn(): void {
    const columns = this.ctx.storage.sql.exec(`PRAGMA table_info(location_tools)`).toArray();
    const hasTitle = columns.some((column) => column.name === "title");
    if (!hasTitle) {
      this.ctx.storage.sql.exec(`ALTER TABLE location_tools ADD COLUMN title TEXT`);
    }
  }

  // -------------------------------------------------------------------------
  // In-memory state rebuild from SQLite
  // -------------------------------------------------------------------------

  private rebuildInMemoryState(): void {
    this.locationTools.clear();
    this.toolToLocations.clear();

    // Rebuild WebSocket map from hibernation-managed sockets.
    // getWebSockets() documents no iteration order, so a socket that was
    // replaced must be skipped rather than winning by enumeration order.
    this.locationWebSockets.clear();
    for (const ws of this.ctx.getWebSockets()) {
      try {
        const attachment = ws.deserializeAttachment() as { locationId?: string; superseded?: boolean } | null;
        if (attachment?.locationId && !attachment.superseded) {
          this.locationWebSockets.set(attachment.locationId, ws);
        }
      } catch {
        // skip websockets without valid attachment
      }
    }

    // Load all tools grouped by location
    const rows = this.ctx.storage.sql.exec(
      `SELECT lt.location_id, lt.tool_name, lt.title, lt.description, lt.input_schema, lt.annotations, lt.server_origin
       FROM location_tools lt
       JOIN locations l ON lt.location_id = l.location_id`,
    ).toArray();

    for (const row of rows) {
      const locationId = row.location_id as string;
      const tool: ToolInfo = {
        name: row.tool_name as string,
        description: (row.description as string) || "",
      };

      if (row.title) {
        tool.title = row.title as string;
      }
      if (row.input_schema) {
        try {
          tool.inputSchema = JSON.parse(row.input_schema as string);
        } catch {
          // skip invalid schema
        }
      }
      if (row.annotations) {
        try {
          tool.annotations = JSON.parse(row.annotations as string) as ToolAnnotations;
        } catch {
          // skip invalid annotations
        }
      }
      if (row.server_origin) {
        tool.serverOrigin = row.server_origin as string;
      }

      // Add to locationTools
      if (!this.locationTools.has(locationId)) {
        this.locationTools.set(locationId, []);
      }
      this.locationTools.get(locationId)!.push(tool);

      // Add to toolToLocations
      if (!this.toolToLocations.has(tool.name)) {
        this.toolToLocations.set(tool.name, []);
      }
      const locs = this.toolToLocations.get(tool.name)!;
      if (!locs.includes(locationId)) {
        locs.push(locationId);
      }
    }

    this.stateRebuilt = true;
  }

  // -------------------------------------------------------------------------
  // HTTP fetch handler
  // -------------------------------------------------------------------------

  async fetch(request: Request): Promise<Response> {
    if (!this.stateRebuilt) {
      this.rebuildInMemoryState();
    }

    const url = new URL(request.url);
    const path = url.pathname;

    if (path === "/ws") {
      return this.handleWebSocketUpgrade(request);
    }
    if (path === "/mcp" && request.method === "POST") {
      return this.handleMcp(request);
    }
    if (path === "/api/locations" && request.method === "GET") {
      return this.handleGetLocations();
    }
    if (path === "/api/locations/token" && request.method === "POST") {
      return this.handleGenerateToken(request);
    }
    if (path === "/api/agent-tokens" && request.method === "GET") {
      return this.handleListAgentTokens();
    }
    if (path === "/api/agent-tokens" && request.method === "POST") {
      return this.handleCreateAgentToken(request);
    }
    if (path.startsWith("/api/agent-tokens/") && request.method === "DELETE") {
      return this.handleDeleteAgentToken(decodeURIComponent(path.slice("/api/agent-tokens/".length)));
    }
    if (path === "/tools" && request.method === "GET") {
      return this.handleGetTools();
    }

    return new Response("Not found", { status: 404 });
  }

  // -------------------------------------------------------------------------
  // WebSocket upgrade
  // -------------------------------------------------------------------------

  private async handleWebSocketUpgrade(request: Request): Promise<Response> {
    const upgradeHeader = request.headers.get("Upgrade");
    if (!upgradeHeader || upgradeHeader.toLowerCase() !== "websocket") {
      return new Response("Expected WebSocket upgrade", { status: 426 });
    }

    // Pre-authenticate: require a valid Bearer token that matches a registered location
    const token = extractBearerToken(request);
    if (!token) {
      return new Response("Unauthorized: missing Bearer token", { status: 401 });
    }

    const tokenHash = await hashToken(token);
    const rows = this.ctx.storage.sql.exec(
      `SELECT location_id FROM locations WHERE relay_token_hash = ?`,
      tokenHash,
    ).toArray();

    if (rows.length === 0) {
      return new Response("Unauthorized: invalid relay token", { status: 401 });
    }

    const pair = new WebSocketPair();
    const [client, server] = [pair[0], pair[1]];

    // Accept with hibernation API
    this.ctx.acceptWebSocket(server);

    return new Response(null, {
      status: 101,
      webSocket: client,
    });
  }

  // -------------------------------------------------------------------------
  // MCP handler
  // -------------------------------------------------------------------------

  private async handleMcp(request: Request): Promise<Response> {
    // Authenticate before reading the body, so an unauthenticated caller
    // learns nothing from parse errors.
    const scope = await this.resolveAgentScope(request);
    if (!scope) {
      return new Response("Unauthorized", { status: 401 });
    }

    let body: JsonRpcRequest;
    try {
      body = (await request.json()) as JsonRpcRequest;
    } catch {
      return jsonResponse({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } }, 400);
    }

    try {
      const mode = this.env.TOOL_REGISTRATION_MODE || "lazy";
      const result = await handleMcpRequest(body, this, mode, scope);
      if (result === null) {
        return new Response(null, { status: 202 });
      }
      return new Response(JSON.stringify(result), {
        headers: { "Content-Type": "application/json" },
      });
    } catch {
      return new Response(JSON.stringify({ error: "Invalid request" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }
  }

  // -------------------------------------------------------------------------
  // Admin: GET /api/locations
  // -------------------------------------------------------------------------

  private handleGetLocations(): Response {
    const rows = this.ctx.storage.sql.exec(
      `SELECT location_id, location_name, created_at, last_seen FROM locations ORDER BY location_name`,
    ).toArray();

    // Determine which locations are currently connected via WebSocket
    const connectedLocationIds = new Set<string>();
    for (const ws of this.ctx.getWebSockets()) {
      try {
        const attachment = ws.deserializeAttachment() as { locationId?: string } | null;
        if (attachment?.locationId) {
          connectedLocationIds.add(attachment.locationId);
        }
      } catch {
        // skip websockets without valid attachment
      }
    }

    const locations = rows.map((row) => ({
      location_id: row.location_id as string,
      location_name: row.location_name as string,
      created_at: row.created_at as number,
      last_seen: row.last_seen as number,
      connected: connectedLocationIds.has(row.location_id as string),
    }));

    return new Response(JSON.stringify({ locations }), {
      headers: { "Content-Type": "application/json" },
    });
  }

  // -------------------------------------------------------------------------
  // Admin: POST /api/locations/token
  // -------------------------------------------------------------------------

  private async handleGenerateToken(request: Request): Promise<Response> {
    let body: Record<string, unknown>;
    try {
      body = (await request.json()) as Record<string, unknown>;
    } catch {
      return new Response(JSON.stringify({ error: "Invalid JSON body" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    const locationName = body.location_name as string | undefined;
    if (!locationName || typeof locationName !== "string") {
      return new Response(JSON.stringify({ error: "Missing location_name" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    if (locationName.length > MAX_LOCATION_NAME_LENGTH) {
      return new Response(
        JSON.stringify({ error: `location_name exceeds maximum length of ${MAX_LOCATION_NAME_LENGTH} characters` }),
        { status: 400, headers: { "Content-Type": "application/json" } },
      );
    }

    const token = generateToken();
    const tokenHash = await hashToken(token);
    const locationId = crypto.randomUUID();
    const now = Date.now();

    this.ctx.storage.sql.exec(
      `INSERT INTO locations (location_id, location_name, relay_token_hash, created_at, last_seen)
       VALUES (?, ?, ?, ?, ?)
       ON CONFLICT(location_name) DO UPDATE SET
         relay_token_hash = excluded.relay_token_hash,
         last_seen = excluded.last_seen`,
      locationId,
      locationName,
      tokenHash,
      now,
      now,
    );

    // When the conflict fires, the original location_id is preserved.
    // Query back the actual ID so the response is correct.
    const rows = this.ctx.storage.sql.exec(
      `SELECT location_id FROM locations WHERE location_name = ?`,
      locationName,
    ).toArray();
    const actualLocationId = (rows[0]?.location_id as string) || locationId;

    return new Response(
      JSON.stringify({
        location_id: actualLocationId,
        location_name: locationName,
        token,
      }),
      {
        status: 201,
        headers: { "Content-Type": "application/json" },
      },
    );
  }

  // -------------------------------------------------------------------------
  // Agent authorization
  // -------------------------------------------------------------------------

  /**
   * The static AGENT_TOKEN keeps full access. Any other bearer must match a
   * scoped agent token minted through /api/agent-tokens. Returns null when the
   * request carries neither.
   */
  async resolveAgentScope(request: Request): Promise<AgentScope | null> {
    if (this.env.AGENT_TOKEN && validateBearerToken(request, this.env.AGENT_TOKEN)) {
      return FULL_AGENT_SCOPE;
    }

    const token = extractBearerToken(request);
    if (!token) {
      return null;
    }

    const rows = this.ctx.storage.sql.exec(
      `SELECT read_only, locations FROM agent_tokens WHERE token_hash = ?`,
      await hashToken(token),
    ).toArray();
    if (rows.length === 0) {
      return null;
    }

    const locations = rows[0].locations === null ? null : (JSON.parse(rows[0].locations as string) as string[]);
    return { readOnly: rows[0].read_only !== 0, locations };
  }

  // -------------------------------------------------------------------------
  // Admin: /api/agent-tokens
  // -------------------------------------------------------------------------

  private handleListAgentTokens(): Response {
    const rows = this.ctx.storage.sql.exec(
      `SELECT token_id, name, read_only, locations, created_at FROM agent_tokens ORDER BY name`,
    ).toArray();

    const agentTokens = rows.map((row) => ({
      token_id: row.token_id as string,
      name: row.name as string,
      read_only: row.read_only !== 0,
      locations: row.locations === null ? null : (JSON.parse(row.locations as string) as string[]),
      created_at: row.created_at as number,
    }));

    return jsonResponse({ agent_tokens: agentTokens });
  }

  private async handleCreateAgentToken(request: Request): Promise<Response> {
    let body: Record<string, unknown>;
    try {
      body = (await request.json()) as Record<string, unknown>;
    } catch {
      return jsonResponse({ error: "Invalid JSON body" }, 400);
    }
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      return jsonResponse({ error: "Invalid JSON body" }, 400);
    }

    const name = body.name;
    if (typeof name !== "string" || name.length === 0) {
      return jsonResponse({ error: "Missing name" }, 400);
    }
    if (name.length > MAX_AGENT_TOKEN_NAME_LENGTH) {
      return jsonResponse({ error: `name exceeds maximum length of ${MAX_AGENT_TOKEN_NAME_LENGTH} characters` }, 400);
    }

    // Read-only unless the caller explicitly asks for write access.
    const readOnly = body.read_only ?? true;
    if (typeof readOnly !== "boolean") {
      return jsonResponse({ error: "read_only must be a boolean" }, 400);
    }

    let locationIds: string[] | null = null;
    if (body.locations !== undefined && body.locations !== null) {
      const resolved = this.resolveLocationIds(body.locations);
      if ("error" in resolved) {
        return jsonResponse({ error: resolved.error }, 400);
      }
      locationIds = resolved.ids;
    }

    const token = generateToken();
    const tokenHash = await hashToken(token);
    const tokenId = crypto.randomUUID();
    const locationsJson = locationIds === null ? null : JSON.stringify(locationIds);

    // Minting an existing name rotates its secret and replaces its scope.
    this.ctx.storage.sql.exec(
      `INSERT INTO agent_tokens (token_id, name, token_hash, read_only, locations, created_at)
       VALUES (?, ?, ?, ?, ?, ?)
       ON CONFLICT(name) DO UPDATE SET
         token_hash = excluded.token_hash,
         read_only = excluded.read_only,
         locations = excluded.locations`,
      tokenId,
      name,
      tokenHash,
      readOnly ? 1 : 0,
      locationsJson,
      Date.now(),
    );

    const rows = this.ctx.storage.sql.exec(
      `SELECT token_id FROM agent_tokens WHERE name = ?`,
      name,
    ).toArray();

    return jsonResponse(
      {
        token_id: (rows[0]?.token_id as string) || tokenId,
        name,
        read_only: readOnly,
        locations: locationIds,
        token,
      },
      201,
    );
  }

  private handleDeleteAgentToken(idOrName: string): Response {
    // A token ID wins over a name, so a token named after another token's ID
    // cannot redirect a revocation.
    const tokenId = this.lookupByIdThenName(
      `SELECT token_id AS id FROM agent_tokens WHERE token_id = ?`,
      `SELECT token_id AS id FROM agent_tokens WHERE name = ?`,
      idOrName,
    );
    if (tokenId === null) {
      return jsonResponse({ error: "Agent token not found" }, 404);
    }
    this.ctx.storage.sql.exec(`DELETE FROM agent_tokens WHERE token_id = ?`, tokenId);
    return new Response(null, { status: 204 });
  }

  /** Match an exact ID first and fall back to a name only when no ID matches */
  private lookupByIdThenName(byId: string, byName: string, value: string): string | null {
    for (const query of [byId, byName]) {
      const rows = this.ctx.storage.sql.exec(query, value).toArray();
      if (rows.length > 0) {
        return rows[0].id as string;
      }
    }
    return null;
  }

  /** Resolve location IDs or names to registered location IDs */
  private resolveLocationIds(value: unknown): { ids: string[] } | { error: string } {
    if (!Array.isArray(value) || value.length === 0) {
      return { error: "locations must be a non-empty array of location IDs or names" };
    }

    const ids: string[] = [];
    for (const entry of value) {
      if (typeof entry !== "string" || entry.length === 0) {
        return { error: "locations must be a non-empty array of location IDs or names" };
      }
      // An ID wins over a name, so a location named after another location's
      // ID cannot widen or move the scope.
      const id = this.lookupByIdThenName(
        `SELECT location_id AS id FROM locations WHERE location_id = ?`,
        `SELECT location_id AS id FROM locations WHERE location_name = ?`,
        entry,
      );
      if (id === null) {
        return { error: `Unknown location: ${entry}` };
      }
      if (!ids.includes(id)) {
        ids.push(id);
      }
    }
    return { ids };
  }

  // -------------------------------------------------------------------------
  // Internal: GET /tools
  // -------------------------------------------------------------------------

  private handleGetTools(): Response {
    const tools = this.getAggregatedTools();
    return new Response(JSON.stringify({ tools }), {
      headers: { "Content-Type": "application/json" },
    });
  }

  // -------------------------------------------------------------------------
  // WebSocket Hibernation API handlers
  // -------------------------------------------------------------------------

  async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer): Promise<void> {
    const raw = typeof message === "string" ? message : new TextDecoder().decode(message);

    let parsed: InboundMessage;
    try {
      parsed = JSON.parse(raw) as InboundMessage;
    } catch {
      this.sendWs(ws, { type: "error", message: "Invalid JSON", code: "PARSE_ERROR" });
      return;
    }

    switch (parsed.type) {
      case "register":
        await this.handleRegister(ws, parsed as RegisterMessage);
        break;
      case "tool_result":
        this.handleToolResult(ws, parsed as ToolCallResponse);
        break;
      case "catalog_update":
        this.handleCatalogUpdate(ws, parsed as CatalogUpdateMessage);
        break;
      case "heartbeat":
        this.sendWs(ws, { type: "heartbeat_ack" });
        break;
      default:
        this.sendWs(ws, {
          type: "error",
          message: `Unknown message type: ${(parsed as Record<string, unknown>).type}`,
          code: "UNKNOWN_TYPE",
        });
    }
  }

  async webSocketClose(ws: WebSocket, code: number, reason: string, wasClean: boolean): Promise<void> {
    this.cleanupWebSocket(ws);
  }

  async webSocketError(ws: WebSocket, error: unknown): Promise<void> {
    this.cleanupWebSocket(ws);
  }

  // -------------------------------------------------------------------------
  // WebSocket message handlers
  // -------------------------------------------------------------------------

  private async handleRegister(ws: WebSocket, msg: RegisterMessage): Promise<void> {
    // Validate protocol version
    if (msg.protocol_version !== PROTOCOL_VERSION) {
      this.sendWs(ws, {
        type: "error",
        message: `Unsupported protocol version: ${msg.protocol_version}, expected ${PROTOCOL_VERSION}`,
        code: "PROTOCOL_MISMATCH",
      });
      return;
    }

    // Validate location name
    if (msg.location_name && msg.location_name.length > MAX_LOCATION_NAME_LENGTH) {
      this.sendWs(ws, {
        type: "error",
        message: `location_name exceeds maximum length of ${MAX_LOCATION_NAME_LENGTH} characters`,
        code: "INVALID_INPUT",
      });
      return;
    }

    // Hash the incoming token and look up matching location
    const incomingHash = await hashToken(msg.token);

    const rows = this.ctx.storage.sql.exec(
      `SELECT location_id, location_name, relay_token_hash FROM locations WHERE relay_token_hash = ?`,
      incomingHash,
    ).toArray();

    if (rows.length === 0) {
      this.sendWs(ws, {
        type: "error",
        message: "Invalid relay token",
        code: "AUTH_FAILED",
      });
      return;
    }

    const locationId = rows[0].location_id as string;
    const locationName = rows[0].location_name as string;
    const now = Date.now();

    // Update last_seen and location_name (relay client may update its name)
    this.ctx.storage.sql.exec(
      `UPDATE locations SET last_seen = ?, location_name = ? WHERE location_id = ?`,
      now,
      msg.location_name || locationName,
      locationId,
    );

    // Replace tools for this location
    this.ctx.storage.sql.exec(`DELETE FROM location_tools WHERE location_id = ?`, locationId);

    for (const tool of msg.tools) {
      this.ctx.storage.sql.exec(
        `INSERT INTO location_tools (location_id, tool_name, title, description, input_schema, annotations, server_origin)
         VALUES (?, ?, ?, ?, ?, ?, ?)`,
        locationId,
        tool.name,
        tool.title || null,
        tool.description || "",
        toolInputSchema(tool) ? JSON.stringify(toolInputSchema(tool)) : null,
        tool.annotations ? JSON.stringify(tool.annotations) : null,
        toolServerOrigin(tool) || null,
      );
    }

    // Attach location_id to the WebSocket before rebuilding so this socket is
    // identifiable and can be preferred over any superseded connection.
    ws.serializeAttachment({ locationId, locationName: msg.location_name || locationName });

    // Retire any other socket still bound to this location so a later
    // in-memory rebuild cannot route calls back to a stale connection.
    this.retireSupersededSockets(locationId, ws);

    // Rebuild in-memory state
    this.rebuildInMemoryState();

    // Cache the WebSocket for O(1) lookup
    this.locationWebSockets.set(locationId, ws);

    // Send confirmation
    const response: RegisteredMessage = {
      type: "registered",
      location_id: locationId,
      location_name: msg.location_name || locationName,
    };
    this.sendWs(ws, response);
  }

  private handleToolResult(ws: WebSocket, msg: ToolCallResponse): void {
    const pending = this.pending.get(msg.call_id);
    if (!pending) {
      // Stale or duplicate result, ignore
      return;
    }

    // Verify the sender is the location that received the original tool_call
    try {
      const attachment = ws.deserializeAttachment() as { locationId?: string } | null;
      if (attachment?.locationId && attachment.locationId !== pending.locationId) {
        // Result from a different location than expected — reject it
        return;
      }
    } catch {
      // No attachment — unregistered WebSocket, ignore
      return;
    }

    clearTimeout(pending.timeout);
    this.pending.delete(msg.call_id);

    if (msg.error) {
      pending.reject(new Error(msg.error));
    } else {
      pending.resolve(msg.result);
    }
  }

  private handleCatalogUpdate(ws: WebSocket, msg: CatalogUpdateMessage): void {
    const attachment = ws.deserializeAttachment() as { locationId?: string } | null;
    if (!attachment?.locationId) {
      this.sendWs(ws, {
        type: "error",
        message: "Must register before sending catalog updates",
        code: "NOT_REGISTERED",
      });
      return;
    }

    const locationId = attachment.locationId;

    // Replace tools for this location
    this.ctx.storage.sql.exec(`DELETE FROM location_tools WHERE location_id = ?`, locationId);

    for (const tool of msg.tools) {
      this.ctx.storage.sql.exec(
        `INSERT INTO location_tools (location_id, tool_name, title, description, input_schema, annotations, server_origin)
         VALUES (?, ?, ?, ?, ?, ?, ?)`,
        locationId,
        tool.name,
        tool.title || null,
        tool.description || "",
        toolInputSchema(tool) ? JSON.stringify(toolInputSchema(tool)) : null,
        tool.annotations ? JSON.stringify(tool.annotations) : null,
        toolServerOrigin(tool) || null,
      );
    }

    // Rebuild in-memory state
    this.rebuildInMemoryState();

    // Update last_seen
    this.ctx.storage.sql.exec(
      `UPDATE locations SET last_seen = ? WHERE location_id = ?`,
      Date.now(),
      locationId,
    );
  }

  private cleanupWebSocket(ws: WebSocket): void {
    try {
      const attachment = ws.deserializeAttachment() as { locationId?: string } | null;
      if (attachment?.locationId) {
        // Remove from WebSocket cache -- location is no longer routable.
        // Only clear the binding when this socket is still the active route:
        // a superseded connection closing late must not remove its replacement.
        // In-memory tool state stays (tools are still in SQLite) so the
        // location will become routable again when it reconnects.
        if (this.locationWebSockets.get(attachment.locationId) === ws) {
          this.locationWebSockets.delete(attachment.locationId);
        }
      }
    } catch {
      // No attachment, nothing to clean up
    }
  }

  /**
   * Mark any previously registered socket for a location as superseded and
   * close it. The attachment is durable across hibernation, so a later
   * rebuildInMemoryState() will not resurrect the stale connection as the
   * active route.
   */
  private retireSupersededSockets(locationId: string, current: WebSocket): void {
    for (const ws of this.ctx.getWebSockets()) {
      if (ws === current) {
        continue;
      }
      try {
        const attachment = ws.deserializeAttachment() as { locationId?: string } | null;
        if (attachment?.locationId !== locationId) {
          continue;
        }
        ws.serializeAttachment({ ...attachment, locationId, superseded: true });
        try {
          ws.close(1000, "superseded by a newer registration");
        } catch {
          // Socket may already be closing.
        }
      } catch {
        // No attachment, not a registered socket for this location.
      }
    }
  }

  // -------------------------------------------------------------------------
  // RelayStub interface implementation
  // -------------------------------------------------------------------------

  async getToolList(mode: string, scope: AgentScope = FULL_AGENT_SCOPE): Promise<ToolInfo[]> {
    if (mode === "lazy" || mode === "meta_only") {
      return META_TOOLS;
    }

    // eager mode: return all deduplicated tools the caller can reach
    return this.getAggregatedTools(scope);
  }

  async handleToolCall(
    toolName: string,
    args: Record<string, unknown>,
    scope: AgentScope = FULL_AGENT_SCOPE,
  ): Promise<Record<string, unknown> | AggregatedResponse> {
    // Handle meta-tools
    if (toolName === "unifi_tool_index") {
      return this.handleToolIndex(args, scope);
    }
    if (toolName === "unifi_execute") {
      return this.handleExecute(args, scope);
    }
    if (toolName === "unifi_batch") {
      return this.handleBatch(args, scope);
    }
    if (toolName === "unifi_location_timeline") {
      return this.handleLocationTimeline(args, scope);
    }

    // Direct tool call (eager mode)
    return this.routeToolCall(toolName, args, scope);
  }

  async isMultiLocation(scope: AgentScope = FULL_AGENT_SCOPE): Promise<boolean> {
    return this.visibleCatalog(scope).locationTools.size > 1;
  }

  // -------------------------------------------------------------------------
  // Meta-tool handlers
  // -------------------------------------------------------------------------

  private handleToolIndex(args: Record<string, unknown>, scope: AgentScope): Record<string, unknown> {
    const catalog = this.visibleCatalog(scope);
    return buildToolIndexResponse(catalog.locationTools, catalog.toolToLocations, args);
  }

  private async handleExecute(
    args: Record<string, unknown>,
    scope: AgentScope,
  ): Promise<Record<string, unknown> | AggregatedResponse> {
    const toolName = args.tool as string;
    if (!toolName) {
      return { success: false, error: "Missing required argument: tool" };
    }

    const toolArgs = (args.arguments as Record<string, unknown>) || {};
    const location = args.__location as string | undefined;
    if (location) {
      toolArgs.__location = location;
    }

    return this.routeToolCall(toolName, toolArgs, scope);
  }

  private async handleBatch(args: Record<string, unknown>, scope: AgentScope): Promise<Record<string, unknown>> {
    const calls = args.calls as Array<{ tool: string; arguments?: Record<string, unknown>; __location?: string }>;
    if (!calls || !Array.isArray(calls)) {
      return { success: false, error: "Missing required argument: calls (array)" };
    }

    const settled = await Promise.allSettled(
      calls.map((call) => {
        const callArgs = { ...(call.arguments || {}) };
        if (call.__location) {
          callArgs.__location = call.__location;
        }
        return this.routeToolCall(call.tool, callArgs, scope);
      }),
    );

    const results: Array<{ tool: string; result?: unknown; error?: string }> = settled.map((outcome, i) => {
      if (outcome.status === "fulfilled") {
        return { tool: calls[i].tool, result: outcome.value };
      }
      const msg = outcome.reason instanceof Error ? outcome.reason.message : "Unknown error";
      return { tool: calls[i].tool, error: msg };
    });

    return { success: true, data: { results, total: results.length } };
  }

  private async handleLocationTimeline(
    args: Record<string, unknown>,
    scope: AgentScope,
  ): Promise<Record<string, unknown>> {
    const products = ["network", "protect"] as const;
    const targets: EvidenceTarget[] = [];
    const locations = this.ctx.storage.sql.exec(`SELECT location_id FROM locations`).toArray();
    for (const row of locations) {
      const locationId = row.location_id as string;
      if (!canSeeLocation(scope, locationId)) {
        continue;
      }
      const tools = this.locationTools.get(locationId) ?? [];
      for (const product of products) {
        const toolName = product === "network" ? "unifi_get_incident_evidence" : "protect_get_incident_evidence";
        targets.push({ location_id: locationId, product, available: tools.some((tool) => tool.name === toolName) });
      }
    }
    return collectIncidentEvidence(args, targets, async (target, tool, parameters) => {
      // The evidence tools are sent directly, not through routeToolCall, so a
      // read-only token gets the same annotation check here. A refusal is
      // reported as that source's permission_denied outcome.
      if (scope.readOnly && !this.isReadOnlyAt(target.location_id, tool)) {
        throw Object.assign(new Error(readOnlyDenied(tool).error as string), { status: 403 });
      }
      const response = await this.sendToolCall(
        target.location_id, tool, parameters, parameters.max_elapsed_ms as number,
      );
      return response.success === true && response.data === null ? null : response;
    });
  }

  // -------------------------------------------------------------------------
  // Tool call routing
  // -------------------------------------------------------------------------

  private async routeToolCall(
    toolName: string,
    args: Record<string, unknown>,
    scope: AgentScope = FULL_AGENT_SCOPE,
  ): Promise<Record<string, unknown> | AggregatedResponse> {
    // A tool that exists only at locations outside the scope reads as missing.
    const locations = (this.toolToLocations.get(toolName) ?? []).filter((id) => canSeeLocation(scope, id));
    if (locations.length === 0) {
      return { success: false, error: `Tool not found: ${toolName}` };
    }

    // An explicit __location is held to the scope on every path, so a token
    // that sees one location cannot name another and have the call land here.
    const targetLocation = args.__location as string | undefined;
    if (targetLocation && !canSeeLocation(scope, targetLocation)) {
      return locationDenied(targetLocation);
    }
    const { __location, ...cleanArgs } = args;

    // Single location: always route directly
    if (this.visibleLocationIds(scope).length === 1) {
      const locationId = locations[0];
      if (scope.readOnly && !this.isReadOnlyAt(locationId, toolName)) {
        return readOnlyDenied(toolName);
      }
      return this.sendToolCall(locationId, toolName, cleanArgs);
    }

    // Multi-location: check if the tool is read-only
    const toolInfo = this.findToolInfo(toolName, locations);
    const isReadOnly = toolInfo?.annotations?.readOnlyHint === true;

    if (isReadOnly) {
      // A read-only token never fans out to a location that annotates the
      // same tool as a write.
      if (scope.readOnly && !locations.every((id) => this.isReadOnlyAt(id, toolName))) {
        return readOnlyDenied(toolName);
      }
      // Fan out to all locations that have this tool
      return this.fanOutToolCall(toolName, args, locations);
    }

    if (scope.readOnly) {
      return readOnlyDenied(toolName);
    }

    // Write tool: requires explicit __location
    if (!targetLocation) {
      // Build a helpful error with available locations
      const locationNames = locations.map((locId) => {
        const nameRow = this.ctx.storage.sql.exec(
          `SELECT location_name FROM locations WHERE location_id = ?`,
          locId,
        ).toArray();
        return { id: locId, name: (nameRow[0]?.location_name as string) || locId };
      });
      return {
        success: false,
        error: `Multi-location write operation requires __location argument. Available locations: ${JSON.stringify(locationNames)}`,
      };
    }

    return this.sendToolCall(targetLocation, toolName, cleanArgs);
  }

  private async sendToolCall(
    locationId: string,
    toolName: string,
    args: Record<string, unknown>,
    timeoutMs: number = TOOL_CALL_TIMEOUT_MS,
  ): Promise<Record<string, unknown>> {
    const ws = this.findWebSocketForLocation(locationId);
    if (!ws) {
      return { success: false, error: `Location ${locationId} is not connected` };
    }

    const callId = crypto.randomUUID();

    const result = await new Promise<unknown>((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pending.delete(callId);
        reject(new DOMException("Tool call timed out", "TimeoutError"));
      }, timeoutMs);

      this.pending.set(callId, { resolve, reject, timeout, locationId });

      const request: ToolCallRequest = {
        type: "tool_call",
        call_id: callId,
        tool_name: toolName,
        arguments: args,
        timeout_ms: timeoutMs,
      };

      this.sendWs(ws, request);
    });

    // If the result is already a structured response, return it
    if (result && typeof result === "object" && "success" in (result as Record<string, unknown>)) {
      return result as Record<string, unknown>;
    }

    return { success: true, data: result };
  }

  private async fanOutToolCall(
    toolName: string,
    args: Record<string, unknown>,
    locationIds: string[],
  ): Promise<AggregatedResponse> {
    // Remove __location from args if present (not needed for fan-out)
    const { __location, ...cleanArgs } = args;

    const promises = locationIds.map(async (locationId): Promise<FanOutResult> => {
      const ws = this.findWebSocketForLocation(locationId);
      const locationName = this.getLocationName(locationId);

      if (!ws) {
        return { location_id: locationId, location_name: locationName, error: "Not connected" };
      }

      const callId = `${crypto.randomUUID()}-${locationId}`;

      try {
        const result = await new Promise<unknown>((resolve, reject) => {
          const timeout = setTimeout(() => {
            this.pending.delete(callId);
            reject(new Error(`Timed out after ${TOOL_CALL_TIMEOUT_MS}ms`));
          }, TOOL_CALL_TIMEOUT_MS);

          this.pending.set(callId, { resolve, reject, timeout, locationId });

          const request: ToolCallRequest = {
            type: "tool_call",
            call_id: callId,
            tool_name: toolName,
            arguments: cleanArgs,
            timeout_ms: TOOL_CALL_TIMEOUT_MS,
          };

          this.sendWs(ws, request);
        });

        return { location_id: locationId, location_name: locationName, data: result };
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Unknown error";
        return { location_id: locationId, location_name: locationName, error: msg };
      }
    });

    const results = await Promise.allSettled(promises);
    const fanOutResults: FanOutResult[] = results.map((r) => {
      if (r.status === "fulfilled") return r.value;
      return {
        location_id: "unknown",
        location_name: "unknown",
        error: r.reason instanceof Error ? r.reason.message : "Unknown error",
      };
    });

    const responded = fanOutResults.filter((r) => !r.error).length;

    return {
      success: responded > 0,
      results: fanOutResults,
      partial: responded > 0 && responded < locationIds.length,
      locations_total: locationIds.length,
      locations_responded: responded,
    };
  }

  // -------------------------------------------------------------------------
  // Helper methods
  // -------------------------------------------------------------------------

  /** Get deduplicated tools across the caller's locations (for eager mode) */
  getAggregatedTools(scope: AgentScope = FULL_AGENT_SCOPE): ToolInfo[] {
    const seen = new Set<string>();
    const tools: ToolInfo[] = [];

    for (const locationToolList of this.visibleCatalog(scope).locationTools.values()) {
      for (const tool of locationToolList) {
        if (!seen.has(tool.name)) {
          seen.add(tool.name);
          tools.push(tool);
        }
      }
    }

    return tools;
  }

  private findToolInfo(toolName: string, locationIds?: string[]): ToolInfo | undefined {
    for (const [locationId, tools] of this.locationTools) {
      if (locationIds && !locationIds.includes(locationId)) continue;
      const found = tools.find((t) => t.name === toolName);
      if (found) return found;
    }
    return undefined;
  }

  /** Whether the tool as registered at this location is annotated read-only */
  private isReadOnlyAt(locationId: string, toolName: string): boolean {
    const tool = this.locationTools.get(locationId)?.find((t) => t.name === toolName);
    return tool?.annotations?.readOnlyHint === true;
  }

  /** Locations with a registered catalog that the caller may reach */
  private visibleLocationIds(scope: AgentScope): string[] {
    return [...this.locationTools.keys()].filter((id) => canSeeLocation(scope, id));
  }

  /**
   * The catalog as the caller sees it: only its locations, and for a
   * read-only token only the tools annotated readOnlyHint=true.
   */
  private visibleCatalog(scope: AgentScope): {
    locationTools: Map<string, ToolInfo[]>;
    toolToLocations: Map<string, string[]>;
  } {
    if (scope.locations === null && !scope.readOnly) {
      return { locationTools: this.locationTools, toolToLocations: this.toolToLocations };
    }

    const locationTools = new Map<string, ToolInfo[]>();
    const toolToLocations = new Map<string, string[]>();
    for (const [locationId, tools] of this.locationTools) {
      if (!canSeeLocation(scope, locationId)) continue;
      const visible = scope.readOnly ? tools.filter((t) => t.annotations?.readOnlyHint === true) : tools;
      locationTools.set(locationId, visible);
      for (const tool of visible) {
        const locs = toolToLocations.get(tool.name) ?? [];
        if (!locs.includes(locationId)) locs.push(locationId);
        toolToLocations.set(tool.name, locs);
      }
    }
    return { locationTools, toolToLocations };
  }

  private findWebSocketForLocation(locationId: string): WebSocket | null {
    return this.locationWebSockets.get(locationId) ?? null;
  }

  private getLocationName(locationId: string): string {
    const rows = this.ctx.storage.sql.exec(
      `SELECT location_name FROM locations WHERE location_id = ?`,
      locationId,
    ).toArray();
    return (rows[0]?.location_name as string) || locationId;
  }

  private sendWs(
    ws: WebSocket,
    msg: RegisteredMessage | ToolCallRequest | HeartbeatAckMessage | ErrorMessage,
  ): void {
    try {
      ws.send(JSON.stringify(msg));
    } catch {
      // WebSocket may already be closed
    }
  }
}
