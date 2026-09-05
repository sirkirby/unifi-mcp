#!/usr/bin/env node

/**
 * Trusted contract helpers for the community issue triage workflow.
 *
 * Contributor-controlled text is accepted only through the injected GitHub client or
 * files.  The CLI deliberately accepts paths, never raw issue content in argv or env.
 */

import {createHash, randomBytes as cryptoRandomBytes} from "node:crypto";
import {readFile, writeFile} from "node:fs/promises";
import {isIP} from "node:net";
import {pathToFileURL} from "node:url";

export const CONTRACT_VERSION = 3;
export const SNAPSHOT_STRATEGY = "bounded-title-lexical-v3";
export const MAX_TARGET_COMMENTS = 100;
export const MAX_TIMELINE_EVENTS = 100;
export const MAX_CANDIDATES = 5;
export const MAX_SCANNED_ISSUES = 1000;
export const MAX_TEXT_ITEM_BYTES = 256 * 1024;
export const MAX_RAW_EVIDENCE_BYTES = 1024 * 1024;

const RECEIPT_PATTERN = /^[a-f0-9]{32}$/;
const SHA_PATTERN = /^[a-f0-9]{40}$/i;
const DIGEST_PATTERN = /^[a-f0-9]{64}$/;
const POSITIVE_INTEGER_STRING_PATTERN = /^[1-9][0-9]*$/;
const VERDICTS = new Set(["RELATED", "NOT_RELATED", "UNCERTAIN"]);
const RUN_KINDS = new Set(["initial", "continuation"]);
const INITIAL_MARKER = "<!-- unifi-mcp-community-triage:v3:initial -->";
const CONTINUATION_MARKER = "<!-- unifi-mcp-community-triage:v3:continuation -->";
const ACTIONS_BOT = "github-actions[bot]";
const ALLOWED_LABELS = new Set([
  "bug", "enhancement", "documentation", "dependencies", "docker",
  "github-actions", "api", "network", "protect", "access", "needs-info",
]);
const SENSITIVE_SCOPES = new Set(["target", "comments", "candidate"]);
const SENSITIVE_CONFIGURATION_BLOB_KEYS = new Set([
  "openvpn_configuration",
  "wireguard_client_configuration_file",
  "wireguard_server_configuration_file",
]);
const SENSITIVE_PATTERNS = [
  /github_pat_[A-Za-z0-9_]{20,}/,
  /gh[pousr]_[A-Za-z0-9]{20,}/,
  /AKIA[0-9A-Z]{16}/,
  /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/,
  /(?:^|[^A-Za-z0-9_])["']?(?:[A-Za-z0-9]+[_-])*[A-Za-z0-9]*(?:api[_ -]?(?:key|token)|token|secret|password|passwd|passphrase|p(?:re)?[_ -]?shared(?:[_ -]?key)?|psk|(?:snmp[_ -]?)?community|private[_ -]?key)["']?\s*=\s*(?!["']?(?:(?:\*{2,})?redacted(?:\*{2,})?|\[redacted\]|<redacted>)["']?(?:[.!?](?=\s|$)|(?=$|[\r\n,;}\]])))(?:["'][^"'\r\n]+["']|[^\s,;}{]+)/i,
  /(?:^|[^A-Za-z0-9_])["']?(?:[A-Za-z0-9]+[_-])*[A-Za-z0-9]*(?:authorization|auth(?:[_ -]?key)?|api[_ -]?(?:key|token)|token|secret|password|passwd|passphrase|credential|cookie|session(?:[_ -]?id)?|p(?:re)?[_ -]?shared(?:[_ -]?key)?|psk|pin(?:[_ -]?code)?|(?:snmp[_ -]?)?community|private[_ -]?key|tls[_ -]?(?:auth|crypt)|rtsp[s]?[_ -]?(?:alias|url|streams?))["']?\s*=\s*(?!["']?(?:configured(?:\s+correctly)?|enabled|disabled|missing|unavailable|unknown|unset|none|null|(?:\*{2,})?redacted(?:\*{2,})?|\[redacted\]|<redacted>)["']?(?:[.!?](?=\s|$)|(?=$|[\r\n,;}\]])))(?:["'][^"'\r\n]{6,}["']|[^\s,;}{]{6,})/i,
  /(?:^|[^A-Za-z0-9_])["']?(?:[A-Za-z0-9]+[_-])*[A-Za-z0-9]*(?:api[_ -]?(?:key|token)|token|secret|password|passwd|passphrase|p(?:re)?[_ -]?shared(?:[_ -]?key)?|psk|(?:snmp[_ -]?)?community|private[_ -]?key)["']?\s*:\s*(?!["'](?:(?:\*{2,})?redacted(?:\*{2,})?|\[redacted\]|<redacted>|none|null)["'](?:\s*[,}]|[.!?]?(?=\s|$)))["'][^"'\r\n]+["']/i,
  /(?:^|[^A-Za-z0-9_])["']?(?:[A-Za-z0-9]+[_-])*[A-Za-z0-9]*(?:authorization|auth|credential|cookie|session(?:[_ -]?id)?|pin(?:[_ -]?code)?|tls[_ -]?auth|rtsp[s]?[_ -]?(?:alias|url|streams?))["']?\s*:\s*(?!["'](?:configured(?:\s+correctly)?|enabled|disabled|missing|unavailable|unknown|unset|none|null|(?:\*{2,})?redacted(?:\*{2,})?|\[redacted\]|<redacted>)["'](?:\s*[,}]|[.!?]?(?=\s|$)))["'][^"'\r\n]+["']/i,
  /(?:^|[^A-Za-z0-9_])["']?(?:[A-Za-z0-9]+[_-])*[A-Za-z0-9]*(?:authorization|auth(?:[_ -]?key)?|api[_ -]?(?:key|token)|token|secret|password|passwd|passphrase|credential|cookie|session(?:[_ -]?id)?|p(?:re)?[_ -]?shared(?:[_ -]?key)?|psk|pin(?:[_ -]?code)?|snmp[_ -]?community|private[_ -]?key|tls[_ -]?(?:auth|crypt)|rtsp[s]?[_ -]?(?:alias|url|streams?))["']?\s*:\s*(?!["']?(?:configured(?:\s+correctly)?|(?:\*{2,})?redacted(?:\*{2,})?|\[redacted\]|<redacted>|removed|hidden|masked|omitted|enabled|unset|missing|unknown|unavailable|disabled|none|null)["']?(?:[.!?](?=\s|$)|(?=$|[\r\n,;}\]])))(?:["'][^"'\r\n]+["']|[^\s,;}{]+)/i,
  /(?:^|[^A-Za-z0-9_])["']?(?:[A-Za-z0-9]+[_-])*[A-Za-z0-9]*(?:authorization|auth(?:[_ -]?key)?|api[_ -]?(?:key|token)|token|secret|password|passwd|passphrase|credential|cookie|session(?:[_ -]?id)?|p(?:re)?[_ -]?shared(?:[_ -]?key)?|psk|pin(?:[_ -]?code)?|snmp[_ -]?community|private[_ -]?key|tls[_ -]?(?:auth|crypt)|rtsp[s]?[_ -]?(?:alias|url|streams?))["']?\s+(?:is|was|are|were)\s+(?!["']?(?:(?:(?:currently|automatically|already|properly)\s+)?(?:configured(?:\s+correctly)?|(?:being\s+)?refreshed|incorrect|correct|valid|ok|fine|working|set|expired|invalid|available|present|missing|empty|removed|hidden|masked|omitted|unset|unavailable|disabled|none|null)|securely\s+stored(?:\s+in\s+(?:1password|a\s+password\s+manager|the\s+vault))?|(?:\*{2,})?redacted(?:\*{2,})?|\[redacted\]|<redacted>)["']?(?:[.!?](?=\s|$)|(?=$|[\r\n,;}\]])))(?:["'][^"'\r\n]+["']|[^\s,;}{]+)/i,
  /(?:^|[^A-Za-z0-9_])(?:pin(?:[_ -]?code)?)["']?\s*[:=]\s*["']?\d{4,12}["']?\b/i,
  /(?:^|\s)--pin(?:[-_]?code)?\s+["']?\d{4,12}["']?\b/i,
  /(?:^|[^A-Za-z0-9_])["']?(?:[A-Za-z0-9]+[_-])*[A-Za-z0-9]*(?:password|passwd|passphrase|p(?:re)?[_ -]?shared(?:[_ -]?key)?|psk|snmp[_ -]?community|private[_ -]?key)["']?\s*:\s*(?!["']?(?:(?:\*{2,})?redacted(?:\*{2,})?|\[redacted\]|<redacted>|none|null)["']?(?:[.!?](?=\s|$)|(?=$|[\r\n,;}\]])))[^\s,;}{]+/i,
  /(?:^|\s)--(?:api[-_]?(?:key|token)|token|secret|password|passwd|passphrase|p(?:re)?[-_]?shared(?:[-_]?key)?|psk|(?:snmp[-_]?)?community|private[-_]?key)\s+(?!["']?(?:(?:\*{2,})?redacted(?:\*{2,})?|\[redacted\]|<redacted>)["']?(?:\s|$))(?:["'][^"'\r\n]+["']|\S+)/i,
  /(?:^|[^A-Za-z0-9_])(?:x[_-]?iapp[_-]?key|private[_-]?preshared[_-]?keys|openvpn[_-]?configuration|wireguard[_-]?(?:client|server)[_-]?configuration[_-]?file)["']?[ \t]*[:=][ \t]*(?!["']?(?:(?:\*{2,})?redacted(?:\*{2,})?|\[redacted\]|<redacted>|none|null)["']?(?:\s|$|[,;}]))(?:["'][^"'\r\n]{6,}["']|[^\s,;}{]{6,})/i,
  /(?:^|\s)--(?:auth(?:[-_]?key)?|api[-_]?(?:key|token)|token|secret|password|passwd|passphrase|credential|cookie|session[-_]?id|p(?:re)?[-_]?shared(?:[-_]?key)?|psk|pin(?:[-_]?code)?|(?:snmp[-_]?)?community|private[-_]?key|tls[-_]?(?:auth|crypt))\s+(?!["']?(?:(?:\*{2,})?redacted(?:\*{2,})?|\[redacted\]|<redacted>)["']?(?:\s|$))(?:["'][^"'\r\n]{6,}["']|\S{6,})/i,
  /(?:^|[^A-Za-z0-9_])["']?(?:[A-Za-z0-9]+[_-])*[A-Za-z0-9]*(?:auth(?:[_ -]?key)?|api[_ -]?(?:key|token)|token|secret|password|passwd|passphrase|credential|cookie|session(?:[_ -]?id)?|p(?:re)?[_ -]?shared(?:[_ -]?key)?|psk|pin(?:[_ -]?code)?|(?:snmp[_ -]?)?community|private[_ -]?key|tls[_ -]?(?:auth|crypt))["']?\s*:\s*[>|][-+]?\s*\r?\n[ \t]+(?!["']?(?:(?:\*{2,})?redacted(?:\*{2,})?|\[redacted\]|<redacted>)["']?(?:\s|$))(?:["'][^"'\r\n]{6,}["']|\S{6,})/i,
  /(?:^|[^A-Za-z0-9_])["']?(?:[A-Za-z0-9]+[_-])*authorization["']?\s*[:=]\s*["']?(?:bearer|basic)\s+[A-Za-z0-9_./+=:-]{8,}/i,
  /\bbearer\s+[A-Za-z0-9._~+/=-]{20,}\b/i,
  /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/,
  /https?:\/\/[^\s/:@]+:[^\s/@]+@/i,
  /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/i,
  /\b(?:social security|ssn|date of birth|dob|home address|street address)\s*[:=]\s*\S+/i,
  /\b(?:phone|mobile|telephone|tel)(?:\s+number)?\s*(?::|=|\bis\b)\s*(?:\+?\d[\d ().-]{7,}\d|\(\d{2,4}\)[\d ().-]{5,}\d)\b/i,
  /\b\d{3}-\d{2}-\d{4}\b/,
  /\b(?:live|reside|address)\s+(?:at|is)\s+\d{1,6}\s+[A-Za-z][A-Za-z .'-]{1,60}\s+(?:street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr|court|ct)\b/i,
  /\b(?:10(?:\.\d{1,3}){3}|127(?:\.\d{1,3}){3}|169\.254(?:\.\d{1,3}){2}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b/,
  /\b(?:device|controller|console|gateway)\s+(?:serial(?:\s+number)?|uuid|device[ _-]?id)\s*[:=]\s*(?!["']?(?:unavailable|unknown|missing|none|null|unset|(?:\*{2,})?redacted(?:\*{2,})?|\[redacted\]|<redacted>)["']?(?:[.!?](?=\s|$)|(?=$|[\r\n,;}\]])))[A-Za-z0-9][A-Za-z0-9._:-]{5,}\b/i,
  /\b(?:f[cd][0-9a-f]{2}|fe[89ab][0-9a-f]):[0-9a-f:]+\b/i,
  /\b(?:[0-9A-F]{2}[:-]){5}[0-9A-F]{2}\b/i,
  /\b(?:[0-9A-F]{4}\.){2}[0-9A-F]{4}\b/i,
  /\b[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.(?:local|lan|internal|home|private)(?::\d{1,5})?\b/i,
  /\b(?:zero[\p{Pd} ]?day|0[\p{Pd} ]?day|undisclosed vulnerab\p{L}*|security vulnerab\p{L}*|remote[\p{Pd} ]code execution|privilege[\p{Pd} ]escalation|sql[\p{Pd} ]injection|sqli|command[\p{Pd} ]injection|(?:path|directory)[\p{Pd} ]traversal|server[\p{Pd} ]side request forgery|ssrf|cross[\p{Pd} ]site scripting|xss|csrf|rce|idor|xxe|access[\p{Pd} ]control bypass|account takeover|unauthenticated(?:\s+(?:access|user|users|request|requests))?|arbitrary (?:file|code|command) (?:read|write|execution)|expos(?:e|es|ed|ing) credentials?|credential exposure)\b/iu,
  /\b(?:auth(?:entication|orization)?)[^\r\n]{0,40}\bbypass\p{L}*\b/iu,
  /\bbypass\p{L}*\b[^\r\n]{0,40}\b(?:auth(?:entication|orization)?)\b/iu,
];
const SENSITIVE_MULTILINE_LABEL_PATTERN =
  /^(?:(.*?)[ _-]+)?(?:authorization|auth(?:[ _-]?key)?|api[ _-]?(?:key|tokens?)|tokens?|secrets?|passwords?|passwd|passphrase|credentials?|cookie|session(?:[ _-]?id)?|p(?:re)?[ _-]?shared(?:[ _-]?key)?|psk|(?:access[ \t]+)?pin(?:[ _-]?code)?|snmp[ _-]?community|private[ _-]?key|tls[ _-]?(?:auth|crypt)|rtsp[s]?[ _-]?(?:alias|url|streams?))(?:[ _-]+(.*))?$/iu;
const UNRESOLVED_HTML_NAMED_REFERENCE_PATTERN = /&[A-Za-z][A-Za-z0-9]+;/u;
const SENSITIVE_LABEL_PROSE_WORD_PATTERN =
  /^(?:and|are|as|at|by|for|from|in|is|of|on|or|that|to|using|was|were|when|where|which|while|with)$/iu;
const SENSITIVE_LABEL_RELATIONAL_PREFIX_PATTERN =
  /^(?:current[ _-]+)?value(?:[ _-]+(?:for|of)(?:[ _-]+[\p{L}\p{N}][\p{L}\p{N}.'-]*){0,2})?$/iu;
const SENSITIVE_LABEL_SUFFIX_PATTERN =
  /^(?:value|is|was|are|were|(?:for|of|in|from|on|at|to)[ _-]+[\p{L}\p{N}][\p{L}\p{N}.'-]*(?:[ _-]+[\p{L}\p{N}][\p{L}\p{N}.'-]*){0,2}|(?:value[ _-]+)?used[ _-]+(?:by|with|for|in)[ _-]+[\p{L}\p{N}][\p{L}\p{N}.'-]*(?:[ _-]+[\p{L}\p{N}][\p{L}\p{N}.'-]*){0,2})$/iu;
const MAX_MARKDOWN_LABEL_NORMALIZATION_PASSES = 32;
const MAX_MARKDOWN_LABEL_LENGTH = 1_024;
const UNSTABLE_MARKDOWN_LABEL_SENTINEL = "&UnstableMarkdownLabel;";
const SAFE_INLINE_LABEL_TAGS = new Set(["b", "code", "del", "em", "i", "kbd", "s", "span", "strong", "sub", "sup", "u"]);
const BENIGN_SESSION_PROSE_LABEL_PATTERN =
  /^(?:debugging|observed|testing)[ _-]+authenticated[ _-]+session$/iu;
const BENIGN_SESSION_PROSE_VALUE_PATTERN = /^(?:the[ _-]+)?endpoint[ _-]+returns[ _-]+\d{3}[.!]?$/iu;
const BENIGN_MULTILINE_SENSITIVE_VALUE_PATTERN =
  /^["']?(?:configured(?:\s+correctly)?|enabled|disabled|missing|unavailable|unknown|unset|none|null|removed|hidden|masked|omitted|(?:\*{2,})?redacted(?:\*{2,})?|\[redacted\]|<redacted>)["']?[.!]?$/iu;
const SENSITIVE_LABEL_CANDIDATE_PATTERN =
  /(?:^|[^A-Za-z0-9])(?:authorization|auth(?:[ _-]?key)?|api[ _-]?(?:key|tokens?)|tokens?|secrets?|passwords?|passwd|passphrase|credentials?|cookie|session(?:[ _-]?id)?|p(?:re)?[ _-]?shared(?:[ _-]?key)?|psk|pin(?:[ _-]?code)?|community|private[ _-]?key|tls[ _-]?(?:auth|crypt)|rtsp[s]?[ _-]?(?:alias|url|streams?))(?=$|[^A-Za-z0-9])/iu;
const MARKDOWN_TABLE_SEPARATOR_PATTERN =
  /^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*(?:\|[ \t]*:?-{3,}:?[ \t]*)*\|?[ \t]*$/u;
const SAFE_STRUCTURAL_LABEL_PATTERN =
  /^(?:actual behavior|additional context|environment|expected behavior|installation(?: method)?|logs?|steps(?: to reproduce)?|transport|version)$/iu;
const BENIGN_SECURITY_CONTEXT_PATTERNS = [
  /^\s*unauthenticated (?:users|requests) (?:correctly )?(?:receive|return) 401(?: unauthorized)?(?: as expected)?[.!]?\s*$/iu,
  /^\s*(?:the )?api denies unauthenticated requests[.!]?\s*$/iu,
  /^\s*(?:the )?(?:xml )?parser rejects xxe payloads[.!]?\s*$/iu,
  /^\s*xxe payloads are rejected by (?:the )?(?:xml )?parser[.!]?\s*$/iu,
  /^\s*account takeover protection (?:is enabled|prevented the attack)[.!]?\s*$/iu,
  /^\s*arbitrary file read is not possible[.!]?\s*$/iu,
];
const STOP_WORDS = new Set([
  "about", "after", "again", "against", "being", "cannot", "could",
  "does", "fails", "from", "have", "into", "issue", "plugin", "server",
  "should", "that", "their", "this", "through", "unifi", "when", "with",
]);
const MISSING_INFORMATION_FIELDS = new Set([
  "package_version",
  "transport",
  "controller_version",
  "sanitized_error",
  "reproduction_steps",
  "expected_actual",
  "live_controller_evidence",
]);
const MISSING_INFORMATION_TEXT = new Map([
  ["package_version", "The exact unifi-mcp package version or commit."],
  ["transport", "The transport in use: stdio, SSE, or streamable HTTP."],
  ["controller_version", "The UniFi application family and version."],
  ["sanitized_error", "The complete sanitized error message or response status."],
  ["reproduction_steps", "Minimal steps that reproduce the behavior."],
  ["expected_actual", "The expected behavior and the actual behavior observed."],
  ["live_controller_evidence", "Sanitized live-controller evidence showing the result."],
]);
const REPOSITORY_EVIDENCE_PATHS = [
  /^(?:README|CONTRIBUTING|SECURITY)\.md$/,
  /^docs\/[A-Za-z0-9][A-Za-z0-9._-]*(?:\/[A-Za-z0-9][A-Za-z0-9._-]*)*\.md$/,
  /^(?:apps|packages)\/[A-Za-z0-9][A-Za-z0-9._-]*\/src\/[A-Za-z0-9_][A-Za-z0-9_-]*(?:\/[A-Za-z0-9_][A-Za-z0-9_-]*)*\.py$/,
];
const COMMENT_FOOTER =
  "This is an automated first-pass triage; a maintainer will make final decisions.";

function fail(message) {
  throw new Error(message);
}

function exactKeys(value, expected) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const actual = Object.keys(value);
  return actual.length === expected.length && actual.every((key) => expected.includes(key));
}

function assertSafePositiveInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) fail(`${name} must be a positive safe integer`);
  return value;
}

function validateRelevantTimelineIdentifier(value) {
  if (typeof value !== "string" && typeof value !== "number") {
    fail("relevant timeline event id must be a positive decimal identifier");
  }
  if (typeof value === "number" && (!Number.isInteger(value) || value < 1)) {
    fail("relevant timeline event id must be a positive decimal identifier");
  }
  if (!POSITIVE_INTEGER_STRING_PATTERN.test(String(value))) {
    fail("relevant timeline event id must be a positive decimal identifier");
  }
}

function normalizeRunId(value) {
  const normalized = String(value);
  if (!POSITIVE_INTEGER_STRING_PATTERN.test(normalized)) fail("run_id must be a positive integer string");
  return normalized;
}

function normalizeRepository(owner, repo) {
  if (!/^[A-Za-z0-9_.-]+$/.test(owner || "") || !/^[A-Za-z0-9_.-]+$/.test(repo || "")) {
    fail("repository owner and name must use the canonical GitHub identifier grammar");
  }
  return `${owner}/${repo}`;
}

function assertWorkflowSha(value) {
  if (typeof value !== "string" || !SHA_PATTERN.test(value)) fail("workflow_sha must be a 40-character commit SHA");
  return value.toLowerCase();
}

function assertReceipt(value, name) {
  if (typeof value !== "string" || !RECEIPT_PATTERN.test(value)) fail(`${name} must be a 128-bit lowercase hex receipt`);
  return value;
}

function assertDigest(value, name) {
  if (typeof value !== "string" || !DIGEST_PATTERN.test(value)) fail(`${name} must be a lowercase SHA-256 digest`);
  return value;
}

function normalizeActionDigest(value, name) {
  if (typeof value !== "string") fail(`${name} must be a SHA-256 artifact digest`);
  const normalized = value.startsWith("sha256:") ? value.slice("sha256:".length) : value;
  return assertDigest(normalized, name);
}

function normalizeNullableText(value) {
  if (value === null || value === undefined) return "";
  if (typeof value !== "string") fail("GitHub returned a non-string text field");
  return value;
}

function textBytes(value, name) {
  const size = Buffer.byteLength(value, "utf8");
  if (size > MAX_TEXT_ITEM_BYTES) {
    fail(`${name} exceeds the ${MAX_TEXT_ITEM_BYTES}-byte trusted evidence limit`);
  }
  return size;
}

function isDocumentationEndpoint(value) {
  const normalized = value.toLowerCase();
  const documentationDomains = ["example.com", "example.org", "example.net"];
  return (
    documentationDomains.some((domain) => normalized === domain || normalized.endsWith(`.${domain}`)) ||
    normalized.startsWith("2001:db8:") ||
    /^(?:192\.0\.2|198\.51\.100|203\.0\.113)\./.test(normalized)
  );
}

function normalizeStructuredKey(value) {
  return value
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean)
    .join("_");
}

function isSanitizedBlobValue(value) {
  if (value === null || value === undefined) return true;
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    return ["", "null", "none", "redacted", "***redacted***", "[redacted]", "<redacted>"].includes(normalized);
  }
  if (Array.isArray(value)) return value.every((item) => isSanitizedBlobValue(item));
  if (typeof value === "object") return Object.values(value).every((item) => isSanitizedBlobValue(item));
  return false;
}

function isSanitizedYamlScalar(value) {
  const normalized = value.trim();
  if (
    (normalized.startsWith('"') && normalized.endsWith('"')) ||
    (normalized.startsWith("'") && normalized.endsWith("'"))
  ) {
    return isSanitizedBlobValue(normalized.slice(1, -1));
  }
  return isSanitizedBlobValue(normalized);
}

function isSanitizedYamlMapping(value) {
  const normalized = value.trim();
  if (normalized === "{}" || normalized === "[]") return true;
  if (!normalized.startsWith("{") || !normalized.endsWith("}")) return false;
  const entries = normalized.slice(1, -1).split(",");
  return entries.every((entry) => {
    const separator = entry.indexOf(":");
    return separator >= 0 && isSanitizedYamlScalar(entry.slice(separator + 1));
  });
}

function isSanitizedYamlLines(lines) {
  const meaningful = lines.map((line) => line.trim()).filter(Boolean);
  if (meaningful.length === 0) return true;
  return meaningful.every((line) => {
    const separator = line.indexOf(":");
    if (separator < 0) return isSanitizedYamlScalar(line);
    return isSanitizedYamlScalar(line.slice(separator + 1));
  });
}

function structuredObjectContainsSensitiveBlob(value) {
  if (!value || typeof value !== "object") return false;
  if (Array.isArray(value)) return value.some((item) => structuredObjectContainsSensitiveBlob(item));
  return Object.entries(value).some(([key, item]) => {
    if (SENSITIVE_CONFIGURATION_BLOB_KEYS.has(normalizeStructuredKey(key))) {
      return !isSanitizedBlobValue(item);
    }
    return structuredObjectContainsSensitiveBlob(item);
  });
}

function containsSensitiveConfigurationBlob(value) {
  try {
    if (structuredObjectContainsSensitiveBlob(JSON.parse(value))) return true;
  } catch {
    // Continue with the bounded YAML subset below.
  }

  const lines = value.split(/\r?\n/);
  for (let index = 0; index < lines.length; index += 1) {
    const match = lines[index].match(
      /^([ \t]*)["']?(openvpn[_-]?configuration|wireguard[_-]?(?:client|server)[_-]?configuration[_-]?file)["']?[ \t]*:[ \t]*(.*)$/i,
    );
    if (!match) continue;
    const baseIndent = match[1].length;
    const inlineValue = match[3].trim();
    if (/^[>|][-+]?$/.test(inlineValue) || !inlineValue) {
      const blockLines = [];
      for (let next = index + 1; next < lines.length; next += 1) {
        const nextLine = lines[next];
        if (!nextLine.trim()) {
          blockLines.push("");
          continue;
        }
        const indentation = nextLine.match(/^[ \t]*/)[0].length;
        if (indentation <= baseIndent) break;
        blockLines.push(nextLine.slice(baseIndent + 1));
      }
      if (!isSanitizedYamlLines(blockLines)) return true;
      continue;
    }
    let structuredValue = inlineValue;
    try {
      structuredValue = JSON.parse(inlineValue);
    } catch {
      if (isSanitizedYamlMapping(inlineValue)) continue;
    }
    if (!isSanitizedBlobValue(structuredValue)) return true;
  }
  return false;
}

function containsControllerAddress(value) {
  const assignmentPattern = /(?:\b(?:controller|console|gateway)(?:\s+(?:public\s+)?(?:ip(?:v[46])?(?:\s+address)?|address|url|host(?:name)?))?|(?:^|[^A-Z0-9_])UNIFI(?:_[A-Z0-9]+)?_HOST)\s*(?::|=|\bis(?:\s+at)?\b|\bat\b)\s*(?:"([^"]+)"|'([^']+)'|(\[[^\]]+\](?::\d{1,5})?|[^\s,;}]+))/giu;
  for (const match of value.matchAll(assignmentPattern)) {
    const raw = (match[1] || match[2] || match[3]).replace(/[.!?]+$/, "");
    if (/^https?:\/\//i.test(raw)) {
      try {
        const hostname = new URL(raw).hostname.replace(/^\[|\]$/g, "");
        if (!isDocumentationEndpoint(hostname)) return true;
      } catch {
        const authority = raw.replace(/^https?:\/\//i, "").split(/[/?#]/, 1)[0];
        const bracketed = authority.match(/^\[([^\]]+)\](?::[^:]*)?$/);
        const hostWithMalformedPort = authority.match(/^([^:]+):[^:]*$/);
        const fallbackHost = bracketed ? bracketed[1] : hostWithMalformedPort ? hostWithMalformedPort[1] : authority;
        if (
          (isIP(fallbackHost) ||
            /^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}$/.test(fallbackHost)) &&
          !isDocumentationEndpoint(fallbackHost)
        ) return true;
      }
      continue;
    }
    const unwrapped = raw.replace(/^\[([^\]]+)\](?::\d{1,5})?$/, "$1");
    const authority = unwrapped.split(/[/?#]/, 1)[0];
    const ipv4WithPort = authority.match(/^((?:\d{1,3}\.){3}\d{1,3}):\d{1,5}$/);
    const endpointHost = ipv4WithPort ? ipv4WithPort[1] : authority;
    if (isIP(endpointHost)) {
      if (!isDocumentationEndpoint(endpointHost)) return true;
      continue;
    }
    const hostname = endpointHost.replace(/:\d{1,5}$/, "");
    if (/^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}$/.test(hostname)) {
      if (!isDocumentationEndpoint(hostname)) return true;
    }
  }
  return false;
}

function markdownTableCells(line) {
  const trimmed = line.trim().replace(/^(?:>[ \t]*)+/u, "");
  const cells = [];
  let cell = "";
  let backslashRun = 0;
  let sawDelimiter = false;
  for (const character of trimmed) {
    if (character === "|" && backslashRun % 2 === 0) {
      cells.push(cell.trim());
      cell = "";
      backslashRun = 0;
      sawDelimiter = true;
      continue;
    }
    cell += character;
    backslashRun = character === "\\" ? backslashRun + 1 : 0;
  }
  if (!sawDelimiter) return null;
  cells.push(cell.trim());
  if (cells[0] === "") cells.shift();
  if (cells.at(-1) === "") cells.pop();
  return cells;
}

function isMarkdownTableSeparator(line) {
  return MARKDOWN_TABLE_SEPARATOR_PATTERN.test(line.trim().replace(/^(?:>[ \t]*)+/u, ""));
}

function stripMarkdownWrappers(value) {
  return value.replace(/^[`*_~]+|[`*_~]+$/gu, "").trim();
}

function decodeHtmlCharacterReferences(value) {
  const named = new Map([
    ["af", "\u2061"],
    ["amp", "&"],
    ["applyfunction", "\u2061"],
    ["apos", "'"],
    ["colon", ":"],
    ["equals", "="],
    ["gt", ">"],
    ["hyphen", "-"],
    ["ic", "\u2063"],
    ["invisiblecomma", "\u2063"],
    ["invisibletimes", "\u2062"],
    ["it", "\u2062"],
    ["lowbar", "_"],
    ["lt", "<"],
    ["lrm", "\u200e"],
    ["negativemediumspace", "\u200b"],
    ["negativethickspace", "\u200b"],
    ["negativethinspace", "\u200b"],
    ["negativeverythinspace", "\u200b"],
    ["nbsp", " "],
    ["nobreak", "\u2060"],
    ["quot", '"'],
    ["rlm", "\u200f"],
    ["shy", "\u00ad"],
    ["zerowidthspace", "\u200b"],
    ["zwnj", "\u200c"],
    ["zwj", "\u200d"],
  ]);
  const namedPattern = new RegExp(
    `&(${[...named.keys()].sort((left, right) => right.length - left.length).join("|")});?`,
    "giu",
  );
  return value
    .replace(/&#(?:x(0*[0-9a-f]{1,6})(?![0-9a-f])|(0*[0-9]{1,7})(?![0-9]));?/giu, (match, hex, decimal) => {
      const codePoint = Number.parseInt(hex || decimal, hex ? 16 : 10);
      return Number.isSafeInteger(codePoint) && codePoint > 0 && codePoint <= 0x10ffff &&
        !(codePoint >= 0xd800 && codePoint <= 0xdfff)
        ? String.fromCodePoint(codePoint)
        : match;
    })
    .replace(namedPattern, (match, name) => named.get(name.toLocaleLowerCase("en-US")) || match);
}

function stripInlineHtmlMarkup(value, discardedValues = null) {
  let result = "";
  for (let index = 0; index < value.length; index += 1) {
    if (value.startsWith("<!--", index)) {
      const commentEnd = value.indexOf("-->", index + 4);
      if (commentEnd !== -1) {
        discardedValues?.push(value.slice(index + 4, commentEnd));
        index = commentEnd + 2;
        continue;
      }
    }
    if (value.startsWith("<?", index)) {
      const instructionEnd = value.indexOf("?>", index + 2);
      if (instructionEnd !== -1) {
        discardedValues?.push(value.slice(index + 2, instructionEnd));
        index = instructionEnd + 1;
        continue;
      }
      result += value.slice(index);
      break;
    }
    if (value.startsWith("<![CDATA[", index)) {
      const cdataEnd = value.indexOf("]]>", index + 9);
      if (cdataEnd !== -1) {
        discardedValues?.push(value.slice(index + 9, cdataEnd));
        index = cdataEnd + 2;
        continue;
      }
      result += value.slice(index);
      break;
    }
    if (value[index] === "<" && value[index + 1] === "!" && /[A-Z]/u.test(value[index + 2] || "")) {
      const declarationEnd = value.indexOf(">", index + 2);
      if (declarationEnd !== -1) {
        discardedValues?.push(value.slice(index + 2, declarationEnd));
        index = declarationEnd;
        continue;
      }
      result += value.slice(index);
      break;
    }
    const tagNameStart = value[index + 1] === "/" ? index + 2 : index + 1;
    if (value[index] === "<" && /[A-Za-z]/u.test(value[tagNameStart] || "")) {
      let quote = null;
      let tagEnd = -1;
      for (let candidate = index + 1; candidate < value.length; candidate += 1) {
        const character = value[candidate];
        if (quote !== null) {
          if (character === quote) quote = null;
        } else if (character === '"' || character === "'") {
          quote = character;
        } else if (character === ">") {
          tagEnd = candidate;
          break;
        }
      }
      if (tagEnd !== -1) {
        const tag = value.slice(index + 1, tagEnd);
        const tagName = tag.match(/^\/?([A-Za-z][^\s/>]*)/u)?.[1] || "";
        const attributes = tag.replace(/^\/?[A-Za-z][^\s/>]*/u, "").replace(/\/?\s*$/u, "").trim();
        if (!SAFE_INLINE_LABEL_TAGS.has(tagName.toLocaleLowerCase("en-US"))) discardedValues?.push(tagName);
        if (attributes !== "") discardedValues?.push(attributes);
        index = tagEnd;
        continue;
      }
      result += value.slice(index);
      break;
    }
    result += value[index];
  }
  return result;
}

function hasSensitiveDiscardedLabelMarkup(value) {
  const discardedValues = [];
  stripInlineHtmlMarkup(value, discardedValues);
  if (discardedValues.some((discarded) => {
    const normalized = stripMarkdownWrappers(
      decodeHtmlCharacterReferences(discarded)
        .normalize("NFKC")
        .replace(/\p{Default_Ignorable_Code_Point}/gu, ""),
    );
    return normalized !== "" && !BENIGN_MULTILINE_SENSITIVE_VALUE_PATTERN.test(normalized);
  })) return true;

  const discardedDestinations = [];
  stripMarkdownInlineLinkDestinations(value, discardedDestinations);
  if (discardedDestinations.length > 0) return true;
  const rendered = value.replace(/[`*_~]+/gu, "");
  const sensitiveCandidate =
    SENSITIVE_LABEL_CANDIDATE_PATTERN.test(rendered) || UNRESOLVED_HTML_NAMED_REFERENCE_PATTERN.test(rendered);
  return sensitiveCandidate && hasClosedMarkdownLabel(rendered);
}

function hasClosedMarkdownLabel(value) {
  let open = false;
  let escaped = false;
  for (const character of value) {
    if (escaped) {
      escaped = false;
      continue;
    }
    if (character === "\\") {
      escaped = true;
    } else if (character === "[") {
      open = true;
    } else if (character === "]" && open) {
      return true;
    }
  }
  return false;
}

function recoverMalformedSensitiveField(line) {
  const rendered = line.replace(/[`*_~]+/gu, "");
  for (let index = 0; index < rendered.length; index += 1) {
    if (rendered[index] !== ":" && rendered[index] !== "=") continue;
    const prefix = rendered.slice(0, index);
    const candidate = prefix.match(SENSITIVE_LABEL_CANDIDATE_PATTERN);
    if (!candidate || candidate.index === undefined) continue;
    const candidateStart = candidate.index + (/^[^A-Za-z0-9]/u.test(candidate[0]) ? 1 : 0);
    return {
      label: UNSTABLE_MARKDOWN_LABEL_SENTINEL,
      value: rendered.slice(index + 1).trim(),
      discardedPrefix: prefix.slice(0, candidateStart).trim(),
    };
  }
  return null;
}

function hasUnsafeMalformedSensitivePrefix(prefix) {
  if (prefix === "") return false;
  if (prefix === "<!--" || prefix === "<?xml" || prefix === "<![CDATA[" || prefix === "<!DOCTYPE") return false;
  const tag = prefix.match(/^<\/?([A-Za-z][A-Za-z0-9:._-]*)$/u);
  return !tag || !SAFE_INLINE_LABEL_TAGS.has(tag[1].toLocaleLowerCase("en-US"));
}

function exposeSensitiveMalformedFields(value) {
  return value
    .split(/\r?\n|\r/u)
    .map((line) => {
      const recovered = recoverMalformedSensitiveField(line);
      if (!recovered) return line;
      const recoveredValue = hasUnsafeMalformedSensitivePrefix(recovered.discardedPrefix)
        ? UNSTABLE_MARKDOWN_LABEL_SENTINEL
        : recovered.value;
      return `${recovered.label}: ${recoveredValue}`;
    })
    .join("\n");
}

function collapseRawHtmlMarkupNewlines(value) {
  let result = "";
  let mode = null;
  let terminator = null;
  let quote = null;
  let markupStart = -1;
  for (let index = 0; index < value.length; index += 1) {
    const character = value[index];
    if (mode === null && character === "<") {
      if (value.startsWith("<!--", index)) {
        mode = "terminated";
        terminator = "-->";
        markupStart = index;
      } else if (value.startsWith("<?", index)) {
        mode = "terminated";
        terminator = "?>";
        markupStart = index;
      } else if (value.startsWith("<![CDATA[", index)) {
        mode = "terminated";
        terminator = "]]>";
        markupStart = index;
      } else if (value[index + 1] === "!" && /[A-Z]/u.test(value[index + 2] || "")) {
        mode = "terminated";
        terminator = ">";
        markupStart = index;
      } else {
        const nameIndex = value[index + 1] === "/" ? index + 2 : index + 1;
        if (/[A-Za-z]/u.test(value[nameIndex] || "")) {
          mode = "tag";
          markupStart = index;
        }
      }
    }

    if (mode !== null && character === "\r" && value[index + 1] === "\n") {
      result += " ";
      index += 1;
      continue;
    }
    if (mode !== null && character === "\n") {
      result += " ";
      continue;
    }

    result += character;
    if (mode === "tag") {
      if (quote !== null) {
        if (character === quote) quote = null;
      } else if (character === '"' || character === "'") {
        quote = character;
      } else if (character === ">") {
        mode = null;
        markupStart = -1;
      }
    } else if (mode === "terminated" && value.startsWith(terminator, index)) {
      result += terminator.slice(1);
      index += terminator.length - 1;
      mode = null;
      terminator = null;
      markupStart = -1;
    }
  }
  if (mode === null || markupStart === -1) return {value: result, sensitiveUnterminated: false};
  const unterminated = value.slice(markupStart);
  const newlineIndex = unterminated.search(/[\r\n]/u);
  if (newlineIndex === -1) return {value: result, sensitiveUnterminated: false};
  const exposed = exposeSensitiveMalformedFields(unterminated);
  return {
    value: result,
    sensitiveUnterminated: containsSensitiveTable(exposed) || containsSensitiveMultilineValue(exposed),
  };
}

function stripMarkdownInlineLinkDestinations(value, discardedDestinations) {
  let result = "";
  for (let index = 0; index < value.length; ) {
    const labelStart = value[index] === "!" && value[index + 1] === "[" ? index + 1 : index;
    if (value[labelStart] !== "[") {
      result += value[index];
      index += 1;
      continue;
    }

    let labelEnd = -1;
    let escaped = false;
    for (let cursor = labelStart + 1; cursor < value.length; cursor += 1) {
      const character = value[cursor];
      if (character === "\r" || character === "\n") break;
      if (escaped) {
        escaped = false;
      } else if (character === "\\") {
        escaped = true;
      } else if (character === "]") {
        labelEnd = cursor;
        break;
      }
    }
    if (labelEnd === -1) {
      result += value.slice(index);
      break;
    }
    if (value[labelEnd + 1] !== "(") {
      result += value.slice(index, labelEnd + 1);
      index = labelEnd + 1;
      continue;
    }

    let destinationEnd = -1;
    let depth = 0;
    let titleQuote = null;
    escaped = false;
    for (let cursor = labelEnd + 1; cursor < value.length; cursor += 1) {
      const character = value[cursor];
      if (character === "\r" || character === "\n") break;
      if (escaped) {
        escaped = false;
      } else if (character === "\\") {
        escaped = true;
      } else if (titleQuote !== null) {
        if (character === titleQuote) titleQuote = null;
      } else if (
        depth === 1 &&
        (character === '"' || character === "'") &&
        /[ \t]/u.test(value[cursor - 1] || "")
      ) {
        titleQuote = character;
      } else if (character === "(") {
        depth += 1;
      } else if (character === ")") {
        depth -= 1;
        if (depth === 0) {
          destinationEnd = cursor;
          break;
        }
      }
    }
    if (destinationEnd === -1) {
      const visibleLabel = value.slice(labelStart + 1, labelEnd);
      const remainder = value.slice(labelEnd + 2).trim();
      const candidateLabel = visibleLabel.replace(/[`*_~]+/gu, "");
      if (
        remainder !== "" &&
        !BENIGN_MULTILINE_SENSITIVE_VALUE_PATTERN.test(stripMarkdownWrappers(remainder)) &&
        SENSITIVE_LABEL_CANDIDATE_PATTERN.test(stripMarkdownWrappers(candidateLabel))
      ) {
        return UNSTABLE_MARKDOWN_LABEL_SENTINEL;
      }
      result += visibleLabel;
      break;
    }

    discardedDestinations?.push(value.slice(labelEnd + 2, destinationEnd));
    result += value.slice(labelStart + 1, labelEnd);
    index = destinationEnd + 1;
  }
  return result;
}

function normalizeMarkdownTableLabel(cell) {
  if (cell.length > MAX_MARKDOWN_LABEL_LENGTH) return UNSTABLE_MARKDOWN_LABEL_SENTINEL;
  let label = stripInlineHtmlMarkup(decodeHtmlCharacterReferences(cell)).trim();
  for (let pass = 0; pass < MAX_MARKDOWN_LABEL_NORMALIZATION_PASSES; pass += 1) {
    const normalized = stripMarkdownInlineLinkDestinations(label)
      .replace(/!?\[([^\]\r\n]+)\]\[[^\]\r\n]*\]/gu, "$1")
      .replace(/!?\[([^\]\r\n]+)\]/gu, "$1")
      .replace(/(\*{1,3}|_{1,3}|~{2}|`+)(.+?)\1/gu, "$2");
    if (normalized === label) return stripMarkdownWrappers(label);
    label = normalized;
  }
  return UNSTABLE_MARKDOWN_LABEL_SENTINEL;
}

function isSensitiveMultilineLabel(label) {
  const normalizedLabel = normalizeMarkdownTableLabel(label);
  // A complete HTML5 named-reference table would add thousands of security-critical
  // aliases. Fail closed when a candidate label still contains one we did not decode.
  if (UNRESOLVED_HTML_NAMED_REFERENCE_PATTERN.test(normalizedLabel)) return true;
  const match = normalizedLabel.match(SENSITIVE_MULTILINE_LABEL_PATTERN);
  if (!match) return false;
  const prefix = (match[1] || "").trim();
  const suffix = (match[2] || "").trim();
  const isShortLabelFragment = (fragment, prosePattern) => {
    if (fragment === "") return true;
    const words = fragment.split(/[ _-]+/u).filter(Boolean);
    return (
      words.length <= 4 &&
      words.every(
        (word) => /^[\p{L}\p{N}][\p{L}\p{N}.'-]*$/u.test(word) && !prosePattern.test(word),
      )
    );
  };
  const validPrefix =
    isShortLabelFragment(prefix, SENSITIVE_LABEL_PROSE_WORD_PATTERN) ||
    SENSITIVE_LABEL_RELATIONAL_PREFIX_PATTERN.test(prefix);
  if (!validPrefix) return false;
  return suffix === "" || SENSITIVE_LABEL_SUFFIX_PATTERN.test(suffix);
}

function markdownReferenceDefinitionLabels(lines) {
  const labels = new Set();
  for (const line of lines) {
    const normalized = line.trim().replace(/^(?:>[ \t]*)+/u, "");
    const match = normalized.match(/^\[([^\]\r\n]+)\]:/u);
    if (match) labels.add(match[1].trim().toLocaleLowerCase("en-US"));
  }
  return labels;
}

function isResolvedPlaceholderReference(candidate, referenceLabels) {
  let normalized = candidate.trim();
  if (
    normalized.length >= 2 &&
    ((normalized.startsWith('"') && normalized.endsWith('"')) ||
      (normalized.startsWith("'") && normalized.endsWith("'")))
  ) {
    normalized = normalized.slice(1, -1).trim();
  }
  normalized = stripMarkdownWrappers(normalized);
  const match = normalized.match(/^\[([^\]\r\n]+)\]$/u);
  return Boolean(match && referenceLabels.has(match[1].trim().toLocaleLowerCase("en-US")));
}

function markdownTableEndIndex(lines, firstRowIndex) {
  let endIndex = firstRowIndex;
  while (endIndex < lines.length && markdownTableCells(lines[endIndex]) !== null) {
    endIndex += 1;
  }
  return endIndex;
}

function sensitiveMarkdownTableColumns(cells) {
  const sensitiveColumns = new Map();
  for (let cellIndex = 0; cellIndex < cells.length; cellIndex += 1) {
    const label = normalizeMarkdownTableLabel(cells[cellIndex]);
    if (isSensitiveMultilineLabel(label)) {
      sensitiveColumns.set(cellIndex, label);
    }
  }
  return sensitiveColumns;
}

function hasSensitiveDiscardedTableLabel(cells) {
  return cells.some((cell) => {
    const label = normalizeMarkdownTableLabel(cell);
    return label === UNSTABLE_MARKDOWN_LABEL_SENTINEL ||
      (isSensitiveMultilineLabel(label) && hasSensitiveDiscardedLabelMarkup(cell));
  });
}

function containsSensitiveTableValue(lines, headerIndex, separatorIndex, referenceLabels, endIndex) {
  const headerCells = markdownTableCells(lines[headerIndex]) || [];
  if (hasSensitiveDiscardedTableLabel(headerCells)) return true;
  let sensitiveColumns = sensitiveMarkdownTableColumns(headerCells);
  for (let rowIndex = separatorIndex + 1; rowIndex < endIndex; rowIndex += 1) {
    const cells = markdownTableCells(lines[rowIndex]);
    if (!cells) throw new Error("Markdown table boundary invariant failed");
    const nextIsSeparator = rowIndex + 1 < endIndex && isMarkdownTableSeparator(lines[rowIndex + 1]);
    const candidateSensitiveColumns = nextIsSeparator ? sensitiveMarkdownTableColumns(cells) : new Map();
    if (nextIsSeparator && hasSensitiveDiscardedTableLabel(cells)) return true;
    if (isMarkdownTableSeparator(lines[rowIndex])) continue;
    for (const [cellIndex, label] of sensitiveColumns) {
      const candidateValue = stripMarkdownWrappers(cells[cellIndex] || "");
      if (
        candidateValue !== "" &&
        (!isBenignValueForSensitiveLabel(candidateValue, label) ||
          isResolvedPlaceholderReference(candidateValue, referenceLabels))
      ) {
        return true;
      }
    }
    for (let cellIndex = 0; cellIndex + 1 < cells.length; cellIndex += 1) {
      const label = normalizeMarkdownTableLabel(cells[cellIndex]);
      const candidateValue = stripMarkdownWrappers(cells[cellIndex + 1]);
      if (
        isSensitiveMultilineLabel(label) &&
        (hasSensitiveDiscardedLabelMarkup(cells[cellIndex]) ||
          (candidateValue !== "" &&
            (!isBenignValueForSensitiveLabel(candidateValue, label) ||
              isResolvedPlaceholderReference(candidateValue, referenceLabels))))
      ) {
        return true;
      }
    }
    if (nextIsSeparator) {
      sensitiveColumns = candidateSensitiveColumns;
      rowIndex += 1;
    }
  }
  return false;
}

function containsSensitiveTable(value) {
  const lines = value.split(/\r?\n/);
  const referenceLabels = markdownReferenceDefinitionLabels(lines);
  for (let headerIndex = 0; headerIndex + 1 < lines.length; headerIndex += 1) {
    if (markdownTableCells(lines[headerIndex]) === null || !isMarkdownTableSeparator(lines[headerIndex + 1])) continue;
    const endIndex = markdownTableEndIndex(lines, headerIndex + 2);
    if (containsSensitiveTableValue(lines, headerIndex, headerIndex + 1, referenceLabels, endIndex)) return true;
    headerIndex = endIndex - 1;
  }
  return false;
}

function normalizeMarkdownContentLine(line) {
  return line
    .trim()
    .replace(/^(?:>[ \t]*)+/u, "")
    .replace(/^(?:[-*+]|\d+[.)])[ \t]+(?:\[[ xX]\][ \t]+)?/u, "");
}

function splitMarkdownField(line) {
  let bracketDepth = 0;
  let parenthesisDepth = 0;
  let unmatchedClosingMarkdown = false;
  let escaped = false;
  let htmlTag = false;
  let htmlQuote = null;
  let htmlComment = false;
  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    if (htmlComment) {
      if (line.startsWith("-->", index)) {
        htmlComment = false;
        index += 2;
      }
      continue;
    }
    if (htmlTag) {
      if (htmlQuote !== null) {
        if (character === htmlQuote) htmlQuote = null;
      } else if (character === '"' || character === "'") {
        htmlQuote = character;
      } else if (character === ">") {
        htmlTag = false;
      }
      continue;
    }
    if (escaped) {
      if (character === "]" || character === ")") unmatchedClosingMarkdown = true;
      escaped = false;
      continue;
    }
    if (character === "\\") {
      escaped = true;
      continue;
    }
    if (line.startsWith("<!--", index)) {
      htmlComment = true;
      index += 3;
      continue;
    }
    if (line.startsWith("<?", index)) {
      const instructionEnd = line.indexOf("?>", index + 2);
      if (instructionEnd === -1) return null;
      index = instructionEnd + 1;
      continue;
    }
    if (line.startsWith("<![CDATA[", index)) {
      const cdataEnd = line.indexOf("]]>", index + 9);
      if (cdataEnd === -1) return null;
      index = cdataEnd + 2;
      continue;
    }
    if (character === "<" && line[index + 1] === "!" && /[A-Z]/u.test(line[index + 2] || "")) {
      const declarationEnd = line.indexOf(">", index + 2);
      if (declarationEnd === -1) return null;
      index = declarationEnd;
      continue;
    }
    const tagNameStart = line[index + 1] === "/" ? index + 2 : index + 1;
    if (character === "<" && /[A-Za-z]/u.test(line[tagNameStart] || "")) {
      htmlTag = true;
      continue;
    }
    if (character === "[") bracketDepth += 1;
    else if (character === "]" && bracketDepth > 0) bracketDepth -= 1;
    else if (character === "]") unmatchedClosingMarkdown = true;
    else if (character === "(" && bracketDepth === 0) parenthesisDepth += 1;
    else if (character === ")" && bracketDepth === 0 && parenthesisDepth > 0) parenthesisDepth -= 1;
    else if (character === ")" && bracketDepth === 0) unmatchedClosingMarkdown = true;
    else if ((character === ":" || character === "=") && bracketDepth === 0 && parenthesisDepth === 0) {
      if (unmatchedClosingMarkdown) {
        const recovered = recoverMalformedSensitiveField(line);
        if (recovered) return [recovered.label, recovered.value];
      }
      return [line.slice(0, index).trim(), line.slice(index + 1).trim()];
    }
  }
  if (bracketDepth > 0 || parenthesisDepth > 0) {
    const recovered = recoverMalformedSensitiveField(line);
    if (recovered) return [recovered.label, recovered.value];
  }
  return null;
}

function parseSensitiveLabelLine(line) {
  const normalized = normalizeMarkdownContentLine(line);
  const field = splitMarkdownField(normalized);
  const fieldLabel = field ? normalizeMarkdownTableLabel(field[0].replace(/^["']|["']$/gu, "")) : "";
  if (field && isSensitiveMultilineLabel(fieldLabel)) {
    const inlineValue = hasSensitiveDiscardedLabelMarkup(field[0])
      ? UNSTABLE_MARKDOWN_LABEL_SENTINEL
      : /^[>|](?:[+-]?[1-9]?|[1-9]?[+-]?)$/u.test(field[1])
        ? ""
        : field[1];
    return { label: fieldLabel, inlineValue, structural: true };
  }
  const heading = normalized.match(/^#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$/u);
  const headingLabel = heading ? normalizeMarkdownTableLabel(heading[1]) : "";
  if (heading && isSensitiveMultilineLabel(headingLabel)) {
    return {
      label: headingLabel,
      inlineValue:
        headingLabel === UNSTABLE_MARKDOWN_LABEL_SENTINEL || hasSensitiveDiscardedLabelMarkup(heading[1])
          ? UNSTABLE_MARKDOWN_LABEL_SENTINEL
          : "",
      structural: true,
    };
  }
  const standaloneSource = normalized.replace(/^['"]|['"]$/gu, "").trim();
  if (standaloneSource.length > MAX_MARKDOWN_LABEL_LENGTH) {
    const isCandidate =
      SENSITIVE_LABEL_CANDIDATE_PATTERN.test(standaloneSource) ||
      UNRESOLVED_HTML_NAMED_REFERENCE_PATTERN.test(standaloneSource) ||
      hasSensitiveDiscardedLabelMarkup(standaloneSource);
    return isCandidate
      ? { label: UNSTABLE_MARKDOWN_LABEL_SENTINEL, inlineValue: "", structural: false }
      : null;
  }
  const standaloneLabel = normalizeMarkdownTableLabel(standaloneSource);
  const normalizedMarkup = standaloneLabel !== standaloneSource;
  if (isSensitiveMultilineLabel(standaloneLabel)) {
    return {
      label: standaloneLabel,
      inlineValue:
        standaloneLabel === UNSTABLE_MARKDOWN_LABEL_SENTINEL || hasSensitiveDiscardedLabelMarkup(standaloneSource)
          ? UNSTABLE_MARKDOWN_LABEL_SENTINEL
          : "",
      structural: normalizedMarkup,
    };
  }
  return null;
}

function isBenignValueForSensitiveLabel(value, label) {
  return (
    BENIGN_MULTILINE_SENSITIVE_VALUE_PATTERN.test(value) ||
    (BENIGN_SESSION_PROSE_LABEL_PATTERN.test(label) && BENIGN_SESSION_PROSE_VALUE_PATTERN.test(value))
  );
}

function parseSensitiveLabelAt(lines, index) {
  const direct = parseSensitiveLabelLine(lines[index]);
  if (direct) return { ...direct, valueIndex: index + 1 };
  if (index + 1 >= lines.length) return null;
  const underline = normalizeMarkdownContentLine(lines[index + 1]);
  if (!/^(?:={3,}|-{3,})$/u.test(underline)) return null;
  const labelSource = normalizeMarkdownContentLine(lines[index]);
  const label = normalizeMarkdownTableLabel(labelSource);
  return isSensitiveMultilineLabel(label)
    ? {
        label,
        inlineValue: hasSensitiveDiscardedLabelMarkup(labelSource) ? UNSTABLE_MARKDOWN_LABEL_SENTINEL : "",
        structural: true,
        valueIndex: index + 2,
      }
    : null;
}

function isSensitiveStructuralBoundaryAt(lines, index, referenceLabels) {
  const match = parseSensitiveLabelAt(lines, index);
  if (!match) return false;
  if (match.structural) return true;
  if (match.inlineValue !== "") return false;
  let valueIndex = match.valueIndex;
  while (valueIndex < lines.length && lines[valueIndex].trim() === "") valueIndex += 1;
  if (valueIndex >= lines.length) return false;
  const candidateValue = stripMarkdownWrappers(normalizeMarkdownContentLine(lines[valueIndex]));
  return (
    isBenignValueForSensitiveLabel(candidateValue, match.label) &&
    !isResolvedPlaceholderReference(candidateValue, referenceLabels)
  );
}

function isSafeStructuralBoundary(line) {
  const normalized = normalizeMarkdownContentLine(line);
  const heading = normalized.match(/^#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$/u);
  if (heading) return SAFE_STRUCTURAL_LABEL_PATTERN.test(normalizeMarkdownTableLabel(heading[1]));
  const field = splitMarkdownField(normalized);
  const fieldLabel = field ? normalizeMarkdownTableLabel(field[0].replace(/^["']|["']$/gu, "")) : "";
  return Boolean(field && SAFE_STRUCTURAL_LABEL_PATTERN.test(fieldLabel));
}

function containsSensitiveMultilineValue(value) {
  const lines = value.split(/\r?\n/);
  const referenceLabels = markdownReferenceDefinitionLabels(lines);
  for (let index = 0; index < lines.length; index += 1) {
    const labelMatch = parseSensitiveLabelAt(lines, index);
    if (!labelMatch) continue;

    const inlineValue = labelMatch.inlineValue;
    if (inlineValue !== "") {
      const normalizedInlineValue = stripMarkdownWrappers(inlineValue);
      if (
        !isBenignValueForSensitiveLabel(normalizedInlineValue, labelMatch.label) ||
        isResolvedPlaceholderReference(normalizedInlineValue, referenceLabels)
      ) return true;
      for (let continuationIndex = index + 1; continuationIndex < lines.length; continuationIndex += 1) {
        const continuation = lines[continuationIndex];
        if (continuation.trim() === "") continue;
        if (isSensitiveStructuralBoundaryAt(lines, continuationIndex, referenceLabels)) break;
        if (isSafeStructuralBoundary(continuation)) break;
        if (!isBenignValueForSensitiveLabel(normalizeMarkdownContentLine(continuation), labelMatch.label)) return true;
      }
      continue;
    }

    let valueIndex = labelMatch.valueIndex;
    while (valueIndex < lines.length && lines[valueIndex].trim() === "") valueIndex += 1;
    if (valueIndex >= lines.length) continue;

    let nextContentIndex = valueIndex + 1;
    while (nextContentIndex < lines.length && lines[nextContentIndex].trim() === "") {
      nextContentIndex += 1;
    }
    if (
      markdownTableCells(lines[valueIndex]) !== null &&
      nextContentIndex < lines.length &&
      isMarkdownTableSeparator(lines[nextContentIndex])
    ) {
      if (
        containsSensitiveTableValue(
          lines,
          valueIndex,
          nextContentIndex,
          referenceLabels,
          markdownTableEndIndex(lines, nextContentIndex + 1),
        )
      ) return true;
      continue;
    }

    if (
      parseSensitiveLabelAt(lines, valueIndex)?.structural === true ||
      isSafeStructuralBoundary(lines[valueIndex])
    ) continue;
    const normalizedFirstValue = normalizeMarkdownContentLine(lines[valueIndex]);
    if (
      !isBenignValueForSensitiveLabel(normalizedFirstValue, labelMatch.label) ||
      isResolvedPlaceholderReference(normalizedFirstValue, referenceLabels)
    ) return true;
    for (let continuationIndex = valueIndex + 1; continuationIndex < lines.length; continuationIndex += 1) {
      const continuation = lines[continuationIndex];
      if (continuation.trim() === "") continue;
      if (isSensitiveStructuralBoundaryAt(lines, continuationIndex, referenceLabels)) break;
      if (isSafeStructuralBoundary(continuation)) break;
      if (!isBenignValueForSensitiveLabel(normalizeMarkdownContentLine(continuation), labelMatch.label)) return true;
    }
  }
  return false;
}

function containsSensitiveContent(value) {
  const normalized = decodeHtmlCharacterReferences(value.replace(/\r\n?/gu, "\n"))
    .normalize("NFKC")
    .replace(/\p{Default_Ignorable_Code_Point}/gu, "")
    .replace(/\\+([:=])/gu, "$1");
  if (BENIGN_SECURITY_CONTEXT_PATTERNS.some((pattern) => pattern.test(normalized))) return false;
  const markdown = collapseRawHtmlMarkupNewlines(normalized);
  const markdownPatternInput = markdown.value;
  // Inline key/value detectors may intentionally span horizontal whitespace, but a
  // Markdown line or paragraph break after prose such as "authenticated session:" is
  // not a credential assignment. Preserve deliberate indented config values while
  // preventing inline detectors from consuming an unindented following line.
  const inlinePatternInput = normalized
    .replace(/(:[ \t]*)[>|](?:[+-]?[1-9]?|[1-9]?[+-]?)[ \t]*(?=\r?\n)/gu, "$1")
    .replace(/\r?\n(?![ \t])/g, "\n,\n");
  return (
    markdown.sensitiveUnterminated ||
    containsControllerAddress(normalized) ||
    containsSensitiveConfigurationBlob(normalized) ||
    containsSensitiveTable(markdownPatternInput) ||
    containsSensitiveMultilineValue(markdownPatternInput) ||
    SENSITIVE_PATTERNS.some((pattern) => pattern.test(inlinePatternInput))
  );
}

function normalizeAuthor(value) {
  if (typeof value === "string") return value;
  const login = value?.login;
  return typeof login === "string" ? login : null;
}

function isValidGitHubActorLogin(value) {
  return (
    typeof value === "string" &&
    value.length <= 100 &&
    /^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\[bot\])?$/u.test(value)
  );
}

function normalizeLabels(labels) {
  if (!Array.isArray(labels)) return [];
  return labels
    .map((label) => (typeof label === "string" ? label : label?.name))
    .filter((label) => typeof label === "string")
    .sort((left, right) => left.localeCompare(right));
}

export function normalizeIssue(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) fail("GitHub returned an invalid issue");
  const number = assertSafePositiveInteger(raw.number, "issue number");
  const state = String(raw.state || "").toLowerCase();
  if (state !== "open" && state !== "closed") fail(`issue #${number} has an invalid state`);
  const title = normalizeNullableText(raw.title);
  const body = normalizeNullableText(raw.body);
  return {
    number,
    title,
    body,
    state,
    created_at: normalizeNullableText(raw.created_at),
    updated_at: normalizeNullableText(raw.updated_at),
    closed_at: raw.closed_at === null || raw.closed_at === undefined ? null : normalizeNullableText(raw.closed_at),
    author: normalizeAuthor(raw.user ?? raw.author),
    labels: normalizeLabels(raw.labels),
  };
}

export function normalizeComment(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) fail("GitHub returned an invalid issue comment");
  const id = assertSafePositiveInteger(raw.id, "comment id");
  return {
    id,
    body: normalizeNullableText(raw.body),
    created_at: normalizeNullableText(raw.created_at),
    updated_at: normalizeNullableText(raw.updated_at),
    author: normalizeAuthor(raw.user ?? raw.author),
  };
}

export function normalizeTimelineEvent(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) fail("GitHub returned an invalid issue timeline event");
  const event = normalizeNullableText(raw.event).toLowerCase();
  if (event === "") fail("timeline event type is invalid");
  const label = raw.label === null || raw.label === undefined
    ? null
    : normalizeNullableText(typeof raw.label === "string" ? raw.label : raw.label?.name);
  const actor = normalizeAuthor(raw.actor);
  // GitHub returns null IDs for some cross-reference events and may return numeric
  // IDs beyond JavaScript's safe-integer range. Only trusted bot needs-info removals
  // affect the continuation count, so validate their IDs as opaque decimals.
  const candidateNeedsInfoRemoval = event === "unlabeled" && label === "needs-info";
  if (candidateNeedsInfoRemoval && !isValidGitHubActorLogin(actor)) {
    fail("needs-info removal timeline event actor is invalid");
  }
  const relevantNeedsInfoRemoval = candidateNeedsInfoRemoval && actor === ACTIONS_BOT;
  if (relevantNeedsInfoRemoval) validateRelevantTimelineIdentifier(raw.id);
  return {
    id: relevantNeedsInfoRemoval ? String(raw.id) : null,
    event,
    created_at: normalizeNullableText(raw.created_at),
    actor,
    label,
  };
}

function normalizeTrigger(trigger) {
  if (!exactKeys(trigger, ["event_name", "action", "actor", "issue_number", "comment_id"])) {
    fail("trigger identity contains unexpected fields");
  }
  if (trigger.event_name !== "issues" && trigger.event_name !== "issue_comment") fail("trigger event is invalid");
  if (typeof trigger.action !== "string" || typeof trigger.actor !== "string" || trigger.actor === "") fail("trigger action or actor is invalid");
  assertSafePositiveInteger(trigger.issue_number, "trigger issue number");
  if (trigger.comment_id !== null) assertSafePositiveInteger(trigger.comment_id, "trigger comment id");
  return trigger;
}

/** Fail-closed deterministic eligibility for automatic community intake. */
export function evaluateIntakeEligibility({
  eventName,
  action,
  actor,
  issue,
  eventComment = null,
  comments = [],
  timelineEvents = [],
}) {
  const target = normalizeIssue(issue);
  if (!Array.isArray(comments) || comments.length > MAX_TARGET_COMMENTS) fail("eligibility comments exceed the trusted bound");
  if (!Array.isArray(timelineEvents) || timelineEvents.length > MAX_TIMELINE_EVENTS) fail("eligibility timeline events exceed the trusted bound");
  const normalizedComments = comments.map(normalizeComment).sort((left, right) => left.id - right.id);
  // Timeline IDs are opaque and may be null or exceed JavaScript's safe-integer
  // range. Eligibility depends only on trusted event type, actor, label, and time.
  const normalizedTimelineEvents = timelineEvents.map(normalizeTimelineEvent);
  const triggerComment = eventComment === null ? null : normalizeComment(eventComment);
  const initialMarkerComments = normalizedComments.filter(
    (comment) => comment.author === ACTIONS_BOT && comment.body.includes(INITIAL_MARKER),
  );
  const initialMarkerCount = initialMarkerComments.length;
  let continuationCommentCount = 0;
  let needsInfoRemovalCount = 0;
  if (initialMarkerCount === 1) {
    const initialMarkerCreatedAt = Date.parse(initialMarkerComments[0].created_at);
    if (!Number.isFinite(initialMarkerCreatedAt)) fail("trusted initial marker timestamp is invalid");
    continuationCommentCount = normalizedComments.filter((comment) => {
      if (comment.author !== ACTIONS_BOT || !comment.body.includes(CONTINUATION_MARKER)) return false;
      const createdAt = Date.parse(comment.created_at);
      if (!Number.isFinite(createdAt)) fail("trusted continuation marker timestamp is invalid");
      return createdAt >= initialMarkerCreatedAt;
    }).length;
    needsInfoRemovalCount = normalizedTimelineEvents.filter((event) => {
      if (event.event !== "unlabeled" || event.actor !== ACTIONS_BOT || event.label !== "needs-info") return false;
      const createdAt = Date.parse(event.created_at);
      if (!Number.isFinite(createdAt)) fail("trusted needs-info removal timestamp is invalid");
      return createdAt >= initialMarkerCreatedAt;
    }).length;
  }
  const continuationCount = continuationCommentCount + needsInfoRemovalCount;
  const needsInfoPresent = target.labels.includes("needs-info");
  const trigger = normalizeTrigger({
    event_name: eventName,
    action,
    actor,
    issue_number: target.number,
    comment_id: triggerComment?.id ?? null,
  });
  const base = {
    eligible: false,
    reason: "event is not eligible",
    target_number: target.number,
    run_kind: null,
    trigger,
    initial_marker_count: initialMarkerCount,
    continuation_count: continuationCount,
    needs_info_present: needsInfoPresent,
  };
  if (issue?.pull_request) return {...base, reason: "target identifies a pull request"};
  if (target.state !== "open") return {...base, reason: "target issue is not open"};
  if (typeof target.author !== "string" || target.author === "" || issue?.user?.type === "Bot") {
    return {...base, reason: "target author is not an eligible human reporter"};
  }
  if (actor !== target.author) return {...base, reason: "trigger actor is not the issue author"};
  if (eventName === "issues" && action === "opened") {
    if (triggerComment !== null) return {...base, reason: "initial issue event cannot bind a comment"};
    if (initialMarkerCount !== 0) return {...base, reason: "trusted initial triage marker already exists"};
    return {...base, eligible: true, reason: "eligible initial intake", run_kind: "initial"};
  }
  const continuationEvent = eventName === "issues" && action === "edited";
  const commentEvent = eventName === "issue_comment" && action === "created";
  if (!continuationEvent && !commentEvent) return base;
  if (commentEvent) {
    if (triggerComment === null || triggerComment.author !== actor) return {...base, reason: "triggering comment identity mismatch"};
    const collected = normalizedComments.find((comment) => comment.id === triggerComment.id);
    if (!collected || canonicalDigest(collected) !== canonicalDigest(triggerComment)) {
      return {...base, reason: "triggering comment is not bound to the trusted collection"};
    }
  } else if (triggerComment !== null) {
    return {...base, reason: "edited issue event cannot bind a comment"};
  }
  if (!needsInfoPresent) return {...base, reason: "continuation requires needs-info"};
  if (initialMarkerCount !== 1) return {...base, reason: "continuation requires exactly one trusted initial marker"};
  if (continuationCount >= 2) return {...base, reason: "continuation limit reached"};
  return {...base, eligible: true, reason: "eligible continuation", run_kind: "continuation"};
}

function canonicalize(value, seen) {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) fail("canonical JSON cannot contain a non-finite number");
    return value;
  }
  if (Array.isArray(value)) return value.map((item) => canonicalize(item, seen));
  if (!value || typeof value !== "object") fail("canonical JSON contains an unsupported value");
  if (seen.has(value)) fail("canonical JSON cannot contain a cycle");
  seen.add(value);
  const result = {};
  for (const key of Object.keys(value).sort()) {
    if (value[key] === undefined) fail("canonical JSON cannot contain undefined");
    result[key] = canonicalize(value[key], seen);
  }
  seen.delete(value);
  return result;
}

export function canonicalStringify(value) {
  return JSON.stringify(canonicalize(value, new Set()));
}

export function canonicalDigest(value) {
  return createHash("sha256").update(canonicalStringify(value), "utf8").digest("hex");
}

function receiptFactory(randomBytes) {
  const source = randomBytes || cryptoRandomBytes;
  return () => {
    const bytes = source(16);
    if (!Buffer.isBuffer(bytes) && !(bytes instanceof Uint8Array)) {
      fail("randomBytes must return 16 bytes");
    }
    if (bytes.byteLength !== 16) fail("randomBytes must return exactly 16 bytes");
    return Buffer.from(bytes).toString("hex");
  };
}

function tokenize(value) {
  const matches = value.toLowerCase().match(/[a-z0-9]+(?:[._-][a-z0-9]+)*/g) || [];
  return [...new Set(matches.filter(
    (token) => token.length >= 3 && token.length <= 100 && !STOP_WORDS.has(token),
  ))];
}

function tokenWeight(token) {
  if (/^\d+(?:\.\d+){1,}$/.test(token)) return 8;
  if (token.includes("-") || token.includes("_")) return 5;
  if (token.length >= 10) return 4;
  return 2;
}

async function fetchIssue(github, owner, repo, issueNumber) {
  const response = await github.rest.issues.get({owner, repo, issue_number: issueNumber});
  const raw = response?.data;
  if (!raw || raw.pull_request) fail(`issue #${issueNumber} is missing or identifies a pull request`);
  return normalizeIssue(raw);
}

async function requireNeedsInfoLabel(github, owner, repo) {
  let response;
  try {
    response = await github.rest.issues.getLabel({owner, repo, name: "needs-info"});
  } catch {
    fail("required repository label 'needs-info' is missing or unreadable; create it before calibration");
  }
  if (response?.data?.name !== "needs-info") {
    fail("required repository label 'needs-info' is missing or unreadable; create it before calibration");
  }
}

async function fetchBoundedComments(github, owner, repo, issueNumber) {
  const request = {owner, repo, issue_number: issueNumber, per_page: 100, page: 1};
  const response = await github.rest.issues.listComments(request);
  if (!Array.isArray(response?.data)) fail("GitHub returned an invalid issue comment collection");
  if (response.data.length > MAX_TARGET_COMMENTS) fail("target comment count exceeds the trusted bound");
  const comments = response.data.map(normalizeComment);
  if (comments.length === MAX_TARGET_COMMENTS) {
    const overflow = await github.rest.issues.listComments({...request, page: 2});
    if (!Array.isArray(overflow?.data)) fail("GitHub returned an invalid issue comment overflow response");
    if (overflow.data.length > 0) fail("target comment count exceeds the trusted bound");
  }
  return comments.sort((left, right) => left.id - right.id);
}

async function fetchBoundedTimelineEvents(github, owner, repo, issueNumber) {
  const request = {owner, repo, issue_number: issueNumber, per_page: 100, page: 1};
  const response = await github.rest.issues.listEventsForTimeline(request);
  if (!Array.isArray(response?.data)) fail("GitHub returned an invalid issue timeline event collection");
  if (response.data.length > MAX_TIMELINE_EVENTS) fail("target timeline event count exceeds the trusted bound");
  const events = response.data.map(normalizeTimelineEvent);
  if (events.length === MAX_TIMELINE_EVENTS) {
    const overflow = await github.rest.issues.listEventsForTimeline({...request, page: 2});
    if (!Array.isArray(overflow?.data)) fail("GitHub returned an invalid issue timeline event overflow response");
    if (overflow.data.length > 0) fail("target timeline event count exceeds the trusted bound");
  }
  return events;
}

async function scanCandidates(github, owner, repo, target) {
  const targetTokens = tokenize(target.title);
  if (targetTokens.length === 0) {
    return {candidates: [], scanned: 0, truncated: false, searchPerformed: false, reason: "no-distinctive-title-terms"};
  }
  const collected = [];
  let cursor = null;
  let truncated = false;
  for (let page = 0; page < 10; page += 1) {
    const result = await github.graphql(
      `query($owner: String!, $repo: String!, $cursor: String) {
        repository(owner: $owner, name: $repo) {
          issues(first: 100, after: $cursor, orderBy: {field: CREATED_AT, direction: DESC}, states: [OPEN, CLOSED]) {
            nodes { number title state createdAt closedAt }
            pageInfo { hasNextPage endCursor }
          }
        }
      }`,
      {owner, repo, cursor},
    );
    const connection = result?.repository?.issues;
    if (!connection || !Array.isArray(connection.nodes)) fail("GitHub returned an invalid issue candidate response");
    if (connection.nodes.length > 100) fail("GitHub returned more than 100 issues in one candidate page");
    collected.push(...connection.nodes);
    if (collected.length > MAX_SCANNED_ISSUES) fail("candidate scan exceeded its trusted issue bound");
    if (!connection.pageInfo?.hasNextPage) break;
    if (page === 9) {
      truncated = true;
      break;
    }
    cursor = connection.pageInfo.endCursor;
    if (typeof cursor !== "string" || cursor === "") fail("GitHub issue pagination omitted endCursor");
  }

  const targetCreatedAt = Date.parse(target.created_at);
  if (!Number.isFinite(targetCreatedAt)) fail("target issue created_at is invalid");
  const closedCutoff = targetCreatedAt - 365 * 24 * 60 * 60 * 1000;
  const targetTokenSet = new Set(targetTokens);
  const ranked = collected
    .filter((candidate) => Number(candidate?.number) !== target.number)
    .filter((candidate) => {
      const state = String(candidate?.state || "").toUpperCase();
      if (state === "OPEN") return true;
      if (state !== "CLOSED") return false;
      const closedAt = Date.parse(candidate.closedAt);
      return Number.isFinite(closedAt) && closedAt >= closedCutoff;
    })
    .map((candidate) => {
      const number = assertSafePositiveInteger(candidate.number, "candidate number");
      const title = normalizeNullableText(candidate.title);
      const shared = tokenize(title).filter((token) => targetTokenSet.has(token));
      return {
        number,
        state: String(candidate.state).toLowerCase(),
        shared,
        score: shared.reduce((total, token) => total + tokenWeight(token), 0),
      };
    })
    .filter((candidate) => candidate.shared.length >= 2 && candidate.score >= 6)
    .sort((left, right) =>
      right.score - left.score || right.shared.length - left.shared.length || right.number - left.number,
    )
    .slice(0, MAX_CANDIDATES)
    .map(({number, state, score}) => {
      const source = collected.find((candidate) => candidate.number === number);
      return {number, state, score, title: normalizeNullableText(source?.title)};
    });

  return {candidates: ranked, scanned: collected.length, truncated, searchPerformed: true, reason: null};
}

function issueTextItems(issue, prefix) {
  return [
    {name: `${prefix} title`, value: issue.title},
    {name: `${prefix} body`, value: issue.body},
  ];
}

function commentsTextItems(comments) {
  return comments.map((comment) => ({name: `target comment ${comment.id}`, value: comment.body}));
}

function inspectEvidence(textItems) {
  let totalBytes = 0;
  let sensitive = false;
  for (const item of textItems) {
    totalBytes += textBytes(item.value, item.name);
    sensitive = sensitive || containsSensitiveContent(item.value);
  }
  if (totalBytes > MAX_RAW_EVIDENCE_BYTES) {
    fail(`raw evidence exceeds the ${MAX_RAW_EVIDENCE_BYTES}-byte aggregate limit`);
  }
  return {totalBytes, sensitive};
}

function baseBundle({
  repository, runId, workflowSha, targetNumber, targetReceipt, targetDigest,
  runKind, trigger, triggerReceipt, initialMarkerCount, continuationCount,
  needsInfoPresent,
}) {
  return {
    version: CONTRACT_VERSION,
    status: "complete",
    strategy: SNAPSHOT_STRATEGY,
    repository,
    run_id: runId,
    workflow_sha: workflowSha,
    target_number: targetNumber,
    run_kind: runKind,
    trigger,
    trigger_receipt: triggerReceipt,
    initial_marker_count: initialMarkerCount,
    continuation_count: continuationCount,
    needs_info_present: needsInfoPresent,
    scanned: 0,
    scan_truncated: false,
    search_performed: false,
    search_reason: null,
    content_persisted: false,
    sensitivity: null,
    target: {receipt: targetReceipt, digest: targetDigest, data: null},
    comments: null,
    candidates: [],
  };
}

function sensitiveBundle(bundle, scope) {
  bundle.status = "sensitive_stop";
  bundle.content_persisted = false;
  bundle.sensitivity = {scope};
  bundle.target.data = null;
  if (bundle.comments) bundle.comments.data = null;
  for (const candidate of bundle.candidates) candidate.data = null;
  return bundle;
}

function snapshotResult(bundle) {
  validateBundle(bundle);
  const json = canonicalStringify(bundle);
  return {
    bundle,
    json,
    digest: createHash("sha256").update(json, "utf8").digest("hex"),
  };
}

/**
 * Build the trusted v3 artifact bundle using an injected Octokit-like client.
 */
export async function createTrustedSnapshot({
  github,
  owner,
  repo,
  targetNumber,
  runId,
  workflowSha,
  runKind,
  trigger,
  expectedInitialMarkerCount = 0,
  expectedContinuationCount = 0,
  expectedNeedsInfoPresent = false,
  randomBytes,
}) {
  if (!github?.rest?.issues?.get || !github?.rest?.issues?.getLabel || !github?.rest?.issues?.listComments || !github?.rest?.issues?.listEventsForTimeline || !github?.graphql) {
    fail("createTrustedSnapshot requires an injected GitHub issue and GraphQL client");
  }
  assertSafePositiveInteger(targetNumber, "targetNumber");
  const repository = normalizeRepository(owner, repo);
  const normalizedRunId = normalizeRunId(runId);
  const normalizedWorkflowSha = assertWorkflowSha(workflowSha);
  const nextReceipt = receiptFactory(randomBytes);
  if (!RUN_KINDS.has(runKind)) fail("snapshot run kind is invalid");
  const normalizedTrigger = normalizeTrigger(trigger);
  if (normalizedTrigger.issue_number !== targetNumber) fail("snapshot trigger target binding mismatch");
  if (!Number.isSafeInteger(expectedInitialMarkerCount) || expectedInitialMarkerCount < 0) fail("expected initial marker count is invalid");
  if (!Number.isSafeInteger(expectedContinuationCount) || expectedContinuationCount < 0 || expectedContinuationCount > 1) fail("expected continuation count is invalid");
  if (typeof expectedNeedsInfoPresent !== "boolean") fail("expected needs-info state is invalid");

  await requireNeedsInfoLabel(github, owner, repo);
  const target = await fetchIssue(github, owner, repo, targetNumber);
  const targetReceipt = nextReceipt();
  const targetDigest = canonicalDigest(target);
  const bundle = baseBundle({
    repository,
    runId: normalizedRunId,
    workflowSha: normalizedWorkflowSha,
    targetNumber,
    targetReceipt,
    targetDigest,
    runKind,
    trigger: normalizedTrigger,
    triggerReceipt: nextReceipt(),
    initialMarkerCount: expectedInitialMarkerCount,
    continuationCount: expectedContinuationCount,
    needsInfoPresent: expectedNeedsInfoPresent,
  });
  const targetInspection = inspectEvidence(issueTextItems(target, "target"));
  if (targetInspection.sensitive) return snapshotResult(sensitiveBundle(bundle, "target"));

  const comments = await fetchBoundedComments(github, owner, repo, targetNumber);
  const timelineEvents = await fetchBoundedTimelineEvents(github, owner, repo, targetNumber);
  const eventComment = normalizedTrigger.comment_id === null
    ? null
    : comments.find((comment) => comment.id === normalizedTrigger.comment_id) || null;
  const eligibility = evaluateIntakeEligibility({
    eventName: normalizedTrigger.event_name,
    action: normalizedTrigger.action,
    actor: normalizedTrigger.actor,
    issue: target,
    eventComment,
    comments,
    timelineEvents,
  });
  if (
    !eligibility.eligible || eligibility.run_kind !== runKind ||
    eligibility.initial_marker_count !== expectedInitialMarkerCount ||
    eligibility.continuation_count !== expectedContinuationCount ||
    eligibility.needs_info_present !== expectedNeedsInfoPresent
  ) fail("trusted intake eligibility changed before snapshot creation");
  const commentsReceipt = nextReceipt();
  const commentsDigest = canonicalDigest(comments);
  bundle.comments = {
    receipt: commentsReceipt,
    digest: commentsDigest,
    count: comments.length,
    data: null,
  };
  const commentsInspection = inspectEvidence([
    ...issueTextItems(target, "target"),
    ...commentsTextItems(comments),
  ]);
  if (commentsInspection.sensitive) return snapshotResult(sensitiveBundle(bundle, "comments"));

  const scan = await scanCandidates(github, owner, repo, target);
  bundle.scanned = scan.scanned;
  bundle.scan_truncated = scan.truncated;
  bundle.search_performed = scan.searchPerformed;
  bundle.search_reason = scan.reason;

  const retained = [];
  for (const candidate of scan.candidates) {
    const data = await fetchIssue(github, owner, repo, candidate.number);
    if (data.title !== candidate.title || data.state !== candidate.state) {
      fail(`candidate #${candidate.number} changed during trusted snapshot creation`);
    }
    retained.push({
      number: candidate.number,
      state: candidate.state,
      score: candidate.score,
      receipt: nextReceipt(),
      digest: canonicalDigest(data),
      data,
    });
  }
  bundle.candidates = retained;

  const allTextItems = [
    ...issueTextItems(target, "target"),
    ...commentsTextItems(comments),
    ...retained.flatMap((candidate) => issueTextItems(candidate.data, `candidate ${candidate.number}`)),
  ];
  const allInspection = inspectEvidence(allTextItems);
  if (allInspection.sensitive) return snapshotResult(sensitiveBundle(bundle, "candidate"));

  bundle.content_persisted = true;
  bundle.target.data = target;
  bundle.comments.data = comments;
  return snapshotResult(bundle);
}

function validateCandidateMetadata(candidate, targetNumber) {
  if (!exactKeys(candidate, ["number", "state", "score", "receipt", "digest", "data"])) {
    fail("snapshot candidate contains unexpected fields or field order");
  }
  assertSafePositiveInteger(candidate.number, "candidate number");
  if (candidate.number === targetNumber) fail("snapshot candidate cannot equal the target");
  if (candidate.state !== "open" && candidate.state !== "closed") fail("snapshot candidate has an invalid state");
  if (!Number.isSafeInteger(candidate.score) || candidate.score < 6) fail("snapshot candidate has an invalid lexical score");
  assertReceipt(candidate.receipt, "candidate receipt");
  assertDigest(candidate.digest, "candidate digest");
}

/** Strictly validate a bundle and its content digests. */
export function validateBundle(bundle) {
  if (!exactKeys(bundle, [
    "version", "status", "strategy", "repository", "run_id", "workflow_sha",
    "target_number", "run_kind", "trigger", "trigger_receipt", "initial_marker_count",
    "continuation_count", "needs_info_present", "scanned", "scan_truncated", "search_performed", "search_reason",
    "content_persisted", "sensitivity", "target", "comments", "candidates",
  ])) fail("snapshot bundle contains unexpected fields or field order");
  if (bundle.version !== CONTRACT_VERSION || bundle.strategy !== SNAPSHOT_STRATEGY) fail("snapshot bundle version or strategy is invalid");
  if (bundle.status !== "complete" && bundle.status !== "sensitive_stop") fail("snapshot bundle status is invalid");
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(bundle.repository)) fail("snapshot repository binding is invalid");
  normalizeRunId(bundle.run_id);
  assertWorkflowSha(bundle.workflow_sha);
  assertSafePositiveInteger(bundle.target_number, "snapshot target number");
  if (!RUN_KINDS.has(bundle.run_kind)) fail("snapshot run kind is invalid");
  normalizeTrigger(bundle.trigger);
  if (bundle.trigger.issue_number !== bundle.target_number) fail("snapshot trigger target binding mismatch");
  assertReceipt(bundle.trigger_receipt, "trigger receipt");
  if (!Number.isSafeInteger(bundle.initial_marker_count) || bundle.initial_marker_count < 0) fail("snapshot initial marker count is invalid");
  if (!Number.isSafeInteger(bundle.continuation_count) || bundle.continuation_count < 0 || bundle.continuation_count > 1) fail("snapshot continuation count is invalid");
  if (typeof bundle.needs_info_present !== "boolean") fail("snapshot needs-info state is invalid");
  if (bundle.run_kind === "initial" && bundle.initial_marker_count !== 0) fail("initial snapshot eligibility bindings are invalid");
  if (bundle.run_kind === "continuation" && (bundle.initial_marker_count < 1 || !bundle.needs_info_present)) fail("continuation snapshot eligibility bindings are invalid");
  if (!Number.isSafeInteger(bundle.scanned) || bundle.scanned < 0 || bundle.scanned > MAX_SCANNED_ISSUES) fail("snapshot scanned count is invalid");
  if (typeof bundle.scan_truncated !== "boolean" || typeof bundle.search_performed !== "boolean") fail("snapshot scan flags are invalid");
  if (bundle.scan_truncated && bundle.scanned !== MAX_SCANNED_ISSUES) fail("truncated scan must bind the full 1,000-issue bound");
  if (bundle.search_reason !== null && bundle.search_reason !== "no-distinctive-title-terms") fail("snapshot search reason is invalid");
  if (!bundle.search_performed && bundle.candidates.length > 0) fail("skipped candidate search cannot retain candidates");
  if (!exactKeys(bundle.target, ["receipt", "digest", "data"])) fail("snapshot target contains unexpected fields");
  assertReceipt(bundle.target.receipt, "target receipt");
  assertDigest(bundle.target.digest, "target digest");
  if (!Array.isArray(bundle.candidates) || bundle.candidates.length > MAX_CANDIDATES) fail("snapshot candidate count is invalid");
  const numbers = new Set();
  const receipts = new Set([bundle.target.receipt, bundle.trigger_receipt]);
  if (bundle.target.receipt === bundle.trigger_receipt) fail("snapshot receipts must be independent");
  for (const candidate of bundle.candidates) {
    validateCandidateMetadata(candidate, bundle.target_number);
    if (numbers.has(candidate.number)) fail("snapshot contains a duplicate candidate number");
    if (receipts.has(candidate.receipt)) fail("snapshot receipts must be independent");
    numbers.add(candidate.number);
    receipts.add(candidate.receipt);
  }
  if (bundle.comments !== null) {
    if (!exactKeys(bundle.comments, ["receipt", "digest", "count", "data"])) fail("snapshot comments contain unexpected fields");
    assertReceipt(bundle.comments.receipt, "comments receipt");
    assertDigest(bundle.comments.digest, "comments digest");
    if (receipts.has(bundle.comments.receipt)) fail("snapshot receipts must be independent");
    receipts.add(bundle.comments.receipt);
    if (!Number.isSafeInteger(bundle.comments.count) || bundle.comments.count < 0 || bundle.comments.count > MAX_TARGET_COMMENTS) fail("snapshot comment count is invalid");
  }

  if (bundle.status === "complete") {
    if (!bundle.content_persisted || bundle.sensitivity !== null || bundle.comments === null) fail("normal snapshot content flags are invalid");
    if (bundle.target.data === null || bundle.comments.data === null || bundle.candidates.some((candidate) => candidate.data === null)) fail("normal snapshot is missing evidence content");
    const target = normalizeIssue(bundle.target.data);
    if (target.number !== bundle.target_number || canonicalDigest(target) !== bundle.target.digest) fail("snapshot target digest does not match its content");
    if (!Array.isArray(bundle.comments.data) || bundle.comments.data.length !== bundle.comments.count) fail("snapshot comments do not match their count");
    const comments = bundle.comments.data.map(normalizeComment).sort((left, right) => left.id - right.id);
    if (canonicalDigest(comments) !== bundle.comments.digest) fail("snapshot comment digest does not match its content");
    for (const candidate of bundle.candidates) {
      const data = normalizeIssue(candidate.data);
      if (data.number !== candidate.number || data.state !== candidate.state || canonicalDigest(data) !== candidate.digest) fail(`snapshot candidate #${candidate.number} digest does not match its content`);
    }
    const inspection = inspectEvidence([
      ...issueTextItems(target, "target"),
      ...commentsTextItems(comments),
      ...bundle.candidates.flatMap((candidate) => issueTextItems(normalizeIssue(candidate.data), `candidate ${candidate.number}`)),
    ]);
    if (inspection.sensitive) fail("normal snapshot contains sensitive evidence");
  } else {
    if (bundle.content_persisted || !bundle.sensitivity || !SENSITIVE_SCOPES.has(bundle.sensitivity.scope)) fail("sensitive snapshot flags are invalid");
    if (!exactKeys(bundle.sensitivity, ["scope"])) fail("sensitive snapshot contains unexpected sensitivity metadata");
    if (
      bundle.target.data !== null ||
      (bundle.comments !== null && bundle.comments.data !== null) ||
      bundle.candidates.some((candidate) => candidate.data !== null)
    ) fail("sensitive snapshot must be metadata-only");
    if (bundle.sensitivity.scope === "target" && (bundle.comments !== null || bundle.candidates.length !== 0)) fail("target-sensitive snapshot must prove later evidence was not persisted");
    if (bundle.sensitivity.scope === "comments" && bundle.comments === null) fail("comment-sensitive snapshot requires the comment collection receipt");
  }
  return bundle;
}

/** Return the only bundle data allowed in Actions job outputs and the agent prompt header. */
export function createMetadataEnvelope(bundle) {
  validateBundle(bundle);
  return {
    version: bundle.version,
    status: bundle.status,
    strategy: bundle.strategy,
    repository: bundle.repository,
    run_id: bundle.run_id,
    workflow_sha: bundle.workflow_sha,
    target_number: bundle.target_number,
    run_kind: bundle.run_kind,
    trigger: bundle.trigger,
    trigger_receipt: bundle.trigger_receipt,
    initial_marker_count: bundle.initial_marker_count,
    continuation_count: bundle.continuation_count,
    needs_info_present: bundle.needs_info_present,
    scanned: bundle.scanned,
    scan_truncated: bundle.scan_truncated,
    search_performed: bundle.search_performed,
    search_reason: bundle.search_reason,
    sensitivity: bundle.sensitivity,
    target: {receipt: bundle.target.receipt, digest: bundle.target.digest},
    comments: bundle.comments && {
      receipt: bundle.comments.receipt,
      digest: bundle.comments.digest,
      count: bundle.comments.count,
    },
    candidates: bundle.candidates.map(({number, state, score, receipt, digest}) => ({
      number, state, score, receipt, digest,
    })),
  };
}

/**
 * Verify the artifact transport and the bundle's immutable internal bindings.
 */
export function verifyArtifactProvenance({
  bundle,
  expectedRepository,
  expectedRunId,
  expectedWorkflowSha,
  expectedTargetNumber,
  expectedArtifactId,
  artifactId,
  expectedActionDigest,
  actionDigest,
  expectedBundleDigest,
}) {
  validateBundle(bundle);
  if (bundle.repository !== expectedRepository) fail("artifact repository binding mismatch");
  if (bundle.run_id !== normalizeRunId(expectedRunId)) fail("artifact run_id binding mismatch");
  if (bundle.workflow_sha !== assertWorkflowSha(expectedWorkflowSha)) fail("artifact workflow_sha binding mismatch");
  if (bundle.target_number !== assertSafePositiveInteger(expectedTargetNumber, "expected target number")) fail("artifact target binding mismatch");
  const normalizedExpectedArtifactId = normalizeRunId(expectedArtifactId);
  if (normalizeRunId(artifactId) !== normalizedExpectedArtifactId) fail("artifact ID mismatch");
  const normalizedExpectedActionDigest = normalizeActionDigest(
    expectedActionDigest,
    "expected action artifact digest",
  );
  const normalizedActionDigest = normalizeActionDigest(
    actionDigest,
    "observed action artifact digest",
  );
  if (normalizedActionDigest !== normalizedExpectedActionDigest) fail("action artifact digest mismatch");
  assertDigest(expectedBundleDigest, "expected canonical bundle digest");
  if (canonicalDigest(bundle) !== expectedBundleDigest) fail("canonical bundle digest mismatch");
  return createMetadataEnvelope(bundle);
}

/** Re-fetch and compare every persisted evidence object immediately before safe outputs. */
export async function verifyFreshness({github, bundle, owner, repo}) {
  validateBundle(bundle);
  if (bundle.repository !== normalizeRepository(owner, repo)) fail("freshness repository binding mismatch");
  const target = await fetchIssue(github, owner, repo, bundle.target_number);
  inspectEvidence(issueTextItems(target, "target"));
  if (canonicalDigest(target) !== bundle.target.digest) fail("target evidence changed after the trusted snapshot");
  if (bundle.sensitivity?.scope === "target") return createMetadataEnvelope(bundle);

  const comments = await fetchBoundedComments(github, owner, repo, bundle.target_number);
  const timelineEvents = await fetchBoundedTimelineEvents(github, owner, repo, bundle.target_number);
  inspectEvidence([...issueTextItems(target, "target"), ...commentsTextItems(comments)]);
  if (bundle.comments === null || comments.length !== bundle.comments.count || canonicalDigest(comments) !== bundle.comments.digest) {
    fail("target comments changed after the trusted snapshot");
  }
  const eventComment = bundle.trigger.comment_id === null
    ? null
    : comments.find((comment) => comment.id === bundle.trigger.comment_id) || null;
  const eligibility = evaluateIntakeEligibility({
    eventName: bundle.trigger.event_name,
    action: bundle.trigger.action,
    actor: bundle.trigger.actor,
    issue: target,
    eventComment,
    comments,
    timelineEvents,
  });
  if (
    !eligibility.eligible || eligibility.run_kind !== bundle.run_kind ||
    eligibility.initial_marker_count !== bundle.initial_marker_count ||
    eligibility.continuation_count !== bundle.continuation_count ||
    eligibility.needs_info_present !== bundle.needs_info_present
  ) fail("trusted intake eligibility changed after the snapshot");
  if (bundle.sensitivity?.scope === "comments") return createMetadataEnvelope(bundle);

  const candidates = [];
  for (const candidate of bundle.candidates) {
    const current = await fetchIssue(github, owner, repo, candidate.number);
    if (current.state !== candidate.state || canonicalDigest(current) !== candidate.digest) {
      fail(`candidate #${candidate.number} changed after the trusted snapshot`);
    }
    candidates.push(current);
  }
  const inspection = inspectEvidence([
    ...issueTextItems(target, "target"),
    ...commentsTextItems(comments),
    ...candidates.flatMap((candidate) => issueTextItems(candidate, `candidate ${candidate.number}`)),
  ]);
  if (bundle.status === "complete" && inspection.sensitive) fail("fresh evidence now contains sensitive content");
  return createMetadataEnvelope(bundle);
}

function normalizeReason(value) {
  if (typeof value !== "string") fail("relationship reason must be a string");
  const normalized = value
    .normalize("NFKC")
    .replace(/\p{Default_Ignorable_Code_Point}/gu, "")
    .replace(/[\p{C}\p{Zl}\p{Zp}]/gu, "")
    .replace(/\s+/gu, " ")
    .trim();
  if (normalized !== value) fail("relationship reason must already be normalized");
  const length = [...normalized].length;
  if (length < 20 || length > 240 || !/[\p{L}\p{N}]/u.test(normalized)) fail("relationship reason must contain 20 to 240 safe visible characters");
  if (/[<>@#]/u.test(normalized) || /https?:\/\//iu.test(normalized) || containsSensitiveContent(normalized)) fail("relationship reason contains unsafe syntax");
  return normalized;
}

function validateRelationships(value, bundle) {
  if (!Array.isArray(value) || value.length !== bundle.candidates.length) fail("relationships must cover every candidate exactly once");
  return value.map((relationship, index) => {
    if (!exactKeys(relationship, ["candidate_number", "candidate_receipt", "verdict", "reason"])) fail("relationship contains unexpected fields or field order");
    const candidate = bundle.candidates[index];
    if (relationship.candidate_number !== candidate.number || relationship.candidate_receipt !== candidate.receipt) fail("relationship candidate order or receipt binding mismatch");
    if (!VERDICTS.has(relationship.verdict)) fail("relationship verdict is invalid");
    return {...relationship, reason: normalizeReason(relationship.reason)};
  });
}

function validateDecision(decision, expectedKind) {
  if (!decision || typeof decision !== "object" || Array.isArray(decision) || typeof decision.kind !== "string") fail("proposal decision is invalid");
  if (expectedKind && decision.kind !== expectedKind) fail(`proposal carrier requires a ${expectedKind} decision`);
  if (decision.kind === "missing_information") {
    if (!exactKeys(decision, ["kind", "fields"])) fail(`${decision.kind} decision contains unexpected fields`);
    if (!Array.isArray(decision.fields) || decision.fields.length < 1 || decision.fields.length > 3 || new Set(decision.fields).size !== decision.fields.length || !decision.fields.every((field) => MISSING_INFORMATION_FIELDS.has(field))) {
      fail(`${decision.kind} decision requires 1 to 3 unique allowlisted fields`);
    }
    return decision;
  }
  if (decision.kind === "repository_evidence") {
    if (!exactKeys(decision, ["kind", "path", "quote"])) fail("repository_evidence decision contains unexpected fields");
    if (typeof decision.path !== "string" || !REPOSITORY_EVIDENCE_PATHS.some((pattern) => pattern.test(decision.path))) fail("repository_evidence path is outside the allowlist");
    if (
      typeof decision.quote !== "string" ||
      decision.quote.trim() !== decision.quote ||
      [...decision.quote].length < 20 ||
      [...decision.quote].length > 600 ||
      decision.quote.split("\n").length > 6 ||
      /[\u0000-\u0009\u000b-\u001f\u007f-\u009f\u2028\u2029]/u.test(decision.quote) ||
      containsSensitiveContent(decision.quote)
    ) fail("repository_evidence quote must be 20 to 600 safe characters across at most 6 lines");
    return decision;
  }
  if (decision.kind === "ready_for_maintainer") {
    if (!exactKeys(decision, ["kind"])) fail("ready_for_maintainer decision contains unexpected fields");
    return decision;
  }
  if (decision.kind === "noop") {
    if (!exactKeys(decision, ["kind"])) fail("noop decision contains unexpected fields");
    return decision;
  }
  fail("proposal decision kind is invalid");
}

function relationshipText(relationships) {
  return relationships.slice(0, 1).map(
    (relationship) => `Candidate #${relationship.candidate_number}: ${relationship.verdict} — ${relationship.reason}`,
  );
}

function renderDecision(decision, relationships, runKind = "initial") {
  let body;
  if (decision.kind === "missing_information") {
    body = "To make this report actionable, please provide:\n\n" + decision.fields.map((field) => `- ${MISSING_INFORMATION_TEXT.get(field)}`).join("\n");
  } else if (decision.kind === "repository_evidence") {
    body = `Repository evidence (${decision.path}):\n\n> ${decision.quote}`;
  } else if (decision.kind === "ready_for_maintainer") {
    body = "Thanks for the report. This automated first pass found enough information for maintainer review.";
  } else {
    body = "No public triage action is proposed by this first pass.";
  }
  const assessments = relationshipText(relationships);
  if (assessments.length > 0) body += `\n\n${assessments.join("\n")}`;
  if (decision.kind === "missing_information" || decision.kind === "repository_evidence" || decision.kind === "ready_for_maintainer") {
    body += `\n\n${COMMENT_FOOTER}`;
    body += `\n\n${runKind === "continuation" ? CONTINUATION_MARKER : INITIAL_MARKER}`;
  }
  return body;
}

function validateLabelIntents(value, allowEmpty = false) {
  if (!Array.isArray(value) || value.length > 4 || (!allowEmpty && value.length < 1)) fail("label_intents must contain one to four labels");
  const names = new Set();
  return value.map((intent) => {
    if (!exactKeys(intent, ["name", "rationale", "confidence"])) fail("label intent contains unexpected fields");
    if (!ALLOWED_LABELS.has(intent.name) || names.has(intent.name)) fail("label intents must be unique and allowlisted");
    names.add(intent.name);
    const rationale = normalizeReason(intent.rationale);
    if (!new Set(["LOW", "MEDIUM", "HIGH"]).has(intent.confidence)) fail("label intent confidence is invalid");
    return {...intent, rationale};
  });
}

function parseCanonicalCarrier(carrier) {
  if (typeof carrier !== "string" || carrier === "") fail("proposal carrier must be a nonempty canonical JSON string");
  let proposal;
  try {
    proposal = JSON.parse(carrier);
  } catch {
    fail("proposal carrier must be canonical JSON");
  }
  if (canonicalStringify(proposal) !== carrier) fail("proposal carrier must use canonical key ordering and encoding");
  return proposal;
}

export function validateSensitiveProposal({carrier, bundle}) {
  validateBundle(bundle);
  if (bundle.status !== "sensitive_stop") fail("sensitive proposal requires a trusted sensitive-stop bundle");
  const proposal = parseCanonicalCarrier(carrier);
  const scope = bundle.sensitivity.scope;
  if (scope === "target") {
    if (!exactKeys(proposal, ["kind", "target_receipt", "version"])) fail("target-sensitive proposal contains unexpected fields");
  } else if (scope === "comments") {
    if (!exactKeys(proposal, ["comments_receipt", "kind", "target_receipt", "version"])) fail("comment-sensitive proposal contains unexpected fields");
  } else {
    if (!exactKeys(proposal, ["candidate_receipts", "comments_receipt", "kind", "target_receipt", "version"])) fail("candidate-sensitive proposal contains unexpected fields");
  }
  if (proposal.version !== CONTRACT_VERSION || proposal.kind !== "sensitive_stop" || proposal.target_receipt !== bundle.target.receipt) fail("sensitive proposal target binding mismatch");
  if (scope !== "target" && proposal.comments_receipt !== bundle.comments?.receipt) fail("sensitive proposal comment binding mismatch");
  if (scope === "candidate") {
    if (!Array.isArray(proposal.candidate_receipts) || proposal.candidate_receipts.length !== bundle.candidates.length || proposal.candidate_receipts.some((receipt, index) => receipt !== bundle.candidates[index].receipt)) fail("sensitive proposal candidate receipt binding mismatch");
  }
  return {proposal, rendered: "Sensitive intake stop: Maintainer attention is required.", relationships: []};
}

/** Validate the sole canonical carrier and return text rendered entirely by trusted code. */
export function validateAndRenderProposal({carrier, bundle, expectedDecisionKind}) {
  validateBundle(bundle);
  if (bundle.status === "sensitive_stop") return validateSensitiveProposal({carrier, bundle});
  const proposal = parseCanonicalCarrier(carrier);
  if (!exactKeys(proposal, ["comments_receipt", "decision", "kind", "label_intents", "relationships", "run_kind", "target_receipt", "trigger_receipt", "version"])) fail("normal proposal contains unexpected fields or field order");
  if (proposal.version !== CONTRACT_VERSION || proposal.kind !== "triage_proposal") fail("normal proposal version or kind is invalid");
  if (proposal.target_receipt !== bundle.target.receipt || proposal.comments_receipt !== bundle.comments.receipt || proposal.trigger_receipt !== bundle.trigger_receipt || proposal.run_kind !== bundle.run_kind) fail("normal proposal intake binding mismatch");
  const relationships = validateRelationships(proposal.relationships, bundle);
  const decision = validateDecision(proposal.decision, expectedDecisionKind);
  const labelIntents = validateLabelIntents(proposal.label_intents, true);
  if (bundle.run_kind === "initial" && !new Set(["ready_for_maintainer", "missing_information", "repository_evidence"]).has(decision.kind)) fail("initial decision is not allowlisted");
  if (bundle.run_kind === "continuation" && decision.kind !== "missing_information") fail("incomplete continuation must request missing information");
  if (bundle.run_kind === "initial") {
    const hasNeedsInfo = labelIntents.some(({name}) => name === "needs-info");
    if (decision.kind === "missing_information" && !hasNeedsInfo) fail("missing-information initial triage requires needs-info");
    if (decision.kind !== "missing_information" && hasNeedsInfo) fail("needs-info is valid only for missing-information initial triage");
  }
  rejectRelationshipSemanticsOutsideCarrier(decision, bundle, labelIntents);
  return {proposal: {...proposal, label_intents: labelIntents, relationships, decision}, rendered: renderDecision(decision, relationships, bundle.run_kind), relationships};
}

/** Select the one designated carrier: label rationale, else comment body, else noop message. */
export function selectProposalCarrier(items) {
  if (!Array.isArray(items) || items.length === 0) fail("agent output must contain at least one item");
  const normalized = items.map((item, index) => ({
    item,
    index,
    type: typeof item?.type === "string" ? item.type.toLowerCase().replaceAll("-", "_") : "",
  }));
  const labels = normalized.filter(({type}) => type === "add_labels");
  const comments = normalized.filter(({type}) => type === "add_comment");
  const noops = normalized.filter(({type}) => type === "noop");
  if (labels.length > 1 || comments.length > 1 || noops.length > 1) fail("agent output contains duplicate proposal types");
  if (comments.length > 0) {
    if (typeof comments[0].item?.body !== "string") fail("comment proposal carrier is invalid");
    return {type: "comment", raw: comments[0].item.body, expectedDecisionKind: null, itemIndex: comments[0].index};
  }
  if (noops.length > 0) {
    if (typeof noops[0].item?.message !== "string") fail("noop proposal carrier is invalid");
    return {type: "noop", raw: noops[0].item.message, expectedDecisionKind: "noop", itemIndex: noops[0].index};
  }
  fail("agent output has no designated proposal carrier");
}

export function escapeHtml(value) {
  return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

/** Validate and replace the designated carrier in a copy of the safe-output document. */
export function validateAndRenderAgentOutput(args) {
  return validateAndRewriteAgentOutput(args);
}

function normalizePolicyText(text) {
  return text
    .normalize("NFKC")
    .replace(/\p{Default_Ignorable_Code_Point}/gu, "")
    .replace(/\s/gu, " ")
    .replace(/\p{C}/gu, "")
    .replace(/\p{Z}/gu, " ")
    .replace(/ +/g, " ");
}

function inspectRenderedText(value, bundle) {
  const violations = [];
  const normalized = normalizePolicyText(value);
  const trustedNumbers = new Set([bundle.target_number, ...bundle.candidates.map(({number}) => number)]);
  const referenced = new Set();
  for (const match of normalized.matchAll(/(^|[^A-Za-z0-9_])#\s*(\d+)\b/g)) referenced.add(Number(match[2]));
  for (const match of normalized.matchAll(/\bissue\s*(?:(?:number|num(?:ber)?|no)\.?\s*)?:?\s*#?\s*(\d+)\b/gi)) referenced.add(Number(match[1]));
  for (const match of normalized.matchAll(/\bGH\s*-\s*(\d+)\b/gi)) referenced.add(Number(match[1]));
  for (const match of normalized.matchAll(/(^|[^A-Za-z0-9_.-])([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)#(\d+)\b/gi)) {
    const repository = `${match[2]}/${match[3]}`.toLowerCase();
    if (repository !== bundle.repository.toLowerCase()) {
      violations.push("cross-repository reference is not allowed");
    } else {
      referenced.add(Number(match[4]));
    }
  }
  for (const match of normalized.matchAll(/(^|[^A-Za-z0-9_.-])([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)\/(issues|pull)\/(\d+)\b/gi)) {
    const repository = `${match[2]}/${match[3]}`.toLowerCase();
    if (repository !== bundle.repository.toLowerCase()) {
      violations.push("cross-repository reference is not allowed");
    } else if (match[4].toLowerCase() === "pull") {
      violations.push("numbered pull-request reference is not allowed");
    } else {
      referenced.add(Number(match[5]));
    }
  }
  if (/\b(?:PRs?|pull[\s-]+requests?)\s*(?:(?:number|num(?:ber)?|no)\.?\s*)?:?\s*#?\s*\d+\b/i.test(normalized)) violations.push("numbered pull-request reference is not allowed");
  if (/(^|[^A-Za-z0-9_])@[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\b/.test(value)) violations.push("user or bot mention is not allowed");
  if (/\[[^\]]+\]\s*(?:\([^)]*\)|\[[^\]]*\])/.test(value) || /<(?:a\s|[^>]+\shref\s*=)/i.test(value)) violations.push("agent-authored link syntax is not allowed");
  if (/\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?[ \t]*#\d+\b/i.test(normalized)) violations.push("closing keyword is not allowed");
  if (containsSensitiveContent(value)) violations.push("sensitive content is not allowed");
  for (const match of value.matchAll(/https?:\/\/[^\s<>"'`]+/gi)) {
    const raw = match[0].replace(/[),.;!?]+$/, "");
    let url;
    try {
      url = new URL(raw);
    } catch {
      violations.push("malformed URL");
      continue;
    }
    const prefix = `/${bundle.repository.toLowerCase()}`;
    let repositoryPath;
    try {
      repositoryPath = decodeURIComponent(url.pathname).toLowerCase();
    } catch {
      violations.push("malformed URL path");
      continue;
    }
    if (url.protocol !== "https:" || url.hostname.toLowerCase() !== "github.com" || !repositoryPath.startsWith(`${prefix}/`)) {
      violations.push("URL outside the canonical repository");
      continue;
    }
    const relativePath = repositoryPath.slice(prefix.length);
    const issueMatch = relativePath.match(/^\/issues\/(\d+)(?:\/|$)/);
    const pullMatch = relativePath.match(/^\/pull\/(\d+)(?:\/|$)/);
    if (issueMatch) referenced.add(Number(issueMatch[1]));
    if (pullMatch) violations.push("numbered pull-request reference is not allowed");
  }
  for (const number of referenced) if (!trustedNumbers.has(number)) violations.push("issue reference outside trusted evidence");
  if (violations.length > 0) fail([...new Set(violations)].join(", "));
}

/** Render only trusted candidate-search metadata for the maintainer summary. */
export function summarizeCandidateResearch(bundle) {
  validateBundle(bundle);
  if (!bundle.search_performed) {
    return bundle.status === "sensitive_stop"
      ? "Candidate research was skipped because sensitive intake was detected before search."
      : "Candidate research was skipped because the target title had no distinctive search terms.";
  }
  if (bundle.candidates.length === 0) return "No lexical candidates met the deterministic threshold.";
  return bundle.candidates.map((candidate) => `- #${candidate.number} (score ${candidate.score})`).join("\n");
}

async function renderRepositoryEvidence(decision, bundle, fetchRepositoryFile) {
  if (typeof fetchRepositoryFile !== "function") fail("repository evidence requires the trusted immutable Contents API callback");
  const fetched = await fetchRepositoryFile(decision.path);
  const content = typeof fetched === "string" ? fetched : fetched?.content;
  if (typeof content !== "string") fail("trusted repository evidence callback returned invalid content");
  if (Buffer.byteLength(content, "utf8") > MAX_RAW_EVIDENCE_BYTES) fail("repository evidence file exceeds the trusted size limit");
  const firstMatch = content.indexOf(decision.quote);
  const secondMatch = firstMatch < 0 ? -1 : content.indexOf(decision.quote, firstMatch + 1);
  if (firstMatch < 0 || secondMatch >= 0) fail("repository evidence quote must have one unique contiguous match");
  const startLine = content.slice(0, firstMatch).split("\n").length;
  const endLine = startLine + decision.quote.split("\n").length - 1;
  const path = decision.path.split("/").map(encodeURIComponent).join("/");
  const sourceUrl = `https://github.com/${bundle.repository}/blob/${bundle.workflow_sha}/${path}#L${startLine}-L${endLine}`;
  return (
    "The repository source currently states:\n\n" +
    decision.quote.split("\n").map((line) => `> ${line}`).join("\n") +
    `\n\nSource: ${sourceUrl}`
  );
}

function appendRelationshipsAndFooter(body, decision, relationships, runKind) {
  const assessments = relationshipText(relationships);
  let rendered = body;
  if (assessments.length > 0) rendered += `\n\n${assessments.join("\n")}`;
  if (decision.kind === "missing_information" || decision.kind === "repository_evidence") {
    rendered += `\n\n${COMMENT_FOOTER}`;
    rendered += `\n\n${runKind === "continuation" ? CONTINUATION_MARKER : INITIAL_MARKER}`;
  }
  return rendered;
}

async function renderVerifiedDecision(decision, relationships, bundle, fetchRepositoryFile) {
  if (decision.kind !== "repository_evidence") return renderDecision(decision, relationships, bundle.run_kind);
  const evidence = await renderRepositoryEvidence(decision, bundle, fetchRepositoryFile);
  return appendRelationshipsAndFooter(evidence, decision, relationships, bundle.run_kind);
}

function rejectRelationshipSemanticsOutsideCarrier(decision, bundle, labelIntents = []) {
  const values = [];
  if (typeof decision.quote === "string") values.push(decision.quote);
  if (typeof decision.reason === "string") values.push(decision.reason);
  for (const intent of labelIntents) {
    if (typeof intent?.rationale === "string") values.push(intent.rationale);
  }
  for (const value of values) {
    const normalized = normalizePolicyText(value);
    if (
      /\b(?:lexical|candidate|duplicate)\s+(?:issue|report|result|search|match|relationship)s?\b/iu.test(normalized) ||
      /\b(?:search(?:ed|ing)?|match(?:ed|es|ing)?|similar|related|overlap(?:ped|s|ping)?)\s+(?:to|with|for)?\s*(?:a\s+|the\s+)?(?:prior|previous|earlier|existing|candidate|other)\s+(?:issue|problem|report)\b/iu.test(normalized) ||
      /\b(?:same|duplicate(?:s|d)?)\s+(?:issue|problem|report)\b/iu.test(normalized) ||
      normalized.includes(bundle.target.receipt) ||
      (bundle.comments && normalized.includes(bundle.comments.receipt)) ||
      bundle.candidates.some(
        (candidate) =>
          normalized.includes(candidate.receipt) ||
          new RegExp(`(?:#\\s*|candidate\\s*#?\\s*)${candidate.number}\\b`, "i").test(normalized),
      )
    ) fail("relationship or search semantics are allowed only in the designated carrier");
  }
}

/**
 * Full safe-output boundary used by the workflow's trusted final job.
 *
 * It validates the entire item collection, verifies repository quotes via the injected
 * immutable Contents API callback, replaces every proposal JSON string with trusted
 * prose, and returns only HTML-escaped summary fields.
 */
export async function validateAndRewriteAgentOutput({
  output,
  bundle,
  fetchRepositoryFile,
  targetNumber = bundle?.target_number,
}) {
  validateBundle(bundle);
  if (targetNumber !== bundle.target_number) fail("trusted safe-output target binding mismatch");
  if (!output || typeof output !== "object" || Array.isArray(output)) fail("agent output must be an object");
  const outputKeys = Object.keys(output);
  if (!outputKeys.every((key) => key === "items" || key === "errors") || !outputKeys.includes("items")) fail("agent output contains unexpected fields");
  if (Object.prototype.hasOwnProperty.call(output, "errors") && (!Array.isArray(output.errors) || output.errors.length > 0)) fail("safe-output collection errors are not allowed");
  if (!Array.isArray(output.items) || output.items.length < 1 || output.items.length > 2) fail("agent output must contain one or two bounded items");

  const trustedOutput = structuredClone(output);
  if (
    bundle.status === "complete" && bundle.run_kind === "continuation" &&
    trustedOutput.items.length === 1 &&
    String(trustedOutput.items[0]?.type || "").toLowerCase().replaceAll("-", "_") === "noop"
  ) {
    const completion = trustedOutput.items[0];
    completion.type = "noop";
    if (!exactKeys(completion, ["type", "message"])) {
      fail("complete continuation must use exactly one receipt-bound noop");
    }
    const proposal = parseCanonicalCarrier(completion.message);
    if (!exactKeys(proposal, ["kind", "target_receipt", "trigger_receipt", "version"])) {
      fail("complete continuation proposal contains unexpected fields");
    }
    if (
      proposal.version !== CONTRACT_VERSION ||
      proposal.kind !== "complete_continuation" ||
      proposal.target_receipt !== bundle.target.receipt ||
      proposal.trigger_receipt !== bundle.trigger_receipt
    ) fail("complete continuation receipt binding mismatch");
    if (!bundle.needs_info_present) fail("complete continuation requires a trusted needs-info label");
    completion.message = "The reporter supplied the requested information; needs-info will be removed.";
    return {
      output: trustedOutput,
      carrier: "completion",
      proposal: null,
      summary: {
        heading_html: "Trusted complete continuation",
        rendered_html: ["The reporter supplied the requested information; needs-info will be removed."],
        relationships: [],
      },
    };
  }

  const counts = new Map();
  for (const item of trustedOutput.items) {
    if (!item || typeof item !== "object" || Array.isArray(item)) fail("safe-output item must be an object");
    const type = typeof item.type === "string" ? item.type.toLowerCase().replaceAll("-", "_") : "";
    if (!new Set(["add_comment", "add_labels", "noop"]).has(type)) fail("unsupported safe-output type");
    counts.set(type, (counts.get(type) || 0) + 1);
    if (counts.get(type) > 1) fail("duplicate safe-output type");
    item.type = type;
    if (type === "add_comment") {
      if (!Object.keys(item).every((key) => ["type", "body", "temporary_id"].includes(key)) || !Object.hasOwn(item, "body")) fail("add_comment contains unexpected fields");
      if (typeof item.body !== "string" || item.body === "") fail("add_comment requires a proposal body");
      if (Object.hasOwn(item, "temporary_id") && (typeof item.temporary_id !== "string" || !/^#?aw_[A-Za-z0-9_]{3,12}$/.test(item.temporary_id))) fail("add_comment temporary_id is invalid");
    } else if (type === "add_labels") {
      if (!exactKeys(item, ["type", "labels"]) || !Array.isArray(item.labels) || item.labels.length < 1 || item.labels.length > 4) fail("add_labels requires one to four label intents");
      item.labels = validateLabelIntents(item.labels);
    } else {
      if (!exactKeys(item, ["type", "message"]) || typeof item.message !== "string" || item.message === "") fail("noop requires exactly one proposal message");
    }
  }
  if ((counts.get("noop") || 0) > 0 && trustedOutput.items.length !== 1) fail("noop must be exclusive from action outputs");
  if (bundle.status === "sensitive_stop" && ((counts.get("noop") || 0) !== 1 || trustedOutput.items.length !== 1)) fail("sensitive evidence requires the exact exclusive noop shape");
  if (bundle.status === "complete") {
    if ((counts.get("noop") || 0) !== 0) fail("normal automatic triage must produce an actionable bounded result");
    if ((counts.get("add_comment") || 0) !== 1) fail("normal automatic triage requires exactly one trusted comment carrier");
    if (bundle.run_kind === "initial" && (counts.get("add_labels") || 0) > 1) fail("initial triage allows at most one bounded label collection");
    if (bundle.run_kind === "continuation" && (counts.get("add_labels") || 0) !== 0) fail("incomplete continuation must not add labels");
  }

  const carrier = selectProposalCarrier(trustedOutput.items);
  const validated = validateAndRenderProposal({carrier: carrier.raw, bundle, expectedDecisionKind: carrier.expectedDecisionKind});
  const labelsItem = trustedOutput.items.find((item) => item.type === "add_labels");
  const outputLabelIntents = labelsItem?.labels || [];
  if (canonicalStringify(outputLabelIntents) !== canonicalStringify(validated.proposal.label_intents || [])) fail("proposal label intents do not exactly match add_labels output");
  if (bundle.status === "complete" && bundle.run_kind === "initial") {
    const hasNeedsInfo = validated.proposal.label_intents.some(({name}) => name === "needs-info");
    if (validated.proposal.decision.kind === "missing_information" && !hasNeedsInfo) fail("missing-information initial triage requires needs-info");
    if (validated.proposal.decision.kind !== "missing_information" && hasNeedsInfo) fail("needs-info is valid only for missing-information initial triage");
  }
  if (bundle.status === "complete") {
    validated.rendered = await renderVerifiedDecision(
      validated.proposal.decision,
      validated.relationships,
      bundle,
      fetchRepositoryFile,
    );
  }
  const carrierItem = trustedOutput.items[carrier.itemIndex];
  if (carrier.type === "comment") carrierItem.body = validated.rendered;
  if (carrier.type === "noop") carrierItem.message = validated.rendered;

  if (labelsItem) {
    labelsItem.item_number = targetNumber;
    for (const label of labelsItem.labels) label.suggest = true;
  }

  const renderedStrings = [];
  for (const item of trustedOutput.items) {
    if (item.type === "add_comment") renderedStrings.push(item.body);
    if (item.type === "add_labels") renderedStrings.push(...item.labels.map(({rationale}) => rationale));
    if (item.type === "noop") renderedStrings.push(item.message);
  }
  for (const value of renderedStrings) inspectRenderedText(value, bundle);
  const escapedRendered = renderedStrings.map(escapeHtml);
  return {
    output: trustedOutput,
    carrier: carrier.type,
    proposal: validated.proposal,
    summary: {
      heading_html: "Trusted rendered proposal",
      rendered_html: escapedRendered,
      relationships: validated.relationships.map(({candidate_number, verdict, reason}) => ({
        candidate_number,
        verdict_html: escapeHtml(verdict),
        reason_html: escapeHtml(reason),
      })),
    },
  };
}

async function readJson(path, name) {
  if (typeof path !== "string" || path === "") fail(`${name} path is required`);
  try {
    return JSON.parse(await readFile(path, "utf8"));
  } catch {
    fail(`${name} must be a readable JSON file`);
  }
}

function parseArgs(argv) {
  const [command, ...rest] = argv;
  const options = new Map();
  for (let index = 0; index < rest.length; index += 2) {
    const flag = rest[index];
    const value = rest[index + 1];
    if (!/^--[a-z-]+$/.test(flag || "") || typeof value !== "string") fail("CLI options must be --name path pairs");
    if (options.has(flag)) fail(`duplicate CLI option ${flag}`);
    options.set(flag, value);
  }
  return {command, options};
}

async function cli(argv) {
  const {command, options} = parseArgs(argv);
  if (command === "digest") {
    const input = await readJson(options.get("--input"), "input");
    const output = options.get("--output");
    if (!output) fail("--output path is required");
    await writeFile(output, `${canonicalDigest(input)}\n`, {encoding: "utf8", mode: 0o600});
    return;
  }
  if (command === "verify-artifact") {
    const bundle = await readJson(options.get("--bundle"), "bundle");
    const request = await readJson(options.get("--request"), "request");
    const output = options.get("--output");
    if (!output) fail("--output path is required");
    if (!exactKeys(request, ["actual", "expected"]) || !exactKeys(request.actual, ["action_digest", "artifact_id"]) || !exactKeys(request.expected, ["action_digest", "artifact_id", "bundle_digest", "repository", "run_id", "target_number", "workflow_sha"])) fail("artifact verification request is invalid");
    const envelope = verifyArtifactProvenance({
      bundle,
      expectedRepository: request.expected.repository,
      expectedRunId: request.expected.run_id,
      expectedWorkflowSha: request.expected.workflow_sha,
      expectedTargetNumber: request.expected.target_number,
      expectedArtifactId: request.expected.artifact_id,
      artifactId: request.actual.artifact_id,
      expectedActionDigest: request.expected.action_digest,
      actionDigest: request.actual.action_digest,
      expectedBundleDigest: request.expected.bundle_digest,
    });
    await writeFile(output, canonicalStringify(envelope), {encoding: "utf8", mode: 0o600});
    return;
  }
  if (command === "validate-proposal") {
    const bundle = await readJson(options.get("--bundle"), "bundle");
    const input = await readJson(options.get("--input"), "input");
    const outputPath = options.get("--output");
    const summaryPath = options.get("--summary-output");
    if (!outputPath || !summaryPath) fail("--output and --summary-output paths are required");
    const result = await validateAndRewriteAgentOutput({output: input, bundle});
    await writeFile(outputPath, canonicalStringify(result.output), {encoding: "utf8", mode: 0o600});
    const summary =
      `<h3>${result.summary.heading_html}</h3>\n` +
      result.summary.rendered_html.map((value) => `<pre>${value}</pre>`).join("\n");
    await writeFile(summaryPath, summary, {encoding: "utf8", mode: 0o600});
    return;
  }
  fail("supported commands: digest, verify-artifact, validate-proposal");
}

const invokedPath = process.argv[1] ? pathToFileURL(process.argv[1]).href : null;
if (invokedPath === import.meta.url) {
  cli(process.argv.slice(2)).catch((error) => {
    console.error(error instanceof Error ? error.message : "community triage contract failed");
    process.exitCode = 1;
  });
}
