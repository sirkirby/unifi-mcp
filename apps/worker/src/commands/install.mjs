// src/commands/install.mjs
import prompts from "prompts";
import { loadConfig, saveConfig, deleteConfig } from "../lib/config.mjs";
import { generateToken } from "../lib/tokens.mjs";
import { ensureWrangler, checkWranglerAuth } from "../lib/prerequisites.mjs";
import { deploy, putSecret, login } from "../lib/wrangler.mjs";
import { createLocationToken } from "../lib/api.mjs";
import { showInstallSuccess, showError } from "../lib/display.mjs";

export async function run(flags) {
  const existing = loadConfig();
  if (existing && !existing.setup_incomplete) {
    if (flags.force) {
      console.log("Overwriting existing config (--force).");
      deleteConfig();
    } else {
      showError("A deployment already exists. Run 'unifi-mcp-worker status' to see it.");
      showError("To start fresh, run 'unifi-mcp-worker destroy' first, or use 'unifi-mcp-worker install --force'.");
      process.exit(1);
    }
  }

  const wranglerOk = await ensureWrangler();
  if (!wranglerOk) process.exit(1);

  const authed = await checkWranglerAuth();
  if (!authed) {
    console.log("You need to log in to Cloudflare.");
    await login();
  }

  const resuming = existing?.setup_incomplete;
  const resumeFrom = resuming ? existing._resume_step || "deploy" : "deploy";

  let workerName, locationName, customDomain, observability;

  if (resuming) {
    workerName = existing.worker_name;
    customDomain = existing.custom_domain || null;
    locationName = existing._location_name || flags["location-name"] || "Home Lab";
    observability = existing.observability || false;
    console.log(`Resuming install for "${workerName}" from ${resumeFrom} step...`);
  } else if (flags["non-interactive"]) {
    workerName = flags["worker-name"] || "unifi-mcp-relay";
    locationName = flags["location-name"] || "Home Lab";
    observability = flags.observability || false;
  } else {
    const answers = await prompts([
      {
        type: "text",
        name: "workerName",
        message: "Worker name",
        initial: "unifi-mcp-relay",
      },
      {
        type: "text",
        name: "baseDomain",
        message: "Base domain (leave blank for default *.workers.dev)",
        initial: "",
      },
      {
        type: "text",
        name: "locationName",
        message: "Location name for your first relay",
        initial: "Home Lab",
      },
      {
        type: "confirm",
        name: "observability",
        message: "Enable observability? (logs stored 7 days in Cloudflare dashboard)",
        initial: false,
      },
    ]);
    workerName = answers.workerName;
    customDomain = answers.baseDomain ? `${answers.workerName}.${answers.baseDomain}` : null;
    locationName = answers.locationName;
    observability = answers.observability;
  }

  if (!workerName || !locationName) {
    showError("Worker name and location name are required.");
    process.exit(1);
  }

  const agentToken = resuming ? existing.agent_token : generateToken();
  const adminToken = resuming ? existing.admin_token : generateToken();

  try {
    let workerUrl = existing?.worker_url;

    if (resumeFrom === "deploy") {
      console.log(`\nDeploying worker "${workerName}"...`);
      const result = await deploy(workerName, { customDomain, observability });
      workerUrl = result.workerUrl;
      if (!workerUrl) {
        workerUrl = `https://${workerName}.workers.dev`;
      }
      console.log(`Deployed to ${workerUrl}`);

      saveConfig({
        setup_incomplete: true,
        _resume_step: "secrets",
        _location_name: locationName,
        worker_name: workerName,
        worker_url: workerUrl,
        custom_domain: customDomain || null,
        observability,
        agent_token: agentToken,
        admin_token: adminToken,
        locations: [],
        created_at: new Date().toISOString(),
      });
    }

    if (resumeFrom === "deploy" || resumeFrom === "secrets") {
      console.log("Setting AGENT_TOKEN...");
      await putSecret(workerName, "AGENT_TOKEN", agentToken);
      console.log("Setting ADMIN_TOKEN...");
      await putSecret(workerName, "ADMIN_TOKEN", adminToken);

      const cfg = loadConfig();
      cfg._resume_step = "location";
      saveConfig(cfg);
    }

    if (resumeFrom === "deploy" || resumeFrom === "secrets" || resumeFrom === "location") {
      console.log(`Creating location "${locationName}"...`);
      await new Promise((r) => setTimeout(r, 3000));

      const loc = await createLocationToken(
        workerUrl || existing?.worker_url,
        adminToken || existing?.admin_token,
        locationName
      );

      saveConfig({
        worker_name: workerName,
        worker_url: workerUrl || existing?.worker_url,
        custom_domain: customDomain || null,
        observability,
        agent_token: agentToken || existing?.agent_token,
        admin_token: adminToken || existing?.admin_token,
        locations: [
          {
            location_name: locationName,
            relay_token: loc.relayToken,
            location_id: loc.locationId,
            created_at: new Date().toISOString(),
          },
        ],
        auto_update_repo: null,
        created_at: existing?.created_at || new Date().toISOString(),
        last_upgraded: new Date().toISOString(),
      });

      showInstallSuccess({
        workerUrl: workerUrl || existing?.worker_url,
        agentToken: agentToken || existing?.agent_token,
        adminToken: adminToken || existing?.admin_token,
        relayToken: loc.relayToken,
        locationName,
      });
    }
  } catch (err) {
    showError(`Install failed: ${err.message}`);
    console.error("\nPartial state saved. Re-run 'unifi-mcp-worker install' to resume.");
    process.exit(1);
  }
}
