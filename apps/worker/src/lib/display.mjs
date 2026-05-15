// src/lib/display.mjs
import chalk from "chalk";
import { maskToken } from "./config.mjs";

export function showInstallSuccess({ workerUrl, agentToken, adminToken, relayToken, locationName }) {
  console.log("");
  console.log(chalk.green.bold("  Worker deployed successfully!"));
  console.log("");
  console.log(`  Worker URL: ${chalk.cyan(workerUrl)}`);
  console.log("");
  console.log(`  ${chalk.yellow("AGENT_TOKEN")}: ${agentToken}`);
  console.log(`    ${chalk.dim("→ Configure this in your AI agent (Claude, ChatGPT, n8n)")}`);
  console.log("");
  console.log(`  ${chalk.yellow("ADMIN_TOKEN")}: ${adminToken}`);
  console.log(`    ${chalk.dim("→ Save this — needed to manage locations")}`);
  console.log(`    ${chalk.dim("  Recoverable from ~/.unifi-mcp-worker/config.json")}`);
  console.log("");
  console.log(`  ${chalk.yellow("RELAY_TOKEN")}: ${relayToken}`);
  console.log(`    ${chalk.dim(`→ Configure in your relay sidecar for "${locationName}"`)}`);
  console.log("");
  console.log(chalk.bold("  Next steps:"));
  console.log(`  1. Configure your relay sidecar with:`);
  console.log(`     ${chalk.dim("UNIFI_RELAY_URL")}=${workerUrl}`);
  console.log(`     ${chalk.dim("UNIFI_RELAY_TOKEN")}=${relayToken}`);
  console.log(`     ${chalk.dim("UNIFI_RELAY_LOCATION_NAME")}=${locationName}`);
  console.log(`  2. Configure your AI agent with:`);
  console.log(`     ${chalk.dim("MCP URL")}: ${workerUrl}/mcp`);
  console.log(`     ${chalk.dim("Auth")}: Bearer ${agentToken}`);
  console.log("");
}

export function showStatus(config) {
  console.log("");
  console.log(chalk.bold("  UniFi MCP Worker Status"));
  console.log("");
  console.log(`  Worker:     ${config.worker_name} (${chalk.cyan(config.worker_url)})`);
  if (config.custom_domain) {
    console.log(`  Domain:     ${chalk.cyan(config.custom_domain)}`);
  }
  console.log(`  Locations:  ${config.locations?.length || 0}`);
  console.log("");

  if (config.locations?.length) {
    for (const loc of config.locations) {
      console.log(`    ${chalk.yellow(loc.location_name)} (${loc.location_id})`);
      console.log(`      Relay token: ${maskToken(loc.relay_token)}`);
    }
    console.log("");
  }

  console.log(`  Agent token: ${maskToken(config.agent_token)}`);
  console.log(`  Admin token: ${maskToken(config.admin_token)}`);
  console.log("");

  if (config.auto_update_repo) {
    console.log(`  Auto-update: ${chalk.green("enabled")} (${config.auto_update_repo})`);
  } else {
    console.log(`  Auto-update: ${chalk.dim("disabled")}`);
  }

  if (config.observability) {
    console.log(`  Observability: ${chalk.green("enabled")}`);
  } else {
    console.log(`  Observability: ${chalk.dim("disabled")}`);
  }

  if (config.last_upgraded) {
    console.log(`  Last upgraded: ${config.last_upgraded}`);
  }
  console.log("");
}

export function showAddLocationSuccess({ locationName, relayToken, workerUrl }) {
  console.log("");
  console.log(chalk.green.bold(`  Location "${locationName}" created!`));
  console.log("");
  console.log(`  ${chalk.yellow("RELAY_TOKEN")}: ${relayToken}`);
  console.log("");
  console.log(`  Configure a relay sidecar for this location with:`);
  console.log(`    ${chalk.dim("UNIFI_RELAY_URL")}=${workerUrl}`);
  console.log(`    ${chalk.dim("UNIFI_RELAY_TOKEN")}=${relayToken}`);
  console.log(`    ${chalk.dim("UNIFI_RELAY_LOCATION_NAME")}=${locationName}`);
  console.log("");
}

export function showError(message) {
  console.error(chalk.red(`  Error: ${message}`));
}
