import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export async function checkCommand(cmd, args = ["--version"]) {
  try {
    const { stdout } = await execFileAsync(cmd, args, { timeout: 10_000 });
    const version = stdout.trim().replace(/^v/, "");
    return { available: true, version };
  } catch {
    return { available: false, version: null };
  }
}

export function getNodeVersion() {
  return parseInt(process.version.replace("v", "").split(".")[0], 10);
}

export async function ensureWrangler() {
  const result = await checkCommand("wrangler", ["--version"]);
  if (result.available) return true;

  console.log("Wrangler not found. Installing...");
  try {
    await execFileAsync("npm", ["install", "-g", "wrangler"], { timeout: 120_000 });
    return true;
  } catch (err) {
    console.error("Failed to install wrangler:", err.message);
    console.error("Install manually: npm install -g wrangler");
    return false;
  }
}

export async function checkWranglerAuth() {
  try {
    const { stdout } = await execFileAsync("wrangler", ["whoami"], { timeout: 15_000 });
    if (stdout.includes("not authenticated") || stdout.includes("not logged in")) {
      return false;
    }
    return true;
  } catch {
    return false;
  }
}

export async function isGhAvailable() {
  const result = await checkCommand("gh", ["--version"]);
  return result.available;
}
