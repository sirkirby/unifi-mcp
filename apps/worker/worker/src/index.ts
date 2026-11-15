// src/index.ts
import type { Env } from "./types";
import { extractBearerToken, validateBearerToken } from "./auth";
import { corsHeaders } from "./cors";

// Re-export the Durable Object class (required by wrangler)
export { RelayObject } from "./relay-object";

function jsonResponse(data: unknown, request: Request, env: Env, status = 200): Response {
  return Response.json(data, { status, headers: corsHeaders(request, env) });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(request, env) });
    }

    // Health check (no auth)
    if (url.pathname === "/health") {
      return jsonResponse({ status: "ok" }, request, env);
    }

    // MCP endpoint (cloud agents). The DO validates the bearer: the static
    // AGENT_TOKEN, or a scoped agent token it stores as a SHA-256 hash.
    if (url.pathname === "/mcp" && request.method === "POST") {
      const token = extractBearerToken(request);
      if (!token) {
        return new Response("Unauthorized", { status: 401 });
      }

      // Get DO singleton and forward
      const doId = env.RELAY.idFromName("singleton");
      const doStub = env.RELAY.get(doId);
      const doResponse = await doStub.fetch(
        new Request("https://relay-do/mcp", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: await request.text(),
        }),
      );

      if (doResponse.status === 401) {
        return new Response("Unauthorized", { status: 401 });
      }

      if (doResponse.status === 202) {
        return new Response(null, { status: 202, headers: corsHeaders(request, env) });
      }

      const result = await doResponse.json();
      return jsonResponse(result, request, env, doResponse.status);
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
      // A 204 (agent token revoked) must not carry a body, even an empty one.
      return new Response(doResponse.status === 204 ? null : responseBody, {
        status: doResponse.status,
        headers: { ...Object.fromEntries(doResponse.headers), ...corsHeaders(request, env) },
      });
    }

    return new Response("Not Found", { status: 404, headers: corsHeaders(request, env) });
  },
};
