// src/commands/add-location.mjs
import prompts from "prompts";
import { loadConfig, saveConfig } from "../lib/config.mjs";
import { healthCheck, createLocationToken } from "../lib/api.mjs";
import { showAddLocationSuccess, showError } from "../lib/display.mjs";

export async function run(flags) {
  const config = loadConfig();
  if (!config) {
    showError("No deployment found. Run 'unifi-mcp-worker install' first.");
    process.exit(1);
  }

  let locationName, workerUrl, adminToken;

  if (flags["non-interactive"]) {
    locationName = flags["location-name"];
    workerUrl = flags["worker-url"] || config.worker_url;
    adminToken = flags["admin-token"] || config.admin_token;
    if (!locationName) {
      showError("--location-name is required in non-interactive mode.");
      process.exit(1);
    }
  } else {
    const answers = await prompts([
      {
        type: "text",
        name: "locationName",
        message: "Location name",
        validate: (v) => (v ? true : "Location name is required"),
      },
      {
        type: "text",
        name: "workerUrl",
        message: "Worker URL",
        initial: config.worker_url,
      },
      {
        type: "text",
        name: "adminToken",
        message: "Admin token",
        initial: config.admin_token,
      },
    ]);
    locationName = answers.locationName;
    workerUrl = answers.workerUrl;
    adminToken = answers.adminToken;
  }

  console.log("\nChecking worker health...");
  const health = await healthCheck(workerUrl);
  if (!health.ok) {
    showError(`Worker not reachable at ${workerUrl}`);
    console.error("  Check that:");
    console.error("  - The URL is correct");
    console.error("  - The worker is deployed (run 'unifi-mcp-worker status')");
    console.error("  - Cloudflare is not experiencing issues");
    if (health.error) console.error(`  Error: ${health.error}`);
    process.exit(1);
  }

  try {
    console.log(`Creating location "${locationName}"...`);
    const loc = await createLocationToken(workerUrl, adminToken, locationName);

    const existingIdx = config.locations.findIndex(
      (l) => l.location_name === locationName
    );
    if (existingIdx >= 0) {
      config.locations[existingIdx].relay_token = loc.relayToken;
      config.locations[existingIdx].location_id = loc.locationId;
    } else {
      config.locations.push({
        location_name: locationName,
        relay_token: loc.relayToken,
        location_id: loc.locationId,
        created_at: new Date().toISOString(),
      });
    }

    saveConfig(config);

    showAddLocationSuccess({
      locationName,
      relayToken: loc.relayToken,
      workerUrl,
    });
  } catch (err) {
    showError(`Failed to create location: ${err.message}`);
    process.exit(1);
  }
}
