#!/usr/bin/env node

/**
 * Trusted contract helpers for the community issue triage workflow.
 *
 * Contributor-controlled text is accepted only through the injected GitHub client or
 * files.  The CLI deliberately accepts paths, never raw issue content in argv or env.
 */

import {createHash, randomBytes as cryptoRandomBytes} from "node:crypto";
import {readFile, writeFile} from "node:fs/promises";
import {pathToFileURL} from "node:url";

export const CONTRACT_VERSION = 2;
export const SNAPSHOT_STRATEGY = "bounded-title-lexical-v2";
export const MAX_TARGET_COMMENTS = 100;
export const MAX_CANDIDATES = 5;
export const MAX_SCANNED_ISSUES = 1000;
export const MAX_TEXT_ITEM_BYTES = 256 * 1024;
export const MAX_RAW_EVIDENCE_BYTES = 1024 * 1024;

const RECEIPT_PATTERN = /^[a-f0-9]{32}$/;
const SHA_PATTERN = /^[a-f0-9]{40}$/i;
const DIGEST_PATTERN = /^[a-f0-9]{64}$/;
const POSITIVE_INTEGER_STRING_PATTERN = /^[1-9][0-9]*$/;
const VERDICTS = new Set(["RELATED", "NOT_RELATED", "UNCERTAIN"]);
const SENSITIVE_SCOPES = new Set(["target", "comments", "candidate"]);
const SECRET_PATTERNS = [
  /github_pat_[A-Za-z0-9_]{20,}/,
  /gh[pousr]_[A-Za-z0-9]{20,}/,
  /AKIA[0-9A-Z]{16}/,
  /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/,
  /\b(?:authorization|api[_ -]?key|token|secret|password)\s*[:=]\s*["']?[A-Za-z0-9_./+=-]{16,}/i,
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
  /^(?:docs|apps|packages)\/[A-Za-z0-9][A-Za-z0-9._-]*(?:\/[A-Za-z0-9][A-Za-z0-9._-]*)*\.md$/,
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

function containsSecret(value) {
  return SECRET_PATTERNS.some((pattern) => pattern.test(value));
}

function normalizeAuthor(value) {
  if (typeof value === "string") return value;
  const login = value?.login;
  return typeof login === "string" ? login : null;
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
    sensitive = sensitive || containsSecret(item.value);
  }
  if (totalBytes > MAX_RAW_EVIDENCE_BYTES) {
    fail(`raw evidence exceeds the ${MAX_RAW_EVIDENCE_BYTES}-byte aggregate limit`);
  }
  return {totalBytes, sensitive};
}

function baseBundle({repository, runId, workflowSha, targetNumber, targetReceipt, targetDigest}) {
  return {
    version: CONTRACT_VERSION,
    status: "complete",
    strategy: SNAPSHOT_STRATEGY,
    repository,
    run_id: runId,
    workflow_sha: workflowSha,
    target_number: targetNumber,
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
 * Build the trusted v2 artifact bundle using an injected Octokit-like client.
 */
export async function createTrustedSnapshot({
  github,
  owner,
  repo,
  targetNumber,
  runId,
  workflowSha,
  randomBytes,
}) {
  if (!github?.rest?.issues?.get || !github?.rest?.issues?.listComments || !github?.graphql) {
    fail("createTrustedSnapshot requires an injected GitHub issue and GraphQL client");
  }
  assertSafePositiveInteger(targetNumber, "targetNumber");
  const repository = normalizeRepository(owner, repo);
  const normalizedRunId = normalizeRunId(runId);
  const normalizedWorkflowSha = assertWorkflowSha(workflowSha);
  const nextReceipt = receiptFactory(randomBytes);

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
  });
  const targetInspection = inspectEvidence(issueTextItems(target, "target"));
  if (targetInspection.sensitive) return snapshotResult(sensitiveBundle(bundle, "target"));

  const comments = await fetchBoundedComments(github, owner, repo, targetNumber);
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
    "target_number", "scanned", "scan_truncated", "search_performed", "search_reason",
    "content_persisted", "sensitivity", "target", "comments", "candidates",
  ])) fail("snapshot bundle contains unexpected fields or field order");
  if (bundle.version !== CONTRACT_VERSION || bundle.strategy !== SNAPSHOT_STRATEGY) fail("snapshot bundle version or strategy is invalid");
  if (bundle.status !== "complete" && bundle.status !== "sensitive_stop") fail("snapshot bundle status is invalid");
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(bundle.repository)) fail("snapshot repository binding is invalid");
  normalizeRunId(bundle.run_id);
  assertWorkflowSha(bundle.workflow_sha);
  assertSafePositiveInteger(bundle.target_number, "snapshot target number");
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
  const receipts = new Set([bundle.target.receipt]);
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
    if (inspection.sensitive) fail("normal snapshot contains secret-like evidence");
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
  inspectEvidence([...issueTextItems(target, "target"), ...commentsTextItems(comments)]);
  if (bundle.comments === null || comments.length !== bundle.comments.count || canonicalDigest(comments) !== bundle.comments.digest) {
    fail("target comments changed after the trusted snapshot");
  }
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
  if (bundle.status === "complete" && inspection.sensitive) fail("fresh evidence now contains secret-like content");
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
  if (/[<>@#]/u.test(normalized) || /https?:\/\//iu.test(normalized) || containsSecret(normalized)) fail("relationship reason contains unsafe syntax");
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
  if (decision.kind === "needs_info" || decision.kind === "missing_information") {
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
      containsSecret(decision.quote)
    ) fail("repository_evidence quote must be 20 to 600 safe characters across at most 6 lines");
    return decision;
  }
  if (decision.kind === "noop") {
    if (!exactKeys(decision, ["kind", "reason"])) fail("noop decision contains unexpected fields");
    return {...decision, reason: normalizeReason(decision.reason)};
  }
  fail("proposal decision kind is invalid");
}

function relationshipText(relationships) {
  return relationships.slice(0, 1).map(
    (relationship) => `Candidate #${relationship.candidate_number}: ${relationship.verdict} — ${relationship.reason}`,
  );
}

function renderDecision(decision, relationships) {
  let body;
  if (decision.kind === "needs_info") {
    body = `Required diagnostic information is missing: ${decision.fields.map((field) => MISSING_INFORMATION_TEXT.get(field)).join(" ")}`;
  } else if (decision.kind === "missing_information") {
    body = "To make this report actionable, please provide:\n\n" + decision.fields.map((field) => `- ${MISSING_INFORMATION_TEXT.get(field)}`).join("\n");
  } else if (decision.kind === "repository_evidence") {
    body = `Repository evidence (${decision.path}):\n\n> ${decision.quote}`;
  } else {
    body = decision.reason;
  }
  const assessments = relationshipText(relationships);
  if (assessments.length > 0) body += `\n\n${assessments.join("\n")}`;
  if (decision.kind === "missing_information" || decision.kind === "repository_evidence") body += `\n\n${COMMENT_FOOTER}`;
  return body;
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
  if (!exactKeys(proposal, ["comments_receipt", "decision", "kind", "relationships", "target_receipt", "version"])) fail("normal proposal contains unexpected fields or field order");
  if (proposal.version !== CONTRACT_VERSION || proposal.kind !== "triage_proposal") fail("normal proposal version or kind is invalid");
  if (proposal.target_receipt !== bundle.target.receipt || proposal.comments_receipt !== bundle.comments.receipt) fail("normal proposal target or comment receipt binding mismatch");
  const relationships = validateRelationships(proposal.relationships, bundle);
  const decision = validateDecision(proposal.decision, expectedDecisionKind);
  rejectRelationshipSemanticsOutsideCarrier(decision, bundle);
  return {proposal: {...proposal, relationships, decision}, rendered: renderDecision(decision, relationships), relationships};
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
  if (labels.length > 0) {
    const labelList = labels[0].item?.labels;
    if (!Array.isArray(labelList) || labelList.length !== 1 || typeof labelList[0]?.rationale !== "string") fail("label proposal carrier is invalid");
    return {type: "label", raw: labelList[0].rationale, expectedDecisionKind: "needs_info", itemIndex: labels[0].index, labelIndex: 0};
  }
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
  if (/\b(?:PRs?|pull[\s-]+requests?)\s*(?:(?:number|num(?:ber)?|no)\.?\s*)?:?\s*#?\s*\d+\b/i.test(normalized)) violations.push("numbered pull-request reference is not allowed");
  if (/(^|[^A-Za-z0-9_])@[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\b/.test(value)) violations.push("user or bot mention is not allowed");
  if (/\[[^\]]+\]\s*(?:\([^)]*\)|\[[^\]]*\])/.test(value) || /<(?:a\s|[^>]+\shref\s*=)/i.test(value)) violations.push("agent-authored link syntax is not allowed");
  if (/\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?[ \t]*#\d+\b/i.test(normalized)) violations.push("closing keyword is not allowed");
  if (containsSecret(value)) violations.push("secret-like content is not allowed");
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
    "The repository documentation currently states:\n\n" +
    decision.quote.split("\n").map((line) => `> ${line}`).join("\n") +
    `\n\nSource: ${sourceUrl}`
  );
}

function appendRelationshipsAndFooter(body, decision, relationships) {
  const assessments = relationshipText(relationships);
  let rendered = body;
  if (assessments.length > 0) rendered += `\n\n${assessments.join("\n")}`;
  if (decision.kind === "missing_information" || decision.kind === "repository_evidence") rendered += `\n\n${COMMENT_FOOTER}`;
  return rendered;
}

async function renderVerifiedDecision(decision, relationships, bundle, fetchRepositoryFile) {
  if (decision.kind !== "repository_evidence") return renderDecision(decision, relationships);
  const evidence = await renderRepositoryEvidence(decision, bundle, fetchRepositoryFile);
  return appendRelationshipsAndFooter(evidence, decision, relationships);
}

function rejectRelationshipSemanticsOutsideCarrier(decision, bundle) {
  const values = [];
  if (typeof decision.quote === "string") values.push(decision.quote);
  if (typeof decision.reason === "string") values.push(decision.reason);
  for (const value of values) {
    const normalized = normalizePolicyText(value);
    if (
      /\b(?:related|not[ _-]?related|uncertain|relationship|duplicate status|lexical result)\b/i.test(normalized) ||
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

function parseSecondaryAction(raw, bundle) {
  const action = parseCanonicalCarrier(raw);
  if (!exactKeys(action, ["decision", "kind", "version"]) || action.version !== CONTRACT_VERSION || action.kind !== "triage_action") fail("secondary comment must be a canonical triage_action proposal");
  const decision = validateDecision(action.decision);
  rejectRelationshipSemanticsOutsideCarrier(decision, bundle);
  return {...action, decision};
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
      if (!exactKeys(item, ["type", "labels"]) || !Array.isArray(item.labels) || item.labels.length !== 1) fail("add_labels requires exactly one label intent");
      const label = item.labels[0];
      if (!exactKeys(label, ["name", "rationale", "confidence"]) || label.name !== "needs-info" || typeof label.rationale !== "string" || !new Set(["LOW", "MEDIUM", "HIGH"]).has(label.confidence)) fail("label intent is outside the trusted needs-info contract");
    } else {
      if (!exactKeys(item, ["type", "message"]) || typeof item.message !== "string" || item.message === "") fail("noop requires exactly one proposal message");
    }
  }
  if ((counts.get("noop") || 0) > 0 && trustedOutput.items.length !== 1) fail("noop must be exclusive from action outputs");
  if (bundle.status === "sensitive_stop" && ((counts.get("noop") || 0) !== 1 || trustedOutput.items.length !== 1)) fail("sensitive evidence requires the exact exclusive noop shape");

  const carrier = selectProposalCarrier(trustedOutput.items);
  const validated = validateAndRenderProposal({carrier: carrier.raw, bundle, expectedDecisionKind: carrier.expectedDecisionKind});
  if (
    bundle.status === "complete" &&
    carrier.type === "comment" &&
    validated.proposal.decision.kind !== "missing_information" &&
    validated.proposal.decision.kind !== "repository_evidence"
  ) fail("comment carrier decision is not allowlisted");
  if (bundle.status === "complete") {
    validated.rendered = await renderVerifiedDecision(
      validated.proposal.decision,
      validated.relationships,
      bundle,
      fetchRepositoryFile,
    );
  }
  const carrierItem = trustedOutput.items[carrier.itemIndex];
  if (carrier.type === "label") carrierItem.labels[0].rationale = validated.rendered;
  if (carrier.type === "comment") carrierItem.body = validated.rendered;
  if (carrier.type === "noop") carrierItem.message = validated.rendered;

  if (carrier.type === "label") {
    carrierItem.item_number = targetNumber;
    carrierItem.labels[0].suggest = true;
    const comment = trustedOutput.items.find((item) => item.type === "add_comment");
    if (comment) {
      const secondary = parseSecondaryAction(comment.body, bundle);
      if (secondary.decision.kind !== "missing_information" && secondary.decision.kind !== "repository_evidence") fail("secondary comment decision is not allowlisted");
      if (
        secondary.decision.kind === "missing_information" &&
        JSON.stringify(secondary.decision.fields) !== JSON.stringify(validated.proposal.decision.fields)
      ) fail("secondary missing-information fields must exactly match the needs-info label fields");
      comment.body = await renderVerifiedDecision(secondary.decision, [], bundle, fetchRepositoryFile);
      inspectRenderedText(comment.body, {...bundle, candidates: []});
    }
  }

  const renderedStrings = [];
  for (const item of trustedOutput.items) {
    if (item.type === "add_comment") renderedStrings.push(item.body);
    if (item.type === "add_labels") renderedStrings.push(item.labels[0].rationale);
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
