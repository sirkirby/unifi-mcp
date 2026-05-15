import { existsSync, mkdirSync, readFileSync, writeFileSync, unlinkSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

const CONFIG_DIR = process.env.UNIFI_MCP_WORKER_CONFIG_DIR || join(homedir(), ".unifi-mcp-worker");
const CONFIG_FILE = join(CONFIG_DIR, "config.json");
const CURRENT_CONFIG_VERSION = 1;

export function loadConfig() {
  if (!existsSync(CONFIG_FILE)) return null;
  const raw = readFileSync(CONFIG_FILE, "utf8");
  return JSON.parse(raw);
}

export function saveConfig(data) {
  if (!existsSync(CONFIG_DIR)) {
    mkdirSync(CONFIG_DIR, { recursive: true, mode: 0o700 });
  }
  data.config_version = CURRENT_CONFIG_VERSION;
  writeFileSync(CONFIG_FILE, JSON.stringify(data, null, 2) + "\n", { mode: 0o600 });
}

export function deleteConfig() {
  if (existsSync(CONFIG_FILE)) {
    unlinkSync(CONFIG_FILE);
  }
}

export function maskToken(token) {
  if (!token) return "****";
  const last4 = token.slice(-4);
  return `****-${last4}`;
}

export function getConfigDir() {
  return CONFIG_DIR;
}
