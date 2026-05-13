// Managed by Myco. Regenerated on `myco update`. Edit src/symbionts/templates/opencode/plugin.ts in the Myco repo instead.
// myco:plugin-marker:opencode
//
// Myco Codebase Intelligence Plugin for OpenCode.
//
// This plugin runs inside opencode's Bun runtime and communicates with the local
// Myco daemon over HTTP — no subprocess spawns, no hook CLI, no stdin piping.
//
//   Capture: POST /sessions/register, /sessions/unregister, /events, /events/stop
//   Context: GET  /api/digest
//   Inject:  client.session.prompt({ noReply: true, parts: [{ synthetic: true }] })
//
// See https://opencode.ai/docs/plugins/
//
// Degraded-mode safety: this plugin ships committed inside any project that has
// run `myco init` — the file lives at .opencode/plugins/myco.ts in that project's
// repo. When a teammate clones such a project WITHOUT having Myco installed
// locally, opencode will still load this plugin (the file is right there in the
// cloned repo). To stay invisible in that case, the plugin has NO external
// runtime imports — only node:fs and node:path, which are always available in
// Bun's runtime. Every path that would contact the Myco daemon gracefully no-ops
// when `.myco/daemon.json` is absent or the daemon is unreachable, so the plugin
// becomes invisible rather than throwing. Do NOT add runtime imports from
// @opencode-ai/plugin or any other package — that would break this guarantee.

import { readFileSync, appendFileSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { execFileSync } from "node:child_process";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/**
 * Keep in sync with `TOOL_OUTPUT_PREVIEW_CHARS` in src/constants.ts (currently 200).
 * The plugin file is standalone and cannot import from Myco — this value is copied
 * so every symbiont records tool_output previews at the same length.
 */
const TOOL_OUTPUT_PREVIEW_CHARS = 200;

/** Timeout for daemon HTTP calls — must be short so we never block opencode. */
const MYCO_FETCH_TIMEOUT_MS = 3000;

/** Tail window read from opencode when building the end-of-turn assistant summary. */
const SESSION_IDLE_TAIL_LIMIT = 12;

/**
 * Widened retry window when the initial tail returns no assistant text.
 * Happens when the last 12 events are all tool calls, or compaction just
 * rewrote history. A NULL response_summary is worse than spending one
 * extra round-trip to recover a real one.
 */
const SESSION_IDLE_TAIL_LIMIT_RETRY = 60;

/** Max size of resume context injection to keep resumed sessions lean. */
const RESUME_CONTEXT_MAX_CHARS = 4000;

const REQUEST_CONTEXT_HEADERS = {
  projectRoot: "x-myco-project-root",
  projectId: "x-myco-project-id",
  sessionId: "x-myco-session-id",
} as const;

/** Heading prefix for compaction context — makes Myco's contribution recognizable in the compacted summary. */
const COMPACTION_HEADING = "## Myco — Project Context (preserved across compaction)\n\n";

/**
 * Marker set on the `metadata` field of every synthetic TextPartInput this
 * plugin injects via `client.session.prompt({ noReply: true, ... })`. The
 * `chat.message` handler checks for this marker and skips matching messages
 * so the injection doesn't re-enter as if it were a new user prompt.
 *
 * Why not the `synthetic` flag? opencode's own prompt.ts uses `synthetic: true`
 * for ~20 distinct internal purposes (plan-mode prompts, build-switch
 * transitions, subagent task summaries, shell-impl wrappers). Filtering on
 * the synthetic flag rejects legitimate user messages whenever opencode has
 * appended one of its own synthetic parts — which caused real user prompts
 * to silently drop in live testing.
 */
const MYCO_METADATA_MARKER = "myco";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type MessagePart = { type?: string; text?: string };
type SessionMessage = { info?: { role?: string }; parts?: MessagePart[] };

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function pickString(
  record: Record<string, unknown>,
  keys: readonly string[],
): string | undefined {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.length > 0) return value;
  }
  return undefined;
}

export function normalizeToolInput(toolInput: unknown): unknown {
  if (!isRecord(toolInput)) return toolInput;

  const filePath = pickString(toolInput, ["file_path", "filePath", "path"]);
  const workdir = pickString(toolInput, ["workdir", "cwd"]);
  const command = pickString(toolInput, ["command", "cmd"]);

  return {
    ...toolInput,
    ...(filePath ? { file_path: filePath } : {}),
    ...(workdir ? { workdir } : {}),
    ...(command ? { command } : {}),
  };
}

export function collectAssistantSummaryFromMessages(messages: SessionMessage[]): string {
  const summaryParts: string[] = [];
  let foundAssistantBlock = false;

  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message?.info?.role !== "assistant") {
      if (foundAssistantBlock) break;
      continue;
    }

    foundAssistantBlock = true;
    const text = (message.parts ?? [])
      .filter((part) => part.type === "text" && part.text)
      .map((part) => part.text as string)
      .join("\n")
      .trim();
    if (text) summaryParts.unshift(text);
  }

  return summaryParts.join("\n").trim();
}

// ---------------------------------------------------------------------------
// Daemon HTTP transport — all communication with the local Myco daemon.
// Every function is best-effort: failures are swallowed so the plugin cannot
// interfere with opencode when Myco is absent or the daemon is unreachable.
// ---------------------------------------------------------------------------

/**
 * Port cache for the Myco daemon state file. Read once on first access; refreshed on
 * the next call that follows a failed HTTP request (handles daemon restarts
 * mid-session). `undefined` = never loaded, `null` = loaded but absent.
 */
let cachedDaemonPort: { statePath: string; port: number | null } | undefined = undefined;

/**
 * Active opencode sessions tracked by this plugin instance. Populated on
 * `session.created` and drained on `session.deleted` / `server.instance.disposed`.
 *
 * Opencode has no `session.end` event — when the TUI exits normally (Ctrl+C,
 * close terminal), the session stays "active" from the daemon's perspective
 * until the session-maintenance job sweeps it (1-hour threshold). To close
 * sessions cleanly on TUI exit, we track them locally and call unregister
 * for each one when `server.instance.disposed` fires.
 */
const activeOpencodeSessions = new Set<string>();

/** Resume injections are process-local and should run at most once per session. */
const resumeInjectedSessions = new Set<string>();

/** Parent batch of the current turn, or null between turns. Non-null => a turn is in progress. */
let currentParentBatchId: number | null = null;

function resolveMycoHome(): string {
  const configured = process.env.MYCO_HOME?.trim();
  if (!configured) return join(homedir(), ".myco");
  if (configured === "~") return homedir();
  if (configured.startsWith("~/")) return join(homedir(), configured.slice(2));
  return configured;
}

function projectUsesGrove(directory: string): boolean {
  try {
    const raw = readFileSync(join(directory, ".myco", "project.toml"), "utf-8");
    return /\[grove\][^\[]*\bid\s*=/.test(raw);
  } catch {
    return false;
  }
}

function readTomlString(raw: string, section: string, key: string): string | null {
  let currentSection: string | null = null;
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    const header = /^\[([^\]]+)\]$/.exec(trimmed);
    if (header) {
      currentSection = header[1];
      continue;
    }
    if (currentSection !== section) continue;
    const match = /^([A-Za-z0-9_-]+)\s*=\s*["']([^"']*)["']/.exec(trimmed);
    if (match?.[1] === key) return match[2];
  }
  return null;
}

function buildRequestContextHeaders(directory: string): Record<string, string> {
  try {
    const raw = readFileSync(join(directory, ".myco", "project.toml"), "utf-8");
    const projectId = readTomlString(raw, "project", "id");
    if (!projectId) return {};
    return {
      [REQUEST_CONTEXT_HEADERS.projectRoot]: resolve(directory),
      [REQUEST_CONTEXT_HEADERS.projectId]: projectId,
      ...(process.env.MYCO_SESSION_ID ? { [REQUEST_CONTEXT_HEADERS.sessionId]: process.env.MYCO_SESSION_ID } : {}),
    };
  } catch {
    return {};
  }
}

function withRequestContextHeaders(directory: string, init?: RequestInit): RequestInit {
  const headers = new Headers(init?.headers);
  for (const [key, value] of Object.entries(buildRequestContextHeaders(directory))) {
    if (!headers.has(key)) headers.set(key, value);
  }
  return { ...init, headers };
}

function resolveDaemonStatePath(directory: string): string {
  return projectUsesGrove(directory)
    ? join(resolveMycoHome(), "service", "daemon.json")
    : join(directory, ".myco", "daemon.json");
}

/** Read the Myco daemon port from project-local or global daemon state. */
function readDaemonPortFromDisk(statePath: string): number | null {
  try {
    const raw = readFileSync(statePath, "utf-8");
    const info = JSON.parse(raw) as { port?: number };
    return typeof info.port === "number" ? info.port : null;
  } catch {
    return null;
  }
}

/** Get the cached daemon port, loading from disk on first access. */
function getDaemonPort(directory: string): number | null {
  const statePath = resolveDaemonStatePath(directory);
  if (!cachedDaemonPort || cachedDaemonPort.statePath !== statePath) {
    cachedDaemonPort = { statePath, port: readDaemonPortFromDisk(statePath) };
  }
  return cachedDaemonPort.port;
}

/** Force-refresh the daemon port from disk — used after a fetch failure in case the daemon restarted. */
function refreshDaemonPort(directory: string): number | null {
  const statePath = resolveDaemonStatePath(directory);
  cachedDaemonPort = { statePath, port: readDaemonPortFromDisk(statePath) };
  return cachedDaemonPort.port;
}

/** Fetch with a short timeout. Returns the Response on success, null on failure. */
async function fetchWithTimeout(url: string, init?: RequestInit): Promise<Response | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), MYCO_FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(url, { ...init, signal: controller.signal });
    return res.ok ? res : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Fetch from a daemon endpoint with a single retry after refreshing the port.
 * The retry handles the case where the daemon restarted on a different port
 * mid-session; the cache hot-path avoids a sync disk read on every HTTP call.
 */
async function fetchFromDaemon(
  directory: string,
  path: string,
  init?: RequestInit,
): Promise<Response | null> {
  const port = getDaemonPort(directory);
  if (!port) return null;
  const requestInit = withRequestContextHeaders(directory, init);

  const first = await fetchWithTimeout(`http://localhost:${port}${path}`, requestInit);
  if (first) return first;

  // Retry once with a refreshed port — the daemon may have restarted.
  const freshPort = refreshDaemonPort(directory);
  if (!freshPort || freshPort === port) return null;
  return fetchWithTimeout(`http://localhost:${freshPort}${path}`, requestInit);
}

/**
 * POST JSON to a daemon endpoint.
 * Returns `{ ok, data }` — `ok` is true when the HTTP call succeeded, `data`
 * is the parsed response body (may be absent if the body was empty or not JSON).
 */
async function postJson(
  directory: string,
  path: string,
  body: Record<string, unknown>,
): Promise<{ ok: boolean; data?: unknown }> {
  const res = await fetchFromDaemon(directory, path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res) return { ok: false };
  try {
    return { ok: true, data: await res.json() };
  } catch {
    return { ok: true };
  }
}

// <myco:shared-helpers>
// ---------------------------------------------------------------------------
// Shared plugin helpers — single source of truth for buffer/POST + batch kinds.
//
// This block is maintained in
//   src/symbionts/templates/_shared/plugin-helpers.ts.snippet
// and injected into each plugin file at install time by SymbiontInstaller.
// The plugin files on disk also carry an inline copy between the
// `// <myco:shared-helpers>` markers so they stay valid TypeScript for
// Vitest imports; a unit test enforces the inline copy matches the snippet.
//
// Contract: the snippet assumes the containing file has already defined
//   - `postJson(directory: string, path: string, body): Promise<{ok, data?}>`
//   - no other imports from the outer file
// and exposes
//   - `BATCH_KIND` constants + `BatchKind` type
//   - `bufferEvent(dir, sessionId, event)` — best-effort JSONL append
//   - `isIgnoredResponse(data)` — true when daemon returned an "ignored" drop
//   - `postEventWithBuffer(dir, sessionId, event)` — live POST with buffer fallback
//
// DO NOT edit this block inside a plugin file directly — edit the snippet
// and run the installer (or rerun the template-sync test to update the
// inlined copy). Changes here apply to every plugin the next time it
// installs/updates.
// ---------------------------------------------------------------------------

/**
 * Discriminated vocabulary for `prompt_batches.kind`. Mirrors
 * `BATCH_KIND` in src/db/queries/batches.ts — plugins can't import daemon
 * code, so the constants are inlined here and kept in sync via the shared
 * snippet + its sync test.
 */
const BATCH_KIND = {
  INITIAL: "initial",
  STEERING: "steering",
  INTERRUPT: "interrupt",
} as const;
type BatchKind = typeof BATCH_KIND[keyof typeof BATCH_KIND];

/**
 * Append an event to `.myco/buffer/<session-id>.jsonl` for replay by the
 * daemon's startup reconciler. On-disk shape intentionally matches
 * `src/capture/buffer.ts`'s EventBuffer — the plugin can't import it because
 * of the zero-runtime-dep constraint, so the protocol is the contract.
 */
function bufferEvent(
  directory: string,
  sessionId: string,
  event: Record<string, unknown>,
): void {
  try {
    const bufferDir = join(directory, ".myco", "buffer");
    mkdirSync(bufferDir, { recursive: true });
    const filePath = join(bufferDir, `${sessionId}.jsonl`);
    // Strip session_id from the entry — it's encoded in the filename
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { session_id: _sid, ...payload } = event;
    const line = JSON.stringify({
      ...payload,
      timestamp: payload.timestamp ?? new Date().toISOString(),
    });
    appendFileSync(filePath, line + "\n");
  } catch {
    // Best-effort — never crash the host agent.
  }
}

/** True when the daemon returned 200 but signalled it dropped the event. */
function isIgnoredResponse(data: unknown): boolean {
  if (data === null || typeof data !== "object") return false;
  const ignored = (data as { ignored?: unknown }).ignored;
  return typeof ignored === "string" && ignored.length > 0;
}

/**
 * POST a capture event to the daemon, buffering to disk on failure. Both
 * transport failures and server-side "ignored" responses route to the
 * buffer — rule bugs have silently dropped whole live sessions before, and
 * the buffer is the recovery path once the cause is fixed.
 */
async function postEventWithBuffer(
  directory: string,
  sessionId: string,
  event: Record<string, unknown>,
): Promise<unknown> {
  const result = await postJson(directory, "/events", event);
  if (!result.ok || isIgnoredResponse(result.data)) {
    bufferEvent(directory, sessionId, event);
    return undefined;
  }
  return result.data;
}
// </myco:shared-helpers>

/**
 * Cheap best-effort branch detection so opencode session registrations carry
 * the same branch hint hook-based symbionts already supply. Failures (no Git,
 * stale repo, timeout) return undefined — the daemon handles authoritative
 * provenance capture asynchronously regardless.
 */
function detectGitBranch(directory: string): string | undefined {
  try {
    const out = execFileSync("git", ["-C", directory, "rev-parse", "--abbrev-ref", "HEAD"], {
      encoding: "utf-8",
      timeout: 1000,
      stdio: ["pipe", "pipe", "pipe"],
    }).trim();
    return out && out !== "HEAD" ? out : undefined;
  } catch {
    return undefined;
  }
}

/** Register an opencode session with the daemon. */
async function mycoRegisterSession(
  directory: string,
  sessionId: string,
  parentSessionId: string | undefined,
): Promise<void> {
  await postJson(directory, "/sessions/register", {
    session_id: sessionId,
    agent: "opencode",
    parent_session_id: parentSessionId,
    branch: detectGitBranch(directory),
    started_at: new Date().toISOString(),
  });
}

/** Unregister an opencode session. */
async function mycoUnregisterSession(directory: string, sessionId: string): Promise<void> {
  await postJson(directory, "/sessions/unregister", { session_id: sessionId });
}

/** Post a user prompt event. Images, if any, are shipped as an array of
 * `{ data: base64, mediaType }` objects — the daemon's event dispatcher persists
 * them as attachments keyed to the newly-opened prompt batch.
 *
 * Opencode has no on-disk transcript for Myco to mine, so images attached by
 * the user in the TUI must travel with the prompt event itself. Other symbionts
 * (claude-code, cursor) extract images from their JSONL transcripts at stop time.
 */
async function mycoPostUserPrompt(
  directory: string,
  sessionId: string,
  prompt: string,
  images: Array<{ data: string; mediaType: string }>,
): Promise<{ batchId?: number }> {
  const kind: BatchKind = currentParentBatchId !== null ? BATCH_KIND.STEERING : BATCH_KIND.INITIAL;
  const parentPromptBatchId = kind === BATCH_KIND.INITIAL ? null : currentParentBatchId;

  const result = await postEventWithBuffer(directory, sessionId, {
    type: "user_prompt",
    session_id: sessionId,
    agent: "opencode",
    prompt,
    kind,
    parent_prompt_batch_id: parentPromptBatchId,
    ...(images.length > 0 ? { images } : {}),
  });

  const batchId = (result as { batchId?: number } | undefined)?.batchId;
  if (kind === BATCH_KIND.INITIAL && batchId != null) {
    currentParentBatchId = batchId;
  }
  return { batchId };
}

/** Post a tool use event. Falls back to the local buffer on failure. */
async function mycoPostToolUse(
  directory: string,
  sessionId: string,
  toolName: string,
  toolInput: unknown,
  toolOutput: string,
): Promise<void> {
  await postEventWithBuffer(directory, sessionId, {
    type: "tool_use",
    session_id: sessionId,
    agent: "opencode",
    tool_name: toolName,
    tool_input: toolInput,
    output_preview: toolOutput,
  });
}

/**
 * Fetch the last assistant text from an opencode session for use as the
 * response summary on the next Stop.
 *
 * Starts with a small tail window (SESSION_IDLE_TAIL_LIMIT) because most
 * idle events have recent assistant text within a dozen messages. When that
 * window contains no assistant text — the turn ended with a tool call,
 * compaction just rewrote history, etc. — retries once with a wider window
 * rather than giving up and persisting a NULL response_summary.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function fetchResponseSummary(client: any, directory: string, sessionId: string): Promise<string> {
  const fetchAt = async (limit: number): Promise<string> => {
    try {
      const result = await client.session.messages({
        path: { id: sessionId },
        query: { directory, limit },
      });
      const messages = ((result as { data?: SessionMessage[] } | undefined)?.data ?? []) as SessionMessage[];
      return collectAssistantSummaryFromMessages(messages);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("[myco] Failed to fetch messages for summary:", err);
      return "";
    }
  };

  let summary = await fetchAt(SESSION_IDLE_TAIL_LIMIT);
  if (!summary) summary = await fetchAt(SESSION_IDLE_TAIL_LIMIT_RETRY);
  return summary;
}

/**
 * Post a stop event, synchronously buffering to disk before the async POST.
 *
 * Covers two failure modes:
 *   1. Daemon unreachable — the buffered entry is replayed at the daemon's
 *      next startup reconcile.
 *   2. Bun process exits before the POST settles — `server.instance.disposed`
 *      fires on TUI close, and the runtime can tear down before awaited
 *      fetches complete. The synchronous buffer write survives regardless.
 *
 * Duplicate work is harmless: the reconciler's setResponseSummary is
 * idempotent, so even if both the live POST and the buffered replay land,
 * the summary is written exactly once.
 */
async function mycoPostStop(
  directory: string,
  sessionId: string,
  lastAssistantMessage: string | undefined,
): Promise<void> {
  const payload = {
    type: "stop" as const,
    session_id: sessionId,
    agent: "opencode",
    last_assistant_message: lastAssistantMessage,
  };
  bufferEvent(directory, sessionId, payload);
  await postJson(directory, "/events/stop", payload);
}

/**
 * Fetch the session-start context for a new opencode session. Hits the daemon's
 * config-aware `POST /context` endpoint, which selects the digest tier the user
 * has configured (`config.cortex.digest.tier`, default 5000) and returns the
 * full session context (digest + branch + session ID lines).
 *
 * This is the same endpoint Claude Code's session-start hook uses, so opencode
 * sessions receive the same context the user has configured for every other agent.
 */
async function fetchMycoSessionContext(
  directory: string,
  sessionId: string,
): Promise<string | null> {
  const result = await postJson(directory, "/context", { session_id: sessionId });
  if (!result.ok) return null;
  const data = result.data as { text?: string } | undefined;
  const text = data?.text?.trim() ?? "";
  return text.length > 0 ? text : null;
}

/** Fetch a small resume recap for a resumed opencode session. */
async function fetchMycoResumeContext(
  directory: string,
  sessionId: string,
  parentSessionId: string,
): Promise<string | null> {
  const result = await postJson(directory, "/context/resume", {
    session_id: sessionId,
    parent_session_id: parentSessionId,
  });
  if (!result.ok) return null;
  const data = result.data as { text?: string } | undefined;
  const text = data?.text?.trim() ?? "";
  if (!text || text.length > RESUME_CONTEXT_MAX_CHARS) return null;
  return text;
}

/** Post a compaction telemetry event. */
async function mycoPostCompact(
  directory: string,
  sessionId: string,
  trigger: string | undefined,
): Promise<void> {
  await postEventWithBuffer(directory, sessionId, {
    type: "pre_compact",
    session_id: sessionId,
    agent: "opencode",
    ...(trigger ? { trigger } : {}),
  });
}

// ---------------------------------------------------------------------------
// Opencode session injection — push synthetic context into session history.
// ---------------------------------------------------------------------------

/**
 * Inject text into an opencode session as a synthetic (plugin-authored) user turn
 * without triggering an AI response. The text part carries:
 *   - `synthetic: true` so opencode's TUI hides it from the chat log
 *   - `metadata.myco: true` so our own `chat.message` handler can distinguish
 *     this re-entry from a real user message (see MYCO_METADATA_MARKER)
 * Errors are swallowed — injection is best-effort.
 */
async function injectSyntheticContext(
  client: unknown,
  sessionId: string,
  text: string,
): Promise<void> {
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = client as any;
    await c.session.prompt({
      path: { id: sessionId },
      body: {
        parts: [
          {
            type: "text",
            text,
            synthetic: true,
            metadata: { [MYCO_METADATA_MARKER]: true },
          },
        ],
        noReply: true,
      },
    });
  } catch (error) {
    // eslint-disable-next-line no-console
    console.error("[myco] Failed to inject synthetic context:", error);
  }
}

/** Flatten todo items into a newline-separated summary. */
function formatTodos(
  todos: Array<{ id?: string; content?: string; status?: string }>,
): string {
  if (!todos || todos.length === 0) return "";
  return todos
    .map((t) => `[${t.status || "pending"}] ${t.content || ""}`)
    .join("\n");
}

/** Truncate tool output for storage. */
function summarizeToolOutput(output: unknown): string {
  if (typeof output !== "string") return "";
  return output.length > TOOL_OUTPUT_PREVIEW_CHARS
    ? output.slice(0, TOOL_OUTPUT_PREVIEW_CHARS) + "..."
    : output;
}

// ---------------------------------------------------------------------------
// Plugin entry
// ---------------------------------------------------------------------------

/**
 * Opencode plugin entry. The function signature matches opencode's Plugin type
 * via duck typing — we deliberately do NOT import the Plugin type from
 * @opencode-ai/plugin so this file has zero external runtime dependencies.
 * That guarantee lets teammates who clone a project that uses Myco still run
 * opencode cleanly even when they don't have Myco installed locally.
 *
 * @param {{ client: any, directory: string, worktree: string }} ctx
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const MycoPlugin = async ({ client, directory, worktree }: { client: any; directory: string; worktree: string }) => {
  // Best-effort init log. Wrapped in try-catch so a future SDK shape change in
  // opencode (e.g. client.app.log moving) cannot prevent the plugin from
  // registering its handlers.
  try {
    await client.app.log({
      service: "myco",
      level: "info",
      message: "Myco plugin initialized",
      extra: { directory, worktree },
    });
  } catch {
    // Swallow — init log is diagnostic only.
  }

  return {
    /**
     * Generic event handler: session lifecycle, todos.
     */
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    event: async ({ event }: { event: any }) => {
      if (event.type === "session.created") {
        const info = event.properties?.info ?? {};
        const sessionId: string | undefined = info.id;
        if (!sessionId) return;

        activeOpencodeSessions.add(sessionId);

        const parentSessionId = info.parentID || undefined;

        // Diagnostic: log the full session.created payload when a parent is
        // present so we can tell sub-agent spawns apart from user-initiated
        // forks. Sub-agents pollute the session list as phantom user sessions;
        // filtering them needs a structural signal we don't have yet. Capture
        // live payloads from both paths (skill invocation vs. TUI fork) and
        // compare. Drop this block once the signal is known.
        if (parentSessionId) {
          try {
            await client.app.log({
              service: "myco",
              level: "info",
              message: "session.created with parentID",
              extra: {
                session_id: sessionId,
                parent_session_id: parentSessionId,
                info: JSON.stringify(info),
              },
            });
          } catch {
            // Diagnostic only — never block registration.
          }
        }
        const contextPromise = parentSessionId
          ? (resumeInjectedSessions.has(sessionId)
            ? Promise.resolve(null)
            : fetchMycoResumeContext(directory, sessionId, parentSessionId))
          : fetchMycoSessionContext(directory, sessionId);

        // Run registration and context fetch concurrently — they don't depend
        // on each other, and parallelizing saves one round-trip of latency.
        const [, sessionContext] = await Promise.all([
          mycoRegisterSession(directory, sessionId, parentSessionId),
          contextPromise,
        ]);

        if (sessionContext) {
          await injectSyntheticContext(client, sessionId, sessionContext);
          if (parentSessionId) resumeInjectedSessions.add(sessionId);
        }
        return;
      }

      if (event.type === "session.deleted") {
        const info = event.properties?.info ?? {};
        if (info.id) {
          activeOpencodeSessions.delete(info.id);
          resumeInjectedSessions.delete(info.id);
          await mycoUnregisterSession(directory, info.id);
        }
        return;
      }

      if (event.type === "server.instance.disposed") {
        // Opencode TUI is shutting down. Flush all tracked sessions so the
        // daemon can mark them completed immediately rather than waiting for
        // the stale-session maintenance sweep (1-hour threshold).
        //
        // Two things happen per session: (1) a Stop so the latest batch gets
        // a response_summary from whatever assistant text exists, and
        // (2) Unregister so the session row closes. Stop runs first — if it
        // lands, processStopEvent closes batches correctly; if it misses
        // (daemon down), the buffer fallback replays on next startup.
        //
        // The Bun process is about to exit, so we can't rely on awaited
        // fetches completing. Promise.all gives both calls their best shot
        // at landing before teardown.
        if (activeOpencodeSessions.size === 0) return;
        const toClose = Array.from(activeOpencodeSessions);
        activeOpencodeSessions.clear();
        for (const id of toClose) resumeInjectedSessions.delete(id);
        await Promise.all(
          toClose.flatMap((id) => [
            (async () => {
              const summary = await fetchResponseSummary(client, directory, id);
              await mycoPostStop(directory, id, summary || undefined);
            })(),
            mycoUnregisterSession(directory, id),
          ]),
        );
        return;
      }

      if (event.type === "session.idle") {
        const sessionId = event.properties?.sessionID;
        if (!sessionId) return;

        const responseSummary = await fetchResponseSummary(client, directory, sessionId);
        await mycoPostStop(directory, sessionId, responseSummary || undefined);
        currentParentBatchId = null;
        return;
      }

      if (event.type === "todo.updated") {
        const sessionId = event.properties?.sessionID;
        if (!sessionId) return;
        const todos = event.properties?.todos ?? [];
        await mycoPostToolUse(
          directory,
          sessionId,
          "TodoUpdate",
          { todos, count: todos.length },
          formatTodos(todos),
        );
      }
    },

    /**
     * Chat message: capture the user prompt + any image attachments.
     *
     * Per-turn spore injection is intentionally not done here. A previous iteration
     * injected spores via session.prompt({ noReply: true }) inside this handler, but
     * opencode re-fires chat.message for the synthetic turn and the first real user
     * message landed during the re-entrancy window. Agents can fetch context on
     * demand via the myco_cortex and myco_search MCP tools.
     *
     * Re-entrancy guard: we check for `metadata.myco === true` on any part to
     * detect our session-start digest injection coming back around. Opencode
     * itself sets `synthetic: true` for many internal purposes (plan-mode
     * prompts, build-switch transitions, subagent task summaries), so the
     * `synthetic` flag alone is NOT reliable as a re-entrancy signal — it
     * would silently drop any user prompt that opencode touched for one of
     * those internal reasons.
     */
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    "chat.message": async (input: any, output: any) => {
      const sessionId = input?.sessionID;
      if (!sessionId) return;

      // Part shapes we care about: text (for the prompt string) and file
      // (for image attachments encoded as data URLs — FilePart.url is
      // `data:<mime>;base64,<data>` per
      // packages/app/src/components/prompt-input/attachments.ts in opencode).
      const allParts = (output?.parts ?? []) as Array<{
        type?: string;
        text?: string;
        mime?: string;
        url?: string;
        synthetic?: boolean;
        metadata?: { [key: string]: unknown };
      }>;
      // Skip if any part carries the Myco metadata marker — that means
      // chat.message is firing for our own injectSyntheticContext call.
      if (allParts.some((p) => p.metadata?.[MYCO_METADATA_MARKER] === true)) return;

      // Prompt text = user's real text only. opencode emits `synthetic: true`
      // text parts for internal scaffolding when the message contains file
      // mentions, plan-mode switches, subagent tasks, and similar — see
      // packages/opencode/src/session/prompt.ts. Those parts include full
      // file contents, tool-call scaffolding, plan instructions, etc. Joining
      // them into prompt_text would bloat every captured user prompt with
      // system-level content that the user never typed.
      const textParts = allParts
        .filter((p) => p.type === "text" && p.text && p.synthetic !== true)
        .map((p) => p.text as string);
      const prompt = textParts.join("\n");
      if (!prompt) return;

      // Extract any image attachments from FilePart data URLs. Non-image file
      // parts (code snippets, documents) are ignored here — only images travel
      // to Myco as binary attachments via the existing attachment pipeline.
      const images: Array<{ data: string; mediaType: string }> = [];
      for (const part of allParts) {
        if (
          part.type !== "file" ||
          !part.mime?.startsWith("image/") ||
          typeof part.url !== "string" ||
          !part.url.startsWith("data:")
        ) {
          continue;
        }
        const commaIdx = part.url.indexOf(",");
        if (commaIdx <= 0) continue;
        const base64 = part.url.slice(commaIdx + 1);
        if (base64) images.push({ data: base64, mediaType: part.mime });
      }

      await mycoPostUserPrompt(directory, sessionId, prompt, images);
    },

    /**
     * Post-tool execution: ship tool usage to Myco.
     *
     * We forward `input.args` as `tool_input` — NOT `output.metadata` — because
     * `args` carries the tool invocation arguments (including `filePath` for
     * write/edit/patch tools), which Myco's plan-capture matcher needs to detect
     * writes to .opencode/plans/*.md.
     */
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    "tool.execute.after": async (input: any, output: any) => {
      const sessionId = input?.sessionID;
      if (!sessionId) return;

      const toolName = input?.tool ?? "unknown";
      const toolInput = normalizeToolInput(input?.args ?? output?.metadata ?? {});
      const toolOutput = summarizeToolOutput(output?.output);

      await mycoPostToolUse(directory, sessionId, toolName, toolInput, toolOutput);
    },

    /**
     * Compaction hook: fires BEFORE opencode generates a continuation summary
     * during session compaction. Pushing the session context into output.context
     * ensures Myco's project knowledge survives compaction rather than being
     * dropped. The fetched context respects the user's configured digest tier.
     *
     * See https://opencode.ai/docs/plugins/#compaction-hooks
     */
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    "experimental.session.compacting": async (input: any, output: any) => {
      const sessionId = input?.sessionID;
      if (!sessionId) return;

      await mycoPostCompact(directory, sessionId, typeof input?.trigger === "string" ? input.trigger : undefined);

      const sessionContext = await fetchMycoSessionContext(directory, sessionId);
      if (!sessionContext) return;

      if (Array.isArray(output?.context)) {
        output.context.push(COMPACTION_HEADING + sessionContext);
      }
    },
  };
};

export default MycoPlugin;
