#!/usr/bin/env node
// Myco hook guard — silently no-ops when myco is not installed.
//
// This file is committed to the repo so open-source contributors without
// Myco don't see hook errors in their agent sessions. It stays deliberately
// thin: its only jobs are (1) provide a cross-platform entry point that
// works under every shell our symbionts fire hooks from, and (2) resolve
// which myco binary to exec via the layered runtime.command pin
// (project-scope `<project>/.myco/runtime.command` first, then machine-scope
// `~/.myco/runtime.command`).
//
// Managed by: myco init / myco update
// Safe to delete: myco remove
'use strict';

// Skip hooks for Myco's own agent pipeline sessions — they are internal
// and should not be captured as user sessions.
if (process.env.MYCO_AGENT_SESSION) process.exit(0);

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

// Defensively pin cwd to the project root. Cursor's hook spawn drops stdin
// when the command uses shell operators, so our installed hook commands
// invoke this guard directly (no `cd "$(...)" &&` prefix). The chdir keeps
// vault resolution working even when the spawning agent's cwd isn't set.
try { process.chdir(path.resolve(__dirname, '..')); } catch { /* best effort */ }

// Resolve which myco binary to invoke.
//
// `~/.myco/runtime.command` is the source of truth — a one-line plain-text
// file holding either a PATH-resolvable name (the default for globally-
// installed users is the file's absence) or an absolute path to a managed/
// dev binary (what `make dev-link` writes; what the beta-channel installer
// writes). Absolute paths bypass PATH entirely, which matters because GUI-
// launched agents (Cursor, Claude Code desktop, etc.) run under macOS
// launchd and inherit a minimal PATH that typically doesn't include
// `~/.local/bin`.
//
// Machine-scoped: there's exactly one daemon per machine, and the runtime
// that backs it is a machine-level choice, not per-project.
const args = process.argv.slice(2);
const bin = readLayeredRuntimeCommand() ?? 'myco';

function readPinFile(filePath) {
  try {
    const raw = fs.readFileSync(filePath, 'utf-8').trim();
    return raw || null;
  } catch { return null; }
}

function readProjectRuntimeCommand(startDir) {
  let dir = path.resolve(startDir);
  while (true) {
    const pin = readPinFile(path.join(dir, '.myco', 'runtime.command'));
    if (pin) return pin;
    const parent = path.dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

function readMachineRuntimeCommand() {
  const home = process.env.MYCO_HOME ? expandHome(process.env.MYCO_HOME) : path.join(os.homedir(), '.myco');
  return readPinFile(path.join(home, 'runtime.command'));
}

function readLayeredRuntimeCommand() {
  return readProjectRuntimeCommand(process.cwd()) ?? readMachineRuntimeCommand();
}

function expandHome(value) {
  if (value === '~') return os.homedir();
  if (value.startsWith(`~${path.sep}`)) return path.join(os.homedir(), value.slice(2));
  return value;
}

function toolNameFromArgs(args) {
  if (args[0] !== 'tool' || args[1] !== 'call') return undefined;
  for (let idx = 2; idx < args.length; idx++) {
    const arg = args[idx];
    if (arg === '--json') continue;
    if (arg === '--input') {
      idx++;
      continue;
    }
    if (arg && !arg.startsWith('-')) return arg;
  }
  return undefined;
}

function writeToolRuntimeUnavailable(command, args) {
  const tool = toolNameFromArgs(args);
  const envelope = {
    ok: false,
    ...(tool ? { tool } : {}),
    error: {
      code: 'runtime_unavailable',
      message: `Myco runtime command '${command}' could not be found. Check <project>/.myco/runtime.command and ~/.myco/runtime.command, or run Myco update from a shell where Myco is installed.`,
    },
  };
  process.stdout.write(`${JSON.stringify(envelope, null, 2)}\n`);
}

try {
  execFileSync(bin, args, { stdio: 'inherit' });
} catch (e) {
  if (e.code === 'ENOENT') {
    if (args[0] === 'tool') {
      writeToolRuntimeUnavailable(bin, args);
      process.exit(1);
    }
    process.exit(0);
  }
  process.exit(e.status ?? 1);
}
