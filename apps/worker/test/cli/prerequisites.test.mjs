import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  checkCommand,
  getNodeVersion,
  isNodeVersionSupported,
  MIN_NODE_MAJOR,
} from "../../src/lib/prerequisites.mjs";

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

  it("gets a supported node version as a number", () => {
    const version = getNodeVersion();
    assert.equal(typeof version, "number");
    assert.ok(version >= MIN_NODE_MAJOR);
    assert.equal(isNodeVersionSupported(version), true);
  });

  it("requires Node.js 22 or newer", () => {
    assert.equal(MIN_NODE_MAJOR, 22);
    assert.equal(isNodeVersionSupported(21), false);
    assert.equal(isNodeVersionSupported(22), true);
    assert.equal(isNodeVersionSupported(23), true);
    assert.equal(isNodeVersionSupported(Number.NaN), false);
  });
});
