# AGENTS.md — UniFi MCP Relay Worker

> Worker app rules. These rules apply inside `apps/worker/` in addition to the
> repository root `AGENTS.md`.

---

## 1. Project Identity

**UniFi MCP Relay Worker** is a CLI + Cloudflare Worker that relays MCP (Model Context Protocol) tool calls between cloud AI agents and locally-hosted UniFi MCP servers through a secure WebSocket relay.

Two workspaces live in one repo:

| Workspace | Language | Path | Purpose |
|-----------|----------|------|---------|
| **CLI** | Plain ESM (`.mjs`) | `bin/`, `src/`, `test/` | Deploys/manages the Worker via Wrangler |
| **Worker** | TypeScript (strict) | `worker/` | Cloudflare Worker + Durable Object relay |

---

## 2. Non-Goals

- This is NOT a general-purpose MCP framework. Do not add plugin systems, extensibility hooks, or abstract base classes.
- This is NOT a UniFi controller. The relay forwards tool calls — it MUST NOT implement UniFi business logic.
- Do not add a build/transpile step to the CLI. It ships as plain `.mjs` — no TypeScript, no bundler.
- Do not merge the CLI and Worker `node_modules`. They are intentionally separate (`npm ci` at root and `cd worker && npm ci`).

---

## 3. Architecture Invariants

### 3.1 Workspace Boundary

- CLI code MUST be plain ESM in `.mjs` files under `src/` and `bin/`.
- Worker code MUST be TypeScript in `.ts` files under `worker/src/`.
- The CLI MUST NOT import from `worker/`. The Worker MUST NOT import from `src/`.

### 3.2 Worker Structure

- `worker/src/index.ts` — HTTP fetch handler and routing. All inbound requests enter here.
- `worker/src/relay-object.ts` — Durable Object (`RelayObject`). All persistent state and WebSocket management lives here.
- `worker/src/mcp-handler.ts` — MCP JSON-RPC dispatch. Pure function, no side effects beyond calling the `RelayStub` interface.
- `worker/src/auth.ts` — Token generation, hashing, and validation. All auth primitives live here.
- `worker/src/types.ts` — All TypeScript interfaces and protocol constants. Shared types MUST be defined here, not inline.

New Worker source files SHOULD be added to `worker/src/` only when they represent a clearly distinct concern. Do not fragment into deep directory trees.

### 3.3 CLI Structure

- `bin/cli.mjs` — Entry point. Parses args and dispatches to command modules. MUST NOT contain business logic.
- `src/commands/*.mjs` — One file per CLI command. Each MUST export a `run(options)` function.
- `src/lib/*.mjs` — Shared utilities (config, API helpers, Wrangler wrappers, display, tokens, prerequisites).

### 3.4 Authentication

- All endpoints except `/health` MUST require Bearer token authentication.
- Token comparison MUST use the constant-time `timingSafeEqual` function from `worker/src/auth.ts`.
- Relay tokens MUST be stored as SHA-256 hashes (via `hashToken`), never plaintext.
- The CLI config file (`~/.unifi-mcp-worker/config.json`) MUST be written with mode `0o600` and its directory with `0o700`.

### 3.5 Protocol

- The relay uses JSON-RPC 2.0 for the MCP interface (POST `/mcp`).
- WebSocket messages between relay clients and the Durable Object use the typed message format defined in `worker/src/types.ts` (`InboundMessage`, `OutboundMessage`).
- Protocol constants (`PROTOCOL_VERSION`, `TOOL_CALL_TIMEOUT_MS`, etc.) MUST be defined in `worker/src/types.ts`, not hardcoded elsewhere.

### 3.6 Durable Object

- The relay uses a singleton Durable Object (`env.RELAY.idFromName("singleton")`).
- The Durable Object uses SQLite for persistent location/token storage (configured in `wrangler.toml` via `new_sqlite_classes`).
- Meta-tools (`unifi_tool_index`, `unifi_execute`, `unifi_batch`, `unifi_location_timeline`) are defined in `relay-object.ts` and handled by the relay itself — they MUST NOT be forwarded to relay clients.

### 3.7 Dependencies

- The CLI has minimal runtime dependencies (`prompts`, `chalk`). Do not add heavy dependencies without justification.
- The Worker has zero runtime dependencies — only `devDependencies` for types, TypeScript, Vitest, and Wrangler.
- Worker MUST NOT add runtime `dependencies`. Cloudflare Workers bundle everything at deploy time; only `devDependencies` are appropriate.

---

## 4. Golden Paths

### 4.1 Add a New CLI Command

1. Create `src/commands/<name>.mjs` exporting `async function run(options) { ... }`.
2. Register the command in the `COMMANDS` map in `bin/cli.mjs`.
3. Add `--help` text for the command in the help string in `bin/cli.mjs`.
4. Add any new flags to the `parseArgs` options in `bin/cli.mjs`.
5. Add tests at `test/cli/<name>.test.mjs` using `node:test` and `node:assert/strict`.
6. Run `make check` to verify.

### 4.2 Add a New Worker Endpoint

1. Add the route handler in `worker/src/index.ts` following the existing `if (url.pathname === ...)` pattern.
2. All authenticated routes MUST call `validateBearerToken` before proceeding.
3. Add tests at `worker/test/<module>.test.ts` using Vitest.
4. Run `make check` to verify.

### 4.3 Add a New Meta-Tool

1. Define the `ToolInfo` constant in `worker/src/relay-object.ts` alongside the existing `META_TOOL_*` constants.
2. Add it to the `META_TOOLS` array.
3. Add the handler case in the Durable Object's tool dispatch logic.
4. Add tests at `worker/test/relay-object.test.ts`.
5. Run `make check` to verify.

### 4.4 Add a New Type or Interface

1. All shared types MUST go in `worker/src/types.ts`.
2. Import types with `import type { ... }` (not value imports) when used only for type checking.
3. Run `cd worker && npm run typecheck` to verify.

### 4.5 Modify Authentication Logic

1. All auth functions live in `worker/src/auth.ts`.
2. Token comparison MUST remain constant-time. Do not introduce early-return comparisons.
3. Tests at `worker/test/auth.test.ts` MUST cover both positive and negative cases.

---

## 5. Quality Gates

Before considering work complete, the following MUST pass:

```bash
make check
```

This runs:

| Step | Command | What it verifies |
|------|---------|-----------------|
| Typecheck | `cd worker && npm run typecheck` | Worker TypeScript compiles with `--strict --noEmit` |
| CLI tests | `npm test` | `node --test test/cli/*.test.mjs` |
| Worker tests | `npm run test:worker` | `cd worker && vitest run` |

### Test Conventions

- **CLI tests** MUST use `node:test` (`describe`, `it`) and `node:assert/strict`. No third-party test runners.
- **Worker tests** MUST use Vitest (`describe`, `it`, `expect`).
- Test files MUST mirror source files: `src/lib/foo.mjs` -> `test/cli/foo.test.mjs`, `worker/src/bar.ts` -> `worker/test/bar.test.ts`.
- Tests MUST NOT depend on network access, running workers, or real Cloudflare infrastructure.

### CI

CI runs on Node 22, ubuntu-latest. The pipeline is:

1. `npm ci` + `cd worker && npm ci`
2. `cd worker && npm run typecheck`
3. `npm test`
4. `npm run test:worker`

If CI fails, the PR MUST NOT be merged.

---

## 6. Release Process

Releases are tag-triggered. Do NOT manually edit `package.json` version on `main`.

1. Create and push a namespaced semver tag from the monorepo root: `git tag worker/v1.2.3 && git push origin worker/v1.2.3`
2. CI validates, tests, packs, creates a GitHub Release, and publishes to npm with provenance.
3. A post-publish job syncs the version back to `main` (`chore: sync version to X.Y.Z [skip ci]`).

---

## 7. Security Considerations

- Secrets (`AGENT_TOKEN`, `ADMIN_TOKEN`, relay tokens) MUST NEVER appear in logs, error messages, or test output.
- The `.dev.vars` and `.env` files are gitignored and MUST remain so.
- Config files written to disk MUST use restrictive permissions (`0o600` for files, `0o700` for directories).
- Token generation MUST use `crypto.getRandomValues` (32 bytes, URL-safe base64).
