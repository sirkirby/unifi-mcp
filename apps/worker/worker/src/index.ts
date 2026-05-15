// src/index.ts
import type { Env, JsonRpcRequest } from "./types";
import { validateBearerToken } from "./auth";

// Re-export the Durable Object class (required by wrangler)
export { RelayObject } from "./relay-object";

function corsHeaders(origin?: string | null): Record<string, string> {
  return {
    "Access-Control-Allow-Origin": origin || "",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
  };
}

function jsonResponse(data: unknown, request: Request, status = 200): Response {
  const origin = request.headers.get("Origin") || "";
  return Response.json(data, { status, headers: corsHeaders(origin) });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin") || "";

    // CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }

    // Health check (no auth)
    if (url.pathname === "/health") {
      return jsonResponse({ status: "ok" }, request);
    }

    // MCP endpoint (cloud agents — authenticated with AGENT_TOKEN)
    if (url.pathname === "/mcp" && request.method === "POST") {
      if (!validateBearerToken(request, env.AGENT_TOKEN)) {
        return new Response("Unauthorized", { status: 401 });
      }

      let body: JsonRpcRequest;
      try {
        body = (await request.json()) as JsonRpcRequest;
      } catch {
        return jsonResponse(
          { jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } },
          request,
          400,
        );
      }

      // Get DO singleton and forward
      const doId = env.RELAY.idFromName("singleton");
      const doStub = env.RELAY.get(doId);
      const doResponse = await doStub.fetch(
        new Request("https://relay-do/mcp", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }),
      );

      const result = await doResponse.json();
      return jsonResponse(result, request);
    }

    // WebSocket upgrade (relay clients — token validated inside DO)
    if (url.pathname === "/ws" && request.headers.get("Upgrade") === "websocket") {
      const doId = env.RELAY.idFromName("singleton");
      const doStub = env.RELAY.get(doId);
      return doStub.fetch(request);
    }

    // Admin API (authenticated with ADMIN_TOKEN)
    if (url.pathname.startsWith("/api/")) {
      if (!validateBearerToken(request, env.ADMIN_TOKEN)) {
        return new Response("Unauthorized", { status: 401 });
      }
      const doId = env.RELAY.idFromName("singleton");
      const doStub = env.RELAY.get(doId);
      const doResponse = await doStub.fetch(request);
      // Add CORS headers to DO response
      const responseBody = await doResponse.text();
      return new Response(responseBody, {
        status: doResponse.status,
        headers: { ...Object.fromEntries(doResponse.headers), ...corsHeaders(origin) },
      });
    }

    return new Response("Not Found", { status: 404, headers: corsHeaders(origin) });
  },
};
