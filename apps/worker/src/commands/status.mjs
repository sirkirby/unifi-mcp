// src/commands/status.mjs
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join, dirname } from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import chalk from "chalk";
import { loadConfig, getConfigDir } from "../lib/config.mjs";
import { showStatus, showError } from "../lib/display.mjs";

const execFileAsync = promisify(execFile);

export async function run() {
  const config = loadConfig();
  if (!config) {
    showError("No deployment found. Run 'unifi-mcp-worker install' first.");
    process.exit(1);
  }

  showStatus(config);

  const pkgPath = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "package.json");
  const currentVersion = JSON.parse(readFileSync(pkgPath, "utf8")).version;
  console.log(`  CLI version: ${currentVersion}`);

  try {
    const { stdout } = await execFileAsync("npm", ["view", "unifi-mcp-worker", "version"], {
      timeout: 10_000,
    });
    const latest = stdout.trim();
    if (latest !== currentVersion) {
      console.log(chalk.yellow(`  Update available: ${latest}`));
      console.log(chalk.dim("  Run 'unifi-mcp-worker upgrade' to update.\n"));
    } else {
      console.log(chalk.green("  Up to date.\n"));
    }
  } catch {
    console.log(chalk.dim("  Could not check for updates.\n"));
  }

  console.log(chalk.dim(`  Config: ${getConfigDir()}/config.json\n`));
}
