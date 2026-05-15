// test/types.test.ts
import { describe, it, expect } from "vitest";
import {
  PROTOCOL_VERSION,
  TOOL_CALL_TIMEOUT_MS,
  HEARTBEAT_INTERVAL_MS,
  HEARTBEAT_ACK_TIMEOUT_MS,
  PROJECT_WEBSITE_URL,
  RELAY_SERVER_ICONS,
} from "../src/types";

describe("types constants", () => {
  it("PROTOCOL_VERSION is 1", () => {
    expect(PROTOCOL_VERSION).toBe(1);
  });

  it("TOOL_CALL_TIMEOUT_MS is 30_000", () => {
    expect(TOOL_CALL_TIMEOUT_MS).toBe(30_000);
  });

  it("HEARTBEAT_INTERVAL_MS is 30_000", () => {
    expect(HEARTBEAT_INTERVAL_MS).toBe(30_000);
  });

  it("HEARTBEAT_ACK_TIMEOUT_MS is 10_000", () => {
    expect(HEARTBEAT_ACK_TIMEOUT_MS).toBe(10_000);
  });

  it("constants are positive integers", () => {
    for (const c of [
      PROTOCOL_VERSION,
      TOOL_CALL_TIMEOUT_MS,
      HEARTBEAT_INTERVAL_MS,
      HEARTBEAT_ACK_TIMEOUT_MS,
    ]) {
      expect(c).toBeGreaterThan(0);
      expect(Number.isInteger(c)).toBe(true);
    }
  });

  it("relay MCP metadata constants are stable and self-contained", () => {
    expect(PROJECT_WEBSITE_URL).toBe("https://github.com/sirkirby/unifi-mcp");
    expect(RELAY_SERVER_ICONS).toEqual([
      expect.objectContaining({
        src: expect.stringMatching(/^data:image\/svg\+xml,/),
        mimeType: "image/svg+xml",
        sizes: ["192x192"],
      }),
    ]);
  });
});
