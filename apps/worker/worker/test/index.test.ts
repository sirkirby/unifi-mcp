// test/index.test.ts
import { describe, it, expect, vi } from "vitest";

vi.mock("cloudflare:workers", () => ({ DurableObject: class {} }));
import worker from "../src/index";
import { RelayObject } from "../src/relay-object";
import type { Env } from "../src/types";

function fakeEnv(doResponse: Response, allowed?: string): { env: Env; doFetch: ReturnType<typeof vi.fn> } {
  const doFetch = vi.fn(async (_request: Request) => doResponse.clone());
  const env = {
    AGENT_TOKEN: "static-agent-token-fixture",
    ADMIN_TOKEN: "admin-token-fixture",
    TOOL_REGISTRATION_MODE: "lazy",
    CORS_ALLOWED_ORIGINS: allowed,
    RELAY: { idFromName: () => "singleton", get: () => ({ fetch: doFetch }) },
  } as unknown as Env;
  return { env, doFetch };
}

function mcp(headers: Record<string, string>, body = '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'): Request {
  return new Request("https://relay.example/mcp", { method: "POST", headers, body });
}

describe("POST /mcp", () => {
  it.each(["notifications/initialized", "notifications/cancelled", "notifications/roots/list_changed", "notifications/unknown"])("acknowledges %s without a JSON-RPC response", async (method) => {
    const { env, doFetch } = fakeEnv(Response.json({}));
    const relay = Object.create(RelayObject.prototype) as RelayObject;
    Object.assign(relay, {
      env,
      stateRebuilt: true,
      ctx: { storage: { sql: { exec: () => ({ toArray: () => [] }) } } },
    });
    doFetch.mockImplementation((request: Request) => relay.fetch(request));
    const headers = {
      Authorization: "Bearer static-agent-token-fixture",
      "Content-Type": "application/json",
      Accept: "application/json, text/event-stream",
    };
    const initialize = await worker.fetch(mcp(headers, JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: { protocolVersion: "2025-03-26", capabilities: {}, clientInfo: { name: "test-client", version: "1.0" } },
    })), env);
    expect(initialize.status).toBe(200);
    const notification = JSON.stringify({ jsonrpc: "2.0", method, params: { requestId: 42, reason: "User cancelled" } });
    const rejected = await worker.fetch(mcp({ ...headers, Authorization: "Bearer wrong-token" }, notification), env);
    expect(rejected.status).toBe(401);
    const accepted = await worker.fetch(mcp(headers, notification), env);
    expect(accepted.status).toBe(202);
    expect(await accepted.text()).toBe("");
  });

  it("rejects a request without a bearer before reaching the relay", async () => {
    const { env, doFetch } = fakeEnv(Response.json({}));

    const res = await worker.fetch(mcp({}), env);

    expect(res.status).toBe(401);
    expect(doFetch).not.toHaveBeenCalled();
  });

  it("forwards the bearer and raw body so the relay can resolve the token's scope", async () => {
    const { env, doFetch } = fakeEnv(Response.json({ jsonrpc: "2.0", id: 1, result: {} }));

    const res = await worker.fetch(mcp({ Authorization: "Bearer scoped-token" }), env);

    expect(res.status).toBe(200);
    const forwarded = doFetch.mock.calls[0][0] as Request;
    expect(forwarded.headers.get("Authorization")).toBe("Bearer scoped-token");
    expect(await forwarded.text()).toBe('{"jsonrpc":"2.0","id":1,"method":"tools/list"}');
  });

  it("returns 401 without CORS headers when the relay rejects the token", async () => {
    const { env } = fakeEnv(new Response("Unauthorized", { status: 401 }), "https://app.example");

    const res = await worker.fetch(mcp({ Authorization: "Bearer bad", Origin: "https://app.example" }), env);

    expect(res.status).toBe(401);
    expect(res.headers.get("Access-Control-Allow-Origin")).toBeNull();
  });

  it("passes the relay's parse-error status through", async () => {
    const parseError = { jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } };
    const { env } = fakeEnv(Response.json(parseError, { status: 400 }));

    const res = await worker.fetch(mcp({ Authorization: "Bearer static-agent-token-fixture" }, "{"), env);

    expect(res.status).toBe(400);
    expect(await res.json()).toEqual(parseError);
  });

  it("echoes only an allowlisted Origin", async () => {
    const { env } = fakeEnv(Response.json({ jsonrpc: "2.0", id: 1, result: {} }), "https://app.example");
    const auth = { Authorization: "Bearer static-agent-token-fixture" };

    const allowed = await worker.fetch(mcp({ ...auth, Origin: "https://app.example" }), env);
    const other = await worker.fetch(mcp({ ...auth, Origin: "https://evil.example" }), env);

    expect(allowed.headers.get("Access-Control-Allow-Origin")).toBe("https://app.example");
    expect(other.headers.get("Access-Control-Allow-Origin")).toBeNull();
  });
});

describe("OPTIONS preflight", () => {
  it("does not grant a preflight to an Origin outside the allowlist", async () => {
    const { env } = fakeEnv(Response.json({}), "https://app.example");
    const preflight = (origin: string) =>
      worker.fetch(new Request("https://relay.example/mcp", { method: "OPTIONS", headers: { Origin: origin } }), env);

    expect((await preflight("https://evil.example")).headers.get("Access-Control-Allow-Origin")).toBeNull();
    expect((await preflight("https://app.example")).headers.get("Access-Control-Allow-Origin")).toBe("https://app.example");
  });

  it("grants an allowlisted Streamable HTTP client's preflight and exposes its session ID", async () => {
    const { env } = fakeEnv(Response.json({}), "https://app.example");

    const res = await worker.fetch(
      new Request("https://relay.example/mcp", {
        method: "OPTIONS",
        headers: {
          Origin: "https://app.example",
          "Access-Control-Request-Method": "POST",
          "Access-Control-Request-Headers": "authorization,content-type,mcp-session-id,mcp-protocol-version",
        },
      }),
      env,
    );

    const allowed = res.headers.get("Access-Control-Allow-Headers")!.toLowerCase().split(", ");
    expect(res.status).toBe(204);
    expect(allowed).toEqual(expect.arrayContaining(["authorization", "content-type", "mcp-session-id", "mcp-protocol-version"]));
    expect(res.headers.get("Access-Control-Expose-Headers")).toBe("Mcp-Session-Id");
  });

  it("echoes any Origin when no allowlist is configured", async () => {
    const { env } = fakeEnv(Response.json({}));

    const res = await worker.fetch(
      new Request("https://relay.example/mcp", { method: "OPTIONS", headers: { Origin: "https://anywhere.example" } }),
      env,
    );

    expect(res.headers.get("Access-Control-Allow-Origin")).toBe("https://anywhere.example");
  });
});

describe("Admin API", () => {
  it("passes a bodyless 204 from the relay through", async () => {
    const { env } = fakeEnv(new Response(null, { status: 204 }));

    const res = await worker.fetch(
      new Request("https://relay.example/api/agent-tokens/reader", {
        method: "DELETE",
        headers: { Authorization: "Bearer admin-token-fixture" },
      }),
      env,
    );

    expect(res.status).toBe(204);
    expect(res.body).toBeNull();
  });

  it("rejects the agent token on admin routes", async () => {
    const { env, doFetch } = fakeEnv(Response.json({}));

    const res = await worker.fetch(
      new Request("https://relay.example/api/agent-tokens", {
        headers: { Authorization: "Bearer static-agent-token-fixture" },
      }),
      env,
    );

    expect(res.status).toBe(401);
    expect(doFetch).not.toHaveBeenCalled();
  });
});
