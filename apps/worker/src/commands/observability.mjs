// src/commands/observability.mjs
import chalk from "chalk";
import prompts from "prompts";
import { loadConfig, saveConfig } from "../lib/config.mjs";
import { ensureWrangler, checkWranglerAuth } from "../lib/prerequisites.mjs";
import { deploy, login } from "../lib/wrangler.mjs";
import { showError } from "../lib/display.mjs";

export async function run(flags) {
  const config = loadConfig();
  if (!config) {
    showError("No deployment found. Run 'unifi-mcp-worker install' first.");
    process.exit(1);
  }

  if (flags.enable && flags.disable) {
    showError("Cannot use both --enable and --disable.");
    process.exit(1);
  }

  // No flags — show current state
  if (!flags.enable && !flags.disable) {
    const state = config.observability ? chalk.green("Enabled") : chalk.dim("Disabled");
    console.log(`\n  Observability: ${state}\n`);
    return;
  }

  const enabling = !!flags.enable;
  const current = !!config.observability;

  if (enabling === current) {
    console.log(`\n  Observability is already ${enabling ? "enabled" : "disabled"}.\n`);
    return;
  }

  // Confirm before redeploying
  if (!flags.yes && !flags["non-interactive"]) {
    const answer = await prompts({
      type: "confirm",
      name: "proceed",
      message: `This will ${enabling ? "enable" : "disable"} observability and redeploy the worker. Continue?`,
      initial: false,
    });
    if (!answer.proceed) {
      console.log("Cancelled.");
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

  try {
    console.log(`\n${enabling ? "Enabling" : "Disabling"} observability for "${config.worker_name}"...`);
    await deploy(config.worker_name, {
      customDomain: config.custom_domain,
      observability: enabling,
    });

    config.observability = enabling;
    config.last_upgraded = new Date().toISOString();
    saveConfig(config);

    console.log(chalk.green(`\n  Observability ${enabling ? "enabled" : "disabled"} successfully.`));
    if (enabling) {
      console.log(chalk.dim("  Logs will appear in the Cloudflare dashboard within a few minutes.\n"));
    } else {
      console.log("");
    }
  } catch (err) {
    showError(`Failed to update observability: ${err.message}`);
    process.exit(1);
  }
}
