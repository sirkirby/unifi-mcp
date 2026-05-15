import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { buildWranglerToml } from "../../src/lib/wrangler.mjs";

describe("buildWranglerToml", () => {
  const baseToml = `name = "unifi-mcp-relay"
main = "src/index.ts"
compatibility_date = "2025-03-14"
compatibility_flags = ["nodejs_compat"]

[vars]
TOOL_REGISTRATION_MODE = "lazy"

[durable_objects]
bindings = [{ name = "RELAY", class_name = "RelayObject" }]

[[migrations]]
tag = "v1"
new_sqlite_classes = ["RelayObject"]`;

  it("returns original TOML when observability is false", () => {
    const result = buildWranglerToml(baseToml, { observability: false });
    assert.equal(result, baseToml);
  });

  it("returns original TOML when observability is undefined", () => {
    const result = buildWranglerToml(baseToml, {});
    assert.equal(result, baseToml);
  });

  it("appends observability block when enabled", () => {
    const result = buildWranglerToml(baseToml, { observability: true });
    assert.ok(result.includes("[observability]"));
    assert.ok(result.includes("[observability.logs]"));
    assert.ok(result.includes("enabled = true"));
    assert.ok(result.includes("invocation_logs = true"));
  });

  it("appends both custom domain and observability", () => {
    const result = buildWranglerToml(baseToml, {
      customDomain: "mcp.example.com",
      observability: true,
    });
    assert.ok(result.includes("[[routes]]"));
    assert.ok(result.includes("mcp.example.com"));
    assert.ok(result.includes("[observability]"));
  });

  it("does not duplicate observability block if already present", () => {
    const tomlWithObs = baseToml + `\n\n[observability]\n[observability.logs]\nenabled = true\ninvocation_logs = true\n`;
    const result = buildWranglerToml(tomlWithObs, { observability: true });
    const matches = result.match(/\[observability\]/g);
    assert.equal(matches.length, 1);
  });
});
