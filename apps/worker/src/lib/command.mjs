// src/lib/command.mjs

// npm and wrangler are installed as .cmd shims on Windows. Node only runs
// .cmd/.bat files through a shell, so a plain execFile/spawn of "npm" or
// "wrangler" fails there with ENOENT.
const SAFE_WINDOWS_ARG = /^[\w.,:/@=+-]+$/;

function quoteWindowsArg(arg) {
  const value = String(arg);
  if (SAFE_WINDOWS_ARG.test(value)) return value;
  return `"${value.replace(/"/g, '""')}"`;
}

// Cloudflare Worker names are letters, digits, dashes and underscores. Checking
// this keeps a typed name from reaching cmd.exe, which expands %VAR% even
// inside double quotes.
const WORKER_NAME = /^[A-Za-z0-9][A-Za-z0-9_-]{0,62}$/;

export function assertWorkerName(name) {
  if (typeof name !== "string" || !WORKER_NAME.test(name)) {
    throw new Error(
      `Invalid worker name "${name}": use up to 63 letters, digits, dashes or underscores, starting with a letter or digit.`,
    );
  }
  return name;
}

/**
 * Returns the file, args and extra options to pass to execFile/spawn so that
 * `cmd` resolves the same way it does in a terminal on every platform.
 */
export function resolveCommand(cmd, args = [], platform = process.platform) {
  if (platform !== "win32") {
    return { file: cmd, args, options: {} };
  }
  // Pass one pre-quoted command line rather than args + shell: true, which
  // Node deprecates (DEP0190) because the args would not be escaped.
  const line = [cmd, ...args].map(quoteWindowsArg).join(" ");
  return { file: line, args: [], options: { shell: true } };
}
