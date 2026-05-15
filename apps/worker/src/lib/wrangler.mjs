// src/lib/wrangler.mjs
import { execFile, spawn } from "node:child_process";
import { promisify } from "node:util";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const execFileAsync = promisify(execFile);

function getWorkerDir() {
  const cliDir = dirname(fileURLToPath(import.meta.url));
  return join(cliDir, "..", "..", "worker");
}

/**
 * Pure function: takes base wrangler.toml content and options,
 * returns the modified TOML string for deploy.
 */
export function buildWranglerToml(originalToml, { customDomain, observability } = {}) {
  let toml = originalToml;

  if (customDomain) {
    // Remove any existing [[routes]] blocks, then append the new one
    toml = toml.replace(/\n*\[\[routes\]\]\n[^\[]*/g, "");
    const routeBlock = `\n[[routes]]\npattern = "${customDomain}"\ncustom_domain = true\n`;
    toml = toml.trimEnd() + "\n" + routeBlock;
  }

  if (observability) {
    // Strip the [observability] block this function emits (canonical format only)
    toml = toml.replace(/\n*\[observability\]\n(\[observability\.\w+\]\n)?[^\[]*/g, "");
    const obsBlock = `\n[observability]\n[observability.logs]\nenabled = true\ninvocation_logs = true\n`;
    toml = toml.trimEnd() + "\n" + obsBlock;
  }

  return toml;
}

export async function deploy(workerName, { customDomain, observability } = {}) {
  const workerDir = getWorkerDir();
  const wranglerToml = join(workerDir, "wrangler.toml");

  // Install worker dependencies (including devDependencies — wrangler and
  // @cloudflare/workers-types are devDeps needed for the build step)
  await execFileAsync("npm", ["install"], {
    cwd: workerDir,
    timeout: 120_000,
  });

  const { readFileSync, writeFileSync } = await import("node:fs");
  const originalToml = readFileSync(wranglerToml, "utf8");
  const modifiedToml = buildWranglerToml(originalToml, { customDomain, observability });

  if (modifiedToml !== originalToml) {
    writeFileSync(wranglerToml, modifiedToml);
  }

  try {
    const args = ["deploy", "--name", workerName];
    const { stdout, stderr } = await execFileAsync("wrangler", args, {
      cwd: workerDir,
      timeout: 120_000,
    });
    // Parse the worker URL from wrangler output
    const output = stdout + stderr;
    const urlMatch = output.match(/https:\/\/[\w.-]+\.workers\.dev/);
    const workerUrl = customDomain
      ? `https://${customDomain}`
      : urlMatch ? urlMatch[0] : null;
    return { stdout, stderr, workerUrl };
  } finally {
    // Restore original wrangler.toml so the bundled source stays clean
    writeFileSync(wranglerToml, originalToml);
  }
}

export async function putSecret(workerName, secretName, secretValue) {
  const workerDir = getWorkerDir();
  return new Promise((resolve, reject) => {
    const child = spawn("wrangler", ["secret", "put", secretName, "--name", workerName], {
      cwd: workerDir,
      stdio: ["pipe", "pipe", "pipe"],
    });
    child.stdin.write(secretValue);
    child.stdin.end();
    let stderr = "";
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("close", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`wrangler secret put ${secretName} failed (code ${code}): ${stderr}`));
    });
    child.on("error", reject);
  });
}

export async function deleteWorker(workerName) {
  const workerDir = getWorkerDir();
  await execFileAsync("wrangler", ["delete", "--name", workerName, "--force"], {
    cwd: workerDir,
    timeout: 30_000,
  });
}

export async function login() {
  return new Promise((resolve, reject) => {
    const child = spawn("wrangler", ["login"], { stdio: "inherit" });
    child.on("close", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`wrangler login exited with code ${code}`));
    });
  });
}
