// src/relay-object.ts
import { DurableObject } from "cloudflare:workers";
import type { RelayStub } from "./mcp-handler";
import { handleMcpRequest } from "./mcp-handler";
import { hashToken, generateToken, extractBearerToken } from "./auth";
import { toolInputSchema, toolServerOrigin } from "./tool-info";
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
} from "./types";
import { PROTOCOL_VERSION, TOOL_CALL_TIMEOUT_MS } from "./types";

// ---------------------------------------------------------------------------
// Meta-tool definitions (virtual tools served by the relay itself)
// ---------------------------------------------------------------------------

const MAX_LOCATION_NAME_LENGTH = 128;

const META_TOOL_INDEX: ToolInfo = {
  name: "unifi_tool_index",
  title: "UniFi Tool Index",
  description:
    "Discover available UniFi tools. Returns names and descriptions by default. " +
    "Use 'category' to filter by area (e.g. clients, firewall, devices), " +
    "'search' for keyword matching, or 'include_schemas' for full parameter schemas. " +
    "Use this to discover tools before calling unifi_execute.",
  inputSchema: {
    type: "object",
    properties: {
      category: {
        type: "string",
        description: "Optional category filter (e.g., 'clients', 'devices', 'firewall')",
      },
      search: {
        type: "string",
        description: "Optional search term to filter tools by name or description",
      },
      include_schemas: {
        type: "boolean",
        description:
          "Include full input schemas per tool. Defaults to false. " +
          "Set true with a category or search filter to get parameter details for specific tools.",
        default: false,
      },
    },
  },
  annotations: {
    readOnlyHint: true,
    destructiveHint: false,
    idempotentHint: true,
    openWorldHint: false,
  },
};

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

const META_TOOL_LOCATION_TIMELINE: ToolInfo = {
  name: "unifi_location_timeline",
  title: "UniFi Location Timeline",
  description:
    "Query events across all connected UniFi products (Network, Protect, Access) " +
    "and return a unified, time-sorted timeline. Correlates network events, camera " +
    "motion, and door access in a single view.",
  inputSchema: {
    type: "object",
    properties: {
      start_time: { type: "string", description: "Start of time window (ISO 8601)" },
      end_time: { type: "string", description: "End of time window (ISO 8601)" },
      location_id: {
        type: "string",
        description: "Filter to a specific location (omit to query all connected locations)",
      },
      products: {
        type: "array",
        items: { type: "string" },
        description: "Filter to specific products: ['network', 'protect', 'access']",
      },
      area_hint: {
        type: "string",
        description: "Filter by area name (e.g., 'front door' matches AP, camera, and door names)",
      },
      event_types: {
        type: "array",
        items: { type: "string" },
        description: "Filter by event type (e.g., 'motion', 'client_connect', 'badge_scan')",
      },
    },
    required: ["start_time", "end_time"],
  },
  annotations: {
    readOnlyHint: true,
    destructiveHint: false,
    idempotentHint: true,
    openWorldHint: false,
  },
};

const META_TOOLS: ToolInfo[] = [META_TOOL_INDEX, META_TOOL_EXECUTE, META_TOOL_BATCH, META_TOOL_LOCATION_TIMELINE];

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

    // Rebuild WebSocket map from hibernation-managed sockets
    this.locationWebSockets.clear();
    for (const ws of this.ctx.getWebSockets()) {
      try {
        const attachment = ws.deserializeAttachment() as { locationId?: string } | null;
        if (attachment?.locationId) {
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
    try {
      const body = (await request.json()) as import("./types").JsonRpcRequest;
      const mode = this.env.TOOL_REGISTRATION_MODE || "lazy";
      const result = await handleMcpRequest(body, this, mode);
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

    // Rebuild in-memory state
    this.rebuildInMemoryState();

    // Attach location_id to the WebSocket for later identification
    ws.serializeAttachment({ locationId, locationName: msg.location_name || locationName });

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
        // In-memory tool state stays (tools are still in SQLite) so the
        // location will become routable again when it reconnects.
        this.locationWebSockets.delete(attachment.locationId);
      }
    } catch {
      // No attachment, nothing to clean up
    }
  }

  // -------------------------------------------------------------------------
  // RelayStub interface implementation
  // -------------------------------------------------------------------------

  async getToolList(mode: string): Promise<ToolInfo[]> {
    if (mode === "lazy" || mode === "meta_only") {
      return META_TOOLS;
    }

    // eager mode: return all deduplicated tools from all locations
    return this.getAggregatedTools();
  }

  async handleToolCall(
    toolName: string,
    args: Record<string, unknown>,
  ): Promise<Record<string, unknown> | AggregatedResponse> {
    // Handle meta-tools
    if (toolName === "unifi_tool_index") {
      return this.handleToolIndex(args);
    }
    if (toolName === "unifi_execute") {
      return this.handleExecute(args);
    }
    if (toolName === "unifi_batch") {
      return this.handleBatch(args);
    }
    if (toolName === "unifi_location_timeline") {
      return this.handleLocationTimeline(args);
    }

    // Direct tool call (eager mode)
    return this.routeToolCall(toolName, args);
  }

  async isMultiLocation(): Promise<boolean> {
    return this.locationTools.size > 1;
  }

  // -------------------------------------------------------------------------
  // Meta-tool handlers
  // -------------------------------------------------------------------------

  private handleToolIndex(args: Record<string, unknown>): Record<string, unknown> {
    const category = args.category as string | undefined;
    const search = args.search as string | undefined;
    const includeSchemas = Boolean(args.include_schemas);

    // Build tool list with location metadata
    const toolEntries: Array<{
      name: string;
      title?: string;
      description: string;
      locations: string[];
      annotations?: ToolAnnotations;
      inputSchema?: Record<string, unknown>;
    }> = [];

    const seen = new Set<string>();
    for (const [locationId, tools] of this.locationTools) {
      for (const tool of tools) {
        if (!seen.has(tool.name)) {
          seen.add(tool.name);
          const entry: (typeof toolEntries)[number] = {
            name: tool.name,
            description: tool.description,
            locations: this.toolToLocations.get(tool.name) || [locationId],
            annotations: tool.annotations,
          };
          if (tool.title) {
            entry.title = tool.title;
          }
          if (includeSchemas && tool.inputSchema) {
            entry.inputSchema = tool.inputSchema;
          }
          toolEntries.push(entry);
        }
      }
    }

    let filtered = toolEntries;

    // Filter by category (matches tools whose name or description contains the category)
    if (category) {
      const cat = category.toLowerCase();
      filtered = filtered.filter(
        (t) => t.name.toLowerCase().includes(cat) || t.description.toLowerCase().includes(cat),
      );
    }

    // Filter by search term
    if (search) {
      const term = search.toLowerCase();
      filtered = filtered.filter(
        (t) => t.name.toLowerCase().includes(term) || t.description.toLowerCase().includes(term),
      );
    }

    return {
      success: true,
      data: {
        tools: filtered,
        total: filtered.length,
        multi_location: this.locationTools.size > 1,
      },
    };
  }

  private async handleExecute(args: Record<string, unknown>): Promise<Record<string, unknown> | AggregatedResponse> {
    const toolName = args.tool as string;
    if (!toolName) {
      return { success: false, error: "Missing required argument: tool" };
    }

    const toolArgs = (args.arguments as Record<string, unknown>) || {};
    const location = args.__location as string | undefined;
    if (location) {
      toolArgs.__location = location;
    }

    return this.routeToolCall(toolName, toolArgs);
  }

  private async handleBatch(args: Record<string, unknown>): Promise<Record<string, unknown>> {
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
        return this.routeToolCall(call.tool, callArgs);
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

  private async handleLocationTimeline(args: Record<string, unknown>): Promise<Record<string, unknown>> {
    const startTime = args.start_time as string | undefined;
    const endTime = args.end_time as string | undefined;

    if (!startTime || !endTime) {
      return { success: false, error: "start_time and end_time are required" };
    }

    // Validate ISO 8601
    if (isNaN(Date.parse(startTime)) || isNaN(Date.parse(endTime))) {
      return { success: false, error: "start_time and end_time must be valid ISO 8601 timestamps" };
    }
    if (new Date(endTime) <= new Date(startTime)) {
      return { success: false, error: "end_time must be after start_time" };
    }

    const locationId = args.location_id as string | undefined;
    const products = args.products as string[] | undefined;
    const areaHint = args.area_hint as string | undefined;
    const eventTypes = args.event_types as string[] | undefined;

    // Event-listing tool names per product
    const eventToolMap: Record<string, string> = {
      network: "unifi_list_events",
      protect: "unifi_protect_list_events",
      access: "unifi_access_list_events",
    };

    // Convert time range to within_hours for Network events (which use a lookback window)
    const startDate = new Date(startTime);
    const endDate = new Date(endTime);
    const withinHours = Math.max(1, Math.ceil((endDate.getTime() - startDate.getTime()) / (1000 * 60 * 60)));
    // Hours from now to the start of the window (for Network's "within" param)
    const hoursAgo = Math.max(1, Math.ceil((Date.now() - startDate.getTime()) / (1000 * 60 * 60)));

    const targetProducts = products || Object.keys(eventToolMap);
    const allEvents: Array<Record<string, unknown>> = [];

    // Fan out event queries to each product's event tool
    for (const product of targetProducts) {
      const toolName = eventToolMap[product];
      if (!toolName) continue;

      // Check if any location has this tool
      const locations = this.toolToLocations.get(toolName);
      if (!locations || locations.length === 0) continue;

      // Filter to specific location if requested
      const targetLocations = locationId ? locations.filter((l) => l === locationId) : locations;
      if (targetLocations.length === 0) continue;

      // Build product-specific arguments
      // Network uses within_hours lookback; Protect/Access may use start_time/end_time
      const toolArgs: Record<string, unknown> = product === "network"
        ? { within_hours: hoursAgo, limit: 3000 }
        : { start_time: startTime, end_time: endTime };

      try {
        const result = await this.routeToolCall(toolName, toolArgs);

        // Extract events from the result (handles both single and fan-out responses)
        const events = this.extractEvents(result, product);
        allEvents.push(...events);
      } catch (err) {
        // Log but continue — partial results are better than failure
      }
    }

    // Sort by timestamp
    allEvents.sort((a, b) => {
      const tsA = String(a.timestamp || a.datetime || a.time || "");
      const tsB = String(b.timestamp || b.datetime || b.time || "");
      return tsA.localeCompare(tsB);
    });

    // Apply area_hint filter (case-insensitive substring match on area names)
    let filtered = allEvents;
    if (areaHint) {
      const hint = areaHint.toLowerCase();
      filtered = allEvents.filter((e) => {
        const areaFields = [e.ap_name, e.camera_name, e.door_name, e.device_name, e.name].filter(Boolean);
        return areaFields.some((f) => String(f).toLowerCase().includes(hint));
      });
    }

    // Apply event_types filter
    if (eventTypes && eventTypes.length > 0) {
      const types = new Set(eventTypes);
      filtered = filtered.filter((e) => types.has(String(e.type || e.event_type || "")));
    }

    // Build summary
    const byProduct: Record<string, number> = {};
    const byType: Record<string, number> = {};
    const byLocation: Record<string, number> = {};
    for (const e of filtered) {
      const p = String(e._product || "unknown");
      byProduct[p] = (byProduct[p] || 0) + 1;
      const t = String(e.type || e.event_type || "unknown");
      byType[t] = (byType[t] || 0) + 1;
      if (e._location_id) {
        const l = String(e._location_id);
        byLocation[l] = (byLocation[l] || 0) + 1;
      }
    }

    return {
      success: true,
      data: {
        timeline: filtered,
        summary: {
          total_events: filtered.length,
          by_product: byProduct,
          by_type: byType,
          by_location: byLocation,
          time_range: { start: startTime, end: endTime },
        },
      },
    };
  }

  /** Extract events from a tool call result, tagging each with product and location metadata. */
  private extractEvents(
    result: Record<string, unknown> | AggregatedResponse,
    product: string,
  ): Array<Record<string, unknown>> {
    // Fan-out response (multi-location)
    if ("results" in result && Array.isArray((result as AggregatedResponse).results)) {
      const agg = result as AggregatedResponse;
      const events: Array<Record<string, unknown>> = [];
      for (const locResult of agg.results) {
        if (locResult.error) continue;
        const locEvents = this.extractEventsFromData(locResult.data);
        for (const e of locEvents) {
          e._product = product;
          e._location_id = locResult.location_id;
          e._location_name = locResult.location_name;
        }
        events.push(...locEvents);
      }
      return events;
    }

    // Single-location response
    const data = (result as Record<string, unknown>).data ?? result;
    const events = this.extractEventsFromData(data);
    for (const e of events) {
      e._product = product;
    }
    return events;
  }

  /** Pull the events array out of a tool result's data payload. */
  private extractEventsFromData(data: unknown): Array<Record<string, unknown>> {
    if (!data || typeof data !== "object") return [];

    // Handle {success: true, data: {events: [...]}} pattern
    const d = data as Record<string, unknown>;
    if (d.success && d.data && typeof d.data === "object") {
      const inner = d.data as Record<string, unknown>;
      if (Array.isArray(inner.events)) return inner.events as Array<Record<string, unknown>>;
    }

    // Handle {events: [...]} directly
    if (Array.isArray(d.events)) return d.events as Array<Record<string, unknown>>;

    // Handle raw array
    if (Array.isArray(data)) return data as Array<Record<string, unknown>>;

    return [];
  }

  // -------------------------------------------------------------------------
  // Tool call routing
  // -------------------------------------------------------------------------

  private async routeToolCall(
    toolName: string,
    args: Record<string, unknown>,
  ): Promise<Record<string, unknown> | AggregatedResponse> {
    const locations = this.toolToLocations.get(toolName);
    if (!locations || locations.length === 0) {
      return { success: false, error: `Tool not found: ${toolName}` };
    }

    // Single location: always route directly
    if (this.locationTools.size === 1) {
      const locationId = locations[0];
      return this.sendToolCall(locationId, toolName, args);
    }

    // Multi-location: check if the tool is read-only
    const toolInfo = this.findToolInfo(toolName);
    const isReadOnly = toolInfo?.annotations?.readOnlyHint === true;

    if (isReadOnly) {
      // Fan out to all locations that have this tool
      return this.fanOutToolCall(toolName, args, locations);
    }

    // Write tool: requires explicit __location
    const targetLocation = args.__location as string | undefined;
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

    // Remove __location from args before sending
    const { __location, ...cleanArgs } = args;
    return this.sendToolCall(targetLocation, toolName, cleanArgs);
  }

  private async sendToolCall(
    locationId: string,
    toolName: string,
    args: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const ws = this.findWebSocketForLocation(locationId);
    if (!ws) {
      return { success: false, error: `Location ${locationId} is not connected` };
    }

    const callId = crypto.randomUUID();

    const result = await new Promise<unknown>((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pending.delete(callId);
        reject(new Error(`Tool call timed out after ${TOOL_CALL_TIMEOUT_MS}ms`));
      }, TOOL_CALL_TIMEOUT_MS);

      this.pending.set(callId, { resolve, reject, timeout, locationId });

      const request: ToolCallRequest = {
        type: "tool_call",
        call_id: callId,
        tool_name: toolName,
        arguments: args,
        timeout_ms: TOOL_CALL_TIMEOUT_MS,
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

  /** Get deduplicated tools across all locations (for eager mode) */
  getAggregatedTools(): ToolInfo[] {
    const seen = new Set<string>();
    const tools: ToolInfo[] = [];

    for (const locationToolList of this.locationTools.values()) {
      for (const tool of locationToolList) {
        if (!seen.has(tool.name)) {
          seen.add(tool.name);
          tools.push(tool);
        }
      }
    }

    return tools;
  }

  private findToolInfo(toolName: string): ToolInfo | undefined {
    for (const tools of this.locationTools.values()) {
      const found = tools.find((t) => t.name === toolName);
      if (found) return found;
    }
    return undefined;
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
