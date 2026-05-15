// src/commands/destroy.mjs
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import prompts from "prompts";
import chalk from "chalk";
import { loadConfig, deleteConfig } from "../lib/config.mjs";
import { ensureWrangler, checkWranglerAuth, isGhAvailable } from "../lib/prerequisites.mjs";
import { deleteWorker, login } from "../lib/wrangler.mjs";
import { showError } from "../lib/display.mjs";

const execFileAsync = promisify(execFile);

export async function run(flags) {
  const config = loadConfig();
  if (!config) {
    showError("No deployment found. Nothing to destroy.");
    process.exit(1);
  }

  if (!flags.yes && !flags["non-interactive"]) {
    const answer = await prompts({
      type: "confirm",
      name: "confirm",
      message: `This will delete worker "${config.worker_name}" and all associated data. Are you sure?`,
      initial: false,
    });
    if (!answer.confirm) {
      console.log("Cancelled.");
      process.exit(0);
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
    console.log(`\nDeleting worker "${config.worker_name}"...`);
    try {
      await deleteWorker(config.worker_name);
      console.log("Worker deleted.");
    } catch (err) {
      if (err.message.includes("does not exist") || err.message.includes("10090")) {
        console.log(chalk.dim("  Worker already removed from Cloudflare. Cleaning up local config."));
      } else {
        throw err;
      }
    }

    if (config.auto_update_repo) {
      const ghOk = await isGhAvailable();
      if (ghOk) {
        let deleteRepo = flags.yes || flags["non-interactive"];
        if (!deleteRepo) {
          const answer = await prompts({
            type: "confirm",
            name: "deleteRepo",
            message: `Delete auto-update repo "${config.auto_update_repo}"?`,
            initial: false,
          });
          deleteRepo = answer.deleteRepo;
        }
        if (deleteRepo) {
          await execFileAsync("gh", ["repo", "delete", config.auto_update_repo, "--yes"], {
            timeout: 30_000,
          });
          console.log("Auto-update repo deleted.");
        }
      }
    }

    deleteConfig();
    console.log(chalk.green("\n  Worker removed. Cloudflare account and local config cleaned up.\n"));
  } catch (err) {
    showError(`Destroy failed: ${err.message}`);
    process.exit(1);
  }
}
