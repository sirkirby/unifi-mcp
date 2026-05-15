// src/commands/upgrade.mjs
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join, dirname } from "node:path";
import prompts from "prompts";
import chalk from "chalk";
import { loadConfig, saveConfig } from "../lib/config.mjs";
import { ensureWrangler, checkWranglerAuth } from "../lib/prerequisites.mjs";
import { deploy, login } from "../lib/wrangler.mjs";
import { showError } from "../lib/display.mjs";

const execFileAsync = promisify(execFile);

async function checkForUpdate() {
  try {
    const { stdout } = await execFileAsync("npm", ["view", "unifi-mcp-worker", "version"], {
      timeout: 10_000,
    });
    const latest = stdout.trim();
    const pkgPath = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "package.json");
    const current = JSON.parse(readFileSync(pkgPath, "utf8")).version;
    return { current, latest, needsUpdate: latest !== current };
  } catch {
    return { current: null, latest: null, needsUpdate: false };
  }
}

export async function run(flags) {
  const versionCheck = await checkForUpdate();
  if (versionCheck.needsUpdate) {
    console.log(
      chalk.yellow(
        `\n  CLI update available: ${versionCheck.current} → ${versionCheck.latest}`
      )
    );

    let shouldUpdate = flags.yes || flags["non-interactive"];
    if (!shouldUpdate) {
      const answer = await prompts({
        type: "confirm",
        name: "update",
        message: "Update CLI before upgrading worker?",
        initial: true,
      });
      shouldUpdate = answer.update;
    }

    if (shouldUpdate) {
      console.log("Updating CLI...");
      await execFileAsync("npm", ["install", "-g", "unifi-mcp-worker@latest"], {
        timeout: 120_000,
      });
      const { spawn } = await import("node:child_process");
      const child = spawn("unifi-mcp-worker", ["upgrade", ...process.argv.slice(3)], {
        stdio: "inherit",
      });
      child.on("close", (code) => process.exit(code));
      return;
    }
  }

  const wranglerOk = await ensureWrangler();
  if (!wranglerOk) process.exit(1);

  const authed = await checkWranglerAuth();
  if (!authed) {
    console.log("You need to log in to Cloudflare.");
    await login();
  }

  const config = loadConfig();
  let workerName;

  if (config) {
    workerName = config.worker_name;
  } else if (flags["worker-name"]) {
    workerName = flags["worker-name"];
  } else if (flags["non-interactive"]) {
    showError("No config found and --worker-name not provided.");
    process.exit(1);
  } else {
    const answer = await prompts({
      type: "text",
      name: "workerName",
      message: "Worker name to upgrade",
      initial: "unifi-mcp-relay",
    });
    workerName = answer.workerName;
  }

  try {
    console.log(`\nUpgrading worker "${workerName}"...`);
    await deploy(workerName, {
      customDomain: config?.custom_domain,
      observability: config?.observability || false,
    });

    if (config) {
      config.last_upgraded = new Date().toISOString();
      saveConfig(config);
    }

    console.log(chalk.green("\n  Upgraded to latest version."));
    console.log(chalk.dim("  Tokens and configuration unchanged.\n"));
  } catch (err) {
    showError(`Upgrade failed: ${err.message}`);
    process.exit(1);
  }
}
