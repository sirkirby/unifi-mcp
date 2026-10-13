import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";

vi.mock("cloudflare:workers", () => ({ DurableObject: class {} }));
import { RelayObject } from "../src/relay-object";
import { TOOL_CALL_TIMEOUT_MS } from "../src/types";

const windowArgs = { start: "2026-08-08T12:00:00Z", end: "2026-08-08T13:00:00Z" };
function fakeRelay(locations: string[], tools: Map<string, string[]>, result: unknown) {
  const relay = Object.create(RelayObject.prototype) as any;
  relay.ctx = { storage: { sql: { exec: vi.fn(() => ({ toArray: () => locations.map((location_id) => ({ location_id })) })) } } };
  relay.locationTools = new Map([...tools].map(([id, names]) => [id, names.map((name) => ({ name, description: "" }))]));
  relay.sendToolCall = vi.fn(async (_id: string, _name: string, _args: Record<string, unknown>) => result);
  return relay;
}

describe("RelayObject location evidence meta-tool", () => {
  it("uses the real tool dispatch path and returns a failed contract document when no tool is registered", async () => {
    const relay = fakeRelay(["fixture-1"], new Map([["fixture-1", []]]), null);
    const result = await relay.handleToolCall("unifi_location_timeline", windowArgs);
    expect(result).toMatchObject({ success: true, data: { schema: "unifi-incident-evidence-view", overall: "failed", coverage_complete: false } });
    expect((result as any).data.sources.map((source: any) => source.outcome)).toEqual(["unsupported", "unsupported"]);
    expect(relay.sendToolCall).not.toHaveBeenCalled();
  });
  it("refuses an unknown location_id through the real dispatch path before any read", async () => {
    const relay = fakeRelay(["fixture-1"], new Map([["fixture-1", ["unifi_get_incident_evidence", "protect_get_incident_evidence"]]]), null);
    const result = await relay.handleToolCall("unifi_location_timeline", { ...windowArgs, location_id: "Home Lab" });
    expect(result).toEqual({ success: false, error: expect.stringContaining('unknown location_id "Home Lab"') });
    expect((result as any).error).toContain("UUID");
    expect(relay.sendToolCall).not.toHaveBeenCalled();
  });
  it("describes location_id as the location UUID in the tool input schema", async () => {
    const relay = fakeRelay([], new Map(), null);
    const tool = (await relay.getToolList("lazy")).find((entry: any) => entry.name === "unifi_location_timeline");
    expect(tool.inputSchema.properties.location_id.description).toContain("UUID");
  });
  it("forwards to the named evidence tools only and keeps controller errors out of the document", async () => {
    const relay = fakeRelay(["fixture-1"], new Map([["fixture-1", ["unifi_get_incident_evidence", "protect_get_incident_evidence"]]]),
      { success: false, error: "private controller text" });
    const result = await relay.handleToolCall("unifi_location_timeline", windowArgs);
    expect(relay.sendToolCall.mock.calls.map((call: any[]) => call[1])).toEqual(["unifi_get_incident_evidence", "protect_get_incident_evidence"]);
    expect((result as any).data.sources.map((source: any) => source.outcome)).toEqual(["unavailable", "unavailable"]);
    expect(JSON.stringify(result)).not.toContain("private controller text");
  });
  it("forwards exactly the arguments the product evidence tools accept", async () => {
    const schemas = Object.fromEntries(["network", "protect"].map((product) => {
      const manifest = JSON.parse(readFileSync(fileURLToPath(String(new URL(`../../../${product}/src/unifi_${product}_mcp/tools_manifest.json`, import.meta.url))), "utf8"));
      const tool = manifest.tools.find((entry: any) => entry.name.endsWith("_get_incident_evidence"));
      return [tool.name, tool.schema.input];
    }));
    const relay = fakeRelay(["fixture-1"], new Map([["fixture-1", Object.keys(schemas)]]), null);
    await relay.handleToolCall("unifi_location_timeline", {
      ...windowArgs, device_macs: ["02:00:00:00:00:01"], camera_ids: ["fixture-camera"],
    });
    expect(relay.sendToolCall.mock.calls.map((call: any[]) => call[1])).toEqual(Object.keys(schemas));
    for (const [, name, args] of relay.sendToolCall.mock.calls) {
      expect(Object.keys(args).filter((key) => !(key in schemas[name].properties))).toEqual([]);
      expect(schemas[name].required.filter((key: string) => !(key in args))).toEqual([]);
      expect(args).toMatchObject({ start: windowArgs.start, end: windowArgs.end, detail: "full" });
    }
  });
  it("classifies a real pending WebSocket call timeout as timeout", async () => {
    vi.useFakeTimers();
    try {
      const relay = fakeRelay(["fixture-1"], new Map([["fixture-1", ["unifi_get_incident_evidence"]]]), null);
      delete relay.sendToolCall;
      relay.locationWebSockets = new Map([["fixture-1", {}]]);
      relay.pending = new Map();
      relay.sendWs = vi.fn();
      const pending = relay.handleToolCall("unifi_location_timeline", { ...windowArgs, products: ["network"] });
      await vi.advanceTimersByTimeAsync(TOOL_CALL_TIMEOUT_MS);
      const result = await pending;
      expect(result).toMatchObject({ success: true, data: { sources: [{ outcome: "timeout", failure: { kind: "timeout" } }] } });
      expect(relay.pending.size).toBe(0);
    } finally { vi.useRealTimers(); }
  });
  it("bounds the relay transport wait by the requested elapsed budget", async () => {
    vi.useFakeTimers();
    try {
      const relay = fakeRelay(["fixture-1"], new Map([["fixture-1", ["unifi_get_incident_evidence"]]]), null);
      delete relay.sendToolCall;
      relay.locationWebSockets = new Map([["fixture-1", {}]]);
      relay.pending = new Map();
      relay.sendWs = vi.fn();
      let finished = false;
      const pending = relay.handleToolCall("unifi_location_timeline", {
        ...windowArgs, products: ["network"], max_elapsed_ms: 25,
      }).then((result: any) => { finished = true; return result; });
      await vi.advanceTimersByTimeAsync(24);
      expect(finished).toBe(false);
      await vi.advanceTimersByTimeAsync(1);
      const result = await pending;
      expect(result.data.sources[0].outcome).toBe("timeout");
      expect(relay.sendWs.mock.calls[0][1].timeout_ms).toBe(25);
      expect(relay.pending.size).toBe(0);
    } finally { vi.useRealTimers(); }
  });

});
