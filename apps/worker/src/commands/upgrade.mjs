// src/commands/upgrade.mjs
import { execFile, spawn } from "node:child_process";
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
import { resolveCommand } from "../lib/command.mjs";

const execFileAsync = promisify(execFile);

async function checkForUpdate() {
  try {
    const npm = resolveCommand("npm", ["view", "unifi-mcp-worker", "version"]);
    const { stdout } = await execFileAsync(npm.file, npm.args, {
      timeout: 10_000,
      ...npm.options,
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
      const npm = resolveCommand("npm", ["install", "-g", "unifi-mcp-worker@latest"]);
      await execFileAsync(npm.file, npm.args, { timeout: 120_000, ...npm.options });
      // The CLI is itself a .cmd shim on Windows.
      const cli = resolveCommand("unifi-mcp-worker", ["upgrade", ...process.argv.slice(3)]);
      const child = spawn(cli.file, cli.args, { stdio: "inherit", ...cli.options });
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
