import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { checkCommand, getNodeVersion } from "../../src/lib/prerequisites.mjs";

describe("prerequisites", () => {
  it("detects node as available", async () => {
    const result = await checkCommand("node", ["--version"]);
    assert.equal(result.available, true);
    assert.ok(result.version);
  });

  it("detects nonexistent command as unavailable", async () => {
    const result = await checkCommand("nonexistent-command-xyz", ["--version"]);
    assert.equal(result.available, false);
  });

  it("gets node version as a number", () => {
    const version = getNodeVersion();
    assert.equal(typeof version, "number");
    assert.ok(version >= 18);
  });
});
