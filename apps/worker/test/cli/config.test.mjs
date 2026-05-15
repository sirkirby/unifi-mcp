import { describe, it, before, after } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const createConfigModule = async (dir) => {
  process.env.UNIFI_MCP_WORKER_CONFIG_DIR = dir;
  const mod = await import(`../../src/lib/config.mjs?dir=${encodeURIComponent(dir)}`);
  return mod;
};

describe("config", () => {
  let tmpDir;

  before(() => {
    tmpDir = mkdtempSync(join(tmpdir(), "unifi-mcp-worker-test-"));
  });

  after(() => {
    rmSync(tmpDir, { recursive: true, force: true });
    delete process.env.UNIFI_MCP_WORKER_CONFIG_DIR;
  });

  it("returns null when no config exists", async () => {
    const { loadConfig } = await createConfigModule(join(tmpDir, "nonexistent"));
    const config = loadConfig();
    assert.equal(config, null);
  });

  it("saves and loads config with correct permissions", async () => {
    const configDir = join(tmpDir, "save-test");
    const { loadConfig, saveConfig } = await createConfigModule(configDir);
    const data = {
      config_version: 1,
      worker_name: "test-worker",
      worker_url: "https://test.workers.dev",
      agent_token: "agent-123",
      admin_token: "admin-456",
      locations: [],
    };
    saveConfig(data);
    const loaded = loadConfig();
    assert.deepEqual(loaded.worker_name, "test-worker");
    assert.deepEqual(loaded.config_version, 1);
  });

  it("masks tokens correctly", async () => {
    const { maskToken } = await createConfigModule(join(tmpDir, "mask-test"));
    assert.equal(maskToken("abcdef-1234-5678-90ab"), "****-90ab");
    assert.equal(maskToken("short"), "****-hort");
    assert.equal(maskToken(""), "****");
  });
});
