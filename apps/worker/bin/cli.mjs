#!/usr/bin/env node

import { parseArgs } from "node:util";

const COMMANDS = {
  install: () => import("../src/commands/install.mjs"),
  upgrade: () => import("../src/commands/upgrade.mjs"),
  "add-location": () => import("../src/commands/add-location.mjs"),
  "rotate-tokens": () => import("../src/commands/rotate-tokens.mjs"),
  status: () => import("../src/commands/status.mjs"),
  destroy: () => import("../src/commands/destroy.mjs"),
  observability: () => import("../src/commands/observability.mjs"),
};

const { values, positionals } = parseArgs({
  allowPositionals: true,
  options: {
    version: { type: "boolean", short: "v" },
    help: { type: "boolean", short: "h" },
    "non-interactive": { type: "boolean" },
    yes: { type: "boolean", short: "y" },
    "worker-name": { type: "string" },
    "location-name": { type: "string" },
    "worker-url": { type: "string" },
    "admin-token": { type: "string" },
    token: { type: "string" },
    force: { type: "boolean", short: "f" },
    enable: { type: "boolean" },
    disable: { type: "boolean" },
    observability: { type: "boolean" },
  },
});

if (values.version) {
  const { readFileSync } = await import("node:fs");
  const { fileURLToPath } = await import("node:url");
  const { join, dirname } = await import("node:path");
  const pkgPath = join(dirname(fileURLToPath(import.meta.url)), "..", "package.json");
  const pkg = JSON.parse(readFileSync(pkgPath, "utf8"));
  console.log(pkg.version);
  process.exit(0);
}

const command = positionals[0];

if (values.help || !command) {
  console.log(`
Usage: unifi-mcp-worker <command> [options]

Commands:
  install         Deploy the Cloudflare Worker and generate tokens
  upgrade         Redeploy the latest worker code
  add-location    Add a new location (generates a relay token)
  rotate-tokens   Rotate agent, admin, or relay tokens
  status          Show deployment info and token summary
  destroy         Remove the worker and clean up
  observability   Show or toggle Workers Logs observability

Options:
  --version, -v          Show CLI version
  --help, -h             Show this help
  --non-interactive      Disable interactive prompts (requires flags for all values)
  --yes, -y              Skip confirmation prompts
  --worker-name <name>   Worker name (default: unifi-mcp-relay)
  --location-name <name> Location name (default: Home Lab)
  --worker-url <url>     Worker URL (for add-location, rotate-tokens)
  --admin-token <token>  Admin token override
  --token <type>         Token to rotate: agent, admin, relay, all
  --force, -f            Overwrite existing config on install
  --enable               Enable observability (for observability command)
  --disable              Disable observability (for observability command)
  --observability        Enable observability during install
`);
  process.exit(0);
}

if (!COMMANDS[command]) {
  console.error(`Unknown command: ${command}`);
  console.error(`Run 'unifi-mcp-worker --help' for available commands.`);
  process.exit(1);
}

const mod = await COMMANDS[command]();
await mod.run(values);
