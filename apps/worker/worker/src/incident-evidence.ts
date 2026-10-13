/** Validation and pure combination of the committed incident evidence v1 contract. */
import { validateEvidenceSchema, validateMappingAssertion } from "./incident-evidence-schema.js";
import type { EvidenceDocument, EvidenceTarget } from "./types";

const utcPattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/;
const isoPattern = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?(Z|z|[+-]\d{2}:?\d{2})?$/;
const digitPattern = /^[0-9]+(?:\.[0-9]+)?$/;
const compare = (a: string, b: string): number => {
  const left = Array.from(a), right = Array.from(b);
  for (let i = 0; i < Math.min(left.length, right.length); i++) {
    const difference = left[i].codePointAt(0)! - right[i].codePointAt(0)!;
    if (difference) return difference < 0 ? -1 : 1;
  }
  return Math.sign(left.length - right.length);
};
const equal = (a: unknown, b: unknown): boolean => canonical(a) === canonical(b);
const fail = (message: string): never => { throw new Error(`Invalid incident evidence: ${message}`); };

/** Core's ASCII strings/code-point key order, with RFC 8785 numbers. */
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort(compare).map((key) => `${asciiString(key)}:${canonical((value as Record<string, unknown>)[key])}`).join(",")}}`;
  }
  if (typeof value === "string") return asciiString(value);
  // JSON.stringify supplies ECMAScript's shortest-round-trip binary64 form,
  // including integral floats, exponent thresholds and negative zero.
  if (typeof value === "number") {
    if (!Number.isFinite(value)) fail("nonfinite canonical number");
    return JSON.stringify(value);
  }
  return JSON.stringify(value);
}
function asciiString(value: string): string {
  return JSON.stringify(value).replace(/[\u007f-\uffff]/g, (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`);
}
async function digest(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(canonical(value));
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash)).map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 24);
}
function utcMicros(micros: bigint): string | null {
  let milliseconds = micros / 1000n;
  let remainder = micros % 1000n;
  if (remainder < 0) { milliseconds -= 1n; remainder += 1000n; }
  const date = new Date(Number(milliseconds));
  if (!Number.isFinite(date.getTime()) || date.getUTCFullYear() < 1 || date.getUTCFullYear() > 9999) return null;
  return date.toISOString().slice(0, -1).replace(/\.(\d{3})$/, (_, fraction: string) => `.${fraction}${remainder.toString().padStart(3, "0")}`) + "Z";
}
function microsFromUtc(value: string): bigint {
  return BigInt(Date.parse(value)) * 1000n + BigInt(value.slice(23, 26));
}
function roundedDecimalMicros(text: string, multiplier: bigint): bigint {
  const [integer, fraction = ""] = text.split(".");
  const denominator = 10n ** BigInt(fraction.length);
  const numerator = (BigInt(integer) * denominator + BigInt(fraction || "0")) * multiplier;
  const quotient = numerator / denominator;
  const residual = numerator % denominator;
  return quotient + (residual * 2n > denominator || (residual * 2n === denominator && quotient % 2n === 1n) ? 1n : 0n);
}
function parsedTime(time: EvidenceDocument, window: EvidenceDocument): EvidenceDocument {
  const output: EvidenceDocument = { ...time, status: "malformed", original_format: "unrecognized", utc: null, utc_offset: null,
    timezone_basis: null, precision: null, boundary_uncertain: false };
  if (time.original_type === "absent" || time.original_type === "null") {
    output.status = "missing"; output.original_format = null;
    return output;
  }
  const value = time.original_value;
  if (["boolean", "object", "array"].includes(time.original_type) || (time.original_type === "float" && value === null)) return output;
  let utc: string | null = null;
  if (["integer", "float"].includes(time.original_type) || (time.original_type === "string" && digitPattern.test(value))) {
    const text = String(value);
    const number = Number(text);
    if (!(number >= 1e8 && number < 1e14)) return output;
    const seconds = number < 1e11;
    utc = utcMicros(roundedDecimalMicros(text, seconds ? 1_000_000n : 1000n));
    if (!utc) return output;
    output.original_format = seconds ? "epoch_seconds" : "epoch_milliseconds";
    output.timezone_basis = "epoch_utc";
    output.precision = text.includes(".") && /[1-9]/.test(text.split(".")[1]) ? "microsecond" : seconds ? "second" : "millisecond";
  } else if (time.original_type === "string") {
    const match = isoPattern.exec(value);
    if (!match) return output;
    const [, datePart, hourText, minuteText, secondText, fractionText, zone] = match;
    const [year, month, day] = datePart.split("-").map(Number);
    const hour = Number(hourText), minute = Number(minuteText), second = Number(secondText ?? "0");
    const date = new Date(0);
    date.setUTCFullYear(year, month - 1, day);
    date.setUTCHours(hour, minute, second, 0);
    if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day ||
        date.getUTCHours() !== hour || date.getUTCMinutes() !== minute || date.getUTCSeconds() !== second) return output;
    if (!zone) { output.status = "ambiguous_timezone"; output.original_format = "iso8601"; return output; }
    let offsetMinutes = 0;
    if (zone !== "Z" && zone !== "z") {
      const digits = zone.slice(1).replace(":", "");
      const h = Number(digits.slice(0, 2)), m = Number(digits.slice(2));
      if (h > 23 || m > 59) return output;
      offsetMinutes = (zone[0] === "+" ? 1 : -1) * (h * 60 + m);
    }
    const micro = BigInt((fractionText ?? "").padEnd(6, "0") || "0");
    utc = utcMicros(BigInt(date.getTime() - offsetMinutes * 60_000) * 1000n + micro);
    if (!utc) return output;
    output.original_format = "iso8601";
    output.utc_offset = `${zone[0] === "-" ? "-" : "+"}${String(Math.floor(Math.abs(offsetMinutes) / 60)).padStart(2, "0")}:${String(Math.abs(offsetMinutes) % 60).padStart(2, "0")}`;
    output.timezone_basis = "explicit_offset";
    output.precision = !secondText ? "minute" : !fractionText ? "second" : fractionText.length <= 3 ? "millisecond" : "microsecond";
  } else return output;
  output.utc = utc;
  output.status = utc >= window.start && utc < window.end ? "in_window" : "out_of_window";
  if (time.clock_uncertainty_ms) {
    const slack = BigInt(time.clock_uncertainty_ms) * 1000n;
    output.boundary_uncertain = [window.start, window.end].some((edge) => {
      const delta = microsFromUtc(utc!) - microsFromUtc(edge);
      return (delta < 0n ? -delta : delta) <= slack;
    });
  }
  return output;
}
function identity(entity: EvidenceDocument): string {
  let id = entity.id;
  if (entity.id_kind === "mac") {
    const trimmed = id.trim().toLowerCase();
    if (/^[a-f0-9]{12}$/.test(trimmed)) id = trimmed.match(/../g)!.join(":");
    else if (/^(?:[a-f0-9]{2}:){5}[a-f0-9]{2}$/.test(trimmed)) id = trimmed;
    else if (/^(?:[a-f0-9]{2}-){5}[a-f0-9]{2}$/.test(trimmed)) id = trimmed.replace(/-/g, ":");
  }
  return `${entity.id_kind}\0${id}`;
}
function resolveMapping(entities: EvidenceDocument[], assertions: EvidenceDocument[] | null): EvidenceDocument {
  const base = { status: "not_evaluated", targets: [] as EvidenceDocument[], matched_on: [] as EvidenceDocument[], sources: [] as string[], confidence: null as string | null };
  if (assertions === null) return base;
  const wanted = new Map(entities.map((entity) => [identity(entity), entity]));
  const targets = new Map<string, EvidenceDocument>(), matched = new Map<string, EvidenceDocument>(), sources = new Set<string>();
  for (const assertion of assertions) {
    const hit = wanted.get(identity(assertion.entity));
    if (hit) {
      const targetKey = identity(assertion.target);
      if (!targets.has(targetKey)) targets.set(targetKey, assertion.target);
      if (!matched.has(identity(hit))) matched.set(identity(hit), hit);
      sources.add(assertion.source);
    }
  }
  if (!targets.size) return { ...base, status: "missing" };
  return { status: targets.size === 1 ? "verified" : "ambiguous",
    targets: [...targets.entries()].sort(([a], [b]) => compare(a, b)).map(([, value]) => value),
    matched_on: [...matched.entries()].sort(([a], [b]) => compare(a, b)).map(([, value]) => value),
    sources: [...sources].sort(compare), confidence: targets.size === 1 ? "exact_identifier" : null };
}
function sortRecords(a: EvidenceDocument, b: EvidenceDocument): number {
  const ka = [a.time.utc === null ? "1" : "0", a.time.utc ?? "", a.provenance.product, a.source_id,
    String(a.provenance.source_record_id ?? ""), a.evidence_id];
  const kb = [b.time.utc === null ? "1" : "0", b.time.utc ?? "", b.provenance.product, b.source_id,
    String(b.provenance.source_record_id ?? ""), b.evidence_id];
  for (let i = 0; i < ka.length; i++) { const difference = compare(ka[i], kb[i]); if (difference) return difference; }
  return 0;
}
function validUtc(value: string): boolean {
  return utcPattern.test(value) && parsedTime({
    original_type: "string", original_value: value, clock_uncertainty_ms: null,
  }, { start: "0001-01-01T00:00:00.000000Z", end: "9999-12-31T23:59:59.999999Z" }).utc === value;
}
function windowValid(window: EvidenceDocument): boolean {
  return validUtc(window.start) && validUtc(window.end) && window.start < window.end;
}
function coverageState(queried: EvidenceDocument | null, requested: EvidenceDocument): string {
  if (!queried) return "unknown";
  return queried.start <= requested.start && queried.end >= requested.end ? "covered" : "not_covered";
}
function truncation(p: EvidenceDocument): string {
  if (p.has_more === true) return "truncated";
  if (p.total_reported !== null && !p.post_filtered) {
    const seen = (p.offset ?? 0) + p.returned;
    // A total below the rows already read contradicts them; it proves nothing.
    if (p.total_reported < seen) return "unknown";
    if (p.total_reported > seen) return "truncated";
    if (!p.interrupted) return "not_truncated";
  }
  if (p.interrupted) return "unknown";
  if (p.has_more === false) return "not_truncated";
  return "unknown";
}
function reasons(source: EvidenceDocument): string[] {
  const c = source.coverage, p = c.pagination, n = c.counts;
  const found: string[] = [];
  if (source.failure) found.push("partial_response");
  if (source.partial_reasons.includes("budget_exhausted")) found.push("budget_exhausted");
  if (c.truncation === "truncated") found.push("truncated");
  else if (c.truncation === "unknown") {
    found.push("truncation_unknown");
    if (p.post_filtered) found.push("post_filtered");
  }
  if (p.offset) found.push("prefix_not_collected");
  if (c.window_coverage === "not_covered") found.push("window_not_covered");
  if (c.window_coverage === "unknown") found.push("window_coverage_unknown");
  for (const [key, reason] of [["malformed_dropped", "malformed_records"], ["untimed", "untimed_records"],
    ["conflicting", "conflicting_records"], ["boundary_uncertain", "boundary_uncertain"]]) if (n[key]) found.push(reason);
  return found.sort(compare);
}
const failureOutcome: Record<string, string[]> = {
  unavailable: ["unavailable", "partial_response"], auth_failed: ["auth_failed"],
  permission_denied: ["permission_denied"], timeout: ["timeout"], unsupported: ["unsupported"],
  parse_failed: ["parse_failed"], not_attempted: ["budget_exhausted"],
};

/** Rejects at the schema layer first, then checks all cross-field semantic rules. */
export async function validateIncidentEvidence(value: unknown): Promise<EvidenceDocument> {
  if (!validateEvidenceSchema(value)) fail("schema");
  const doc = value as EvidenceDocument;
  const window = doc.requested_window;
  if (!windowValid(window)) fail("requested_window");
  const byId = new Map<string, EvidenceDocument>();
  for (const source of doc.sources) {
    if (typeof source.source_id !== "string" || !/^[a-z0-9][a-z0-9_.:-]{0,127}$/.test(source.source_id) ||
        typeof source.collected_at !== "string" || !validUtc(source.collected_at))
      fail("source identity or collection time");
    if (byId.has(source.source_id) || (byId.size && compare([...byId.keys()].at(-1)!, source.source_id) >= 0)) fail("source order");
    byId.set(source.source_id, source);
    const c = source.coverage, p = c.pagination, n = c.counts;
    if (!windowValid(c.requested_window) || !equal(c.requested_window, window) || (c.queried_window && !windowValid(c.queried_window))) fail("source window");
    if (c.window_coverage !== coverageState(c.queried_window, window)) fail("window coverage");
    if (c.truncation !== truncation(p) || p.returned !== n.received ||
        (p.cap !== null && p.requested_cap !== null && p.cap > p.requested_cap)) fail("pagination");
    const complete = c.window_coverage === "covered" && c.truncation === "not_truncated" && !p.offset && !p.interrupted &&
      !n.malformed_dropped && !n.untimed && !n.conflicting && !n.boundary_uncertain;
    if (c.complete !== complete || c.population_total !== (complete ? n.in_window : null)) fail("completeness");
    if (n.received !== n.accepted + n.malformed_dropped + n.duplicates_dropped ||
        n.accepted !== n.in_window + n.out_of_window + n.untimed || n.conflicting > n.accepted ||
        n.conflicting === 1 || n.boundary_uncertain > n.out_of_window) fail("counts");
    if (source.outcome === "partial") {
      if (complete || !equal(source.partial_reasons, reasons(source)) ||
          p.interrupted !== (source.failure !== null || source.partial_reasons.includes("budget_exhausted"))) fail("partial reasons");
    } else if (["complete", "empty"].includes(source.outcome)) {
      if (!complete || source.failure !== null || source.partial_reasons.length ||
          (source.outcome === "empty") !== (n.in_window === 0)) fail("source outcome");
    } else if (!source.failure || !failureOutcome[source.outcome]?.includes(source.failure.kind) ||
        n.received || source.partial_reasons.length || complete || c.queried_window !== null ||
        c.window_coverage !== "unknown" || c.truncation !== "unknown" || !p.interrupted ||
        p.has_more !== null || p.total_reported !== null) fail("failed source");
  }
  const perSource = new Map([...byId.keys()].map((key) => [key, [] as EvidenceDocument[]]));
  const evidenceIds = new Set<string>();
  for (const record of doc.records) {
    const source = byId.get(record.source_id);
    if (!source) fail("unlisted record source");
    const p = record.provenance;
    for (const field of ["product", "api_family", "source_tool", "endpoint", "scope", "query", "collected_at"])
      if (!equal(p[field], source![field])) fail("record provenance");
    const t = record.time;
    if ((t.original_type === "integer" && (!Number.isInteger(t.original_value) || typeof t.original_value !== "number")) ||
        (t.original_type === "float" && t.original_value !== null && typeof t.original_value !== "number") ||
        (t.original_type === "string" && typeof t.original_value !== "string") ||
        (t.original_type === "boolean" && typeof t.original_value !== "boolean") ||
        (["absent", "null", "object", "array"].includes(t.original_type) && t.original_value !== null)) fail("original timestamp type");
    if (!equal(record.time, parsedTime(record.time, window))) fail("record time");
    if (!equal(record.mapping, resolveMapping(record.entities, doc.mappings))) fail("record mapping");
    const rid = p.source_record_id;
    if ((rid !== null) !== (record.evidence_id_basis === "source_record_id")) fail("evidence ID basis");
    const content = { source_record_id: rid === null ? null : [typeof rid === "number" ? "int" : "str", rid],
      source_record_id_field: p.source_record_id_field,
      time: [record.time.original_field, record.time.original_type, record.time.original_value],
      event_type: record.event_type, summary: record.summary, entities: record.entities, attributes: record.attributes };
    const hash = await digest(content);
    // The identity differing versions share: the typed source record ID, or for a record without one whose
    // summary cannot identify it, the digest of its content with the summary left out. Plain content-hash
    // records have none and cannot conflict.
    const base = rid !== null
      ? `${record.source_id}|${typeof rid === "number" ? "int" : "str"}|${encodeURIComponent(String(rid)).replace(/[!'()*]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`)}`
      : record.evidence_id_basis === "content_hash_without_summary"
        ? `${record.source_id}|fields|${await digest({ ...content, summary: null })}` : null;
    if (record.conflict_group !== null && (base === null || record.conflict_group !== base)) fail("conflict group");
    const expected = base === null ? `${record.source_id}|sha256|${hash}` :
      record.conflict_group === null ? base : `${base}|version|${hash}`;
    if (record.evidence_id !== expected || evidenceIds.has(expected)) fail("evidence ID");
    evidenceIds.add(expected);
    perSource.get(record.source_id)!.push(record);
  }
  for (let i = 1; i < doc.records.length; i++) if (sortRecords(doc.records[i - 1], doc.records[i]) > 0) fail("record order");
  for (const source of doc.sources) {
    const records = perSource.get(source.source_id)!;
    const n = source.coverage.counts;
    const placed = records.filter((record) => record.time.status === "in_window").map((record) => record.time.utc).sort(compare);
    const groups = new Map<string, number>();
    for (const record of records) if (record.conflict_group) groups.set(record.conflict_group, (groups.get(record.conflict_group) ?? 0) + 1);
    if ([...groups.values()].some((size) => size < 2) ||
        !equal([n.accepted, n.in_window, n.out_of_window, n.untimed, n.conflicting, n.boundary_uncertain],
          [records.length, placed.length, records.filter((r) => r.time.status === "out_of_window").length,
            records.filter((r) => !["in_window", "out_of_window"].includes(r.time.status)).length,
            [...groups.values()].reduce((a, b) => a + b, 0),
            records.filter((r) => r.time.status === "out_of_window" && r.time.boundary_uncertain).length]) ||
        !equal([source.coverage.observed_first_utc, source.coverage.observed_last_utc],
          placed.length ? [placed[0], placed.at(-1)] : [null, null])) fail("record counts");
  }
  const budget = doc.budgets;
  if (!equal(budget.exhausted, [...new Set<string>(budget.exhausted)].sort(compare))) fail("budget order");
  const duration = Number(microsFromUtc(window.end) - microsFromUtc(window.start)) / 1e6;
  if ((budget.limits.window_seconds < duration) !== budget.exhausted.includes("window")) fail("window budget");
  for (const [kind, field] of [["events", "events"], ["calls", "calls"], ["elapsed", "elapsed_ms"]])
    if (budget.usage[field] > budget.limits[field] && !budget.exhausted.includes(kind)) fail("budget exhaustion");
  const outcomes = doc.sources.map((source: EvidenceDocument) => source.outcome);
  const overall = !outcomes.some((outcome: string) => ["complete", "empty", "partial"].includes(outcome)) ? "failed" :
    budget.exhausted.length || !outcomes.every((outcome: string) => ["complete", "empty"].includes(outcome)) ? "partial" :
    outcomes.every((outcome: string) => outcome === "empty") ? "empty" : "complete";
  if (doc.overall !== overall || doc.coverage_complete !== ["complete", "empty"].includes(overall)) fail("overall");
  return doc;
}

export async function canonicalIncidentEvidence(value: unknown): Promise<string> {
  return canonical(await validateIncidentEvidence(value));
}

/** Pure, order-independent combination. Identical documents count once. */
export async function combineIncidentEvidence(values: unknown[]): Promise<EvidenceDocument> {
  const unique = new Map<string, EvidenceDocument>();
  for (const value of values) { const doc = await validateIncidentEvidence(value); unique.set(canonical(doc), doc); }
  if (!unique.size) fail("no documents");
  const docs = [...unique.entries()].sort(([a], [b]) => compare(a, b)).map(([, doc]) => doc);
  const window = docs[0].requested_window;
  if (docs.some((doc) => !equal(doc.requested_window, window))) fail("different requested windows");
  const sourceRecords = new Map<string, { source: EvidenceDocument; records: EvidenceDocument[] }>();
  for (const doc of docs) {
    for (const source of doc.sources) {
      const records = doc.records.filter((record: EvidenceDocument) => record.source_id === source.source_id)
        .map((record: EvidenceDocument) => ({ ...record, mapping: resolveMapping(record.entities, null) }));
      const previous = sourceRecords.get(source.source_id);
      if (previous && !equal(previous, { source, records })) fail(`conflicting source ${source.source_id}`);
      sourceRecords.set(source.source_id, { source, records });
    }
  }
  const assertionSets = docs.map((doc) => doc.mappings).filter((assertions) => assertions !== null) as EvidenceDocument[][];
  const mappings = assertionSets.length ? [...new Map(assertionSets.flat().map((assertion) => [canonical(assertion), assertion])).entries()]
    .sort(([a], [b]) => compare(a, b)).map(([, assertion]) => assertion) : null;
  const sources = [...sourceRecords.values()].map((item) => item.source).sort((a, b) => compare(a.source_id, b.source_id));
  const records = [...sourceRecords.values()].flatMap((item) => item.records)
    .map((record) => ({ ...record, mapping: resolveMapping(record.entities, mappings) })).sort(sortRecords);
  const limits = { window_seconds: Math.min(...docs.map((doc) => doc.budgets.limits.window_seconds)), events: 0, calls: 0, elapsed_ms: 0 };
  const usage = { events: 0, calls: 0, elapsed_ms: 0 };
  const exhausted = new Set<string>();
  for (const doc of docs) {
    for (const field of ["events", "calls", "elapsed_ms"] as const) {
      limits[field] += doc.budgets.limits[field]; usage[field] += doc.budgets.usage[field];
    }
    for (const kind of doc.budgets.exhausted) exhausted.add(kind);
  }
  for (const [kind, field] of [["events", "events"], ["calls", "calls"], ["elapsed", "elapsed_ms"]])
    if (usage[field as keyof typeof usage] > limits[field as keyof typeof usage]) exhausted.add(kind);
  const budgets = { limits, usage, exhausted: [...exhausted].sort(compare) };
  const outcomes = sources.map((source) => source.outcome);
  const overall = !outcomes.some((outcome) => ["complete", "empty", "partial"].includes(outcome)) ? "failed" :
    budgets.exhausted.length || !outcomes.every((outcome) => ["complete", "empty"].includes(outcome)) ? "partial" :
    outcomes.every((outcome) => outcome === "empty") ? "empty" : "complete";
  return validateIncidentEvidence({ schema: "unifi-incident-evidence", schema_version: 1, requested_window: window,
    budgets, mappings, sources, records, overall, coverage_complete: ["complete", "empty"].includes(overall) });
}

export const DEFAULT_MAX_RECORDS_RETURNED = 25;
export const MAX_RECORDS_RETURNED = 50;
/** Core's `VIEW_TOKEN_BUDGET`: most estimated tokens a view takes as an MCP tool result. */
export const VIEW_TOKEN_BUDGET = 20_000;
/** Core's `VIEW_BYTE_LIMIT`: most UTF-8 bytes a view takes as that result; only an undercounting estimate could pass it. */
export const VIEW_BYTE_LIMIT = 4 * VIEW_TOKEN_BUDGET;
/** Core's `RECORD_TOKEN_LIMIT`: a citation over it is never returned, since identifiers are never cut. */
export const RECORD_TOKEN_LIMIT = 2_500;
const MAX_CITED_EVIDENCE_ID_LENGTH = 256;
export const MAX_CURSOR_LENGTH = 2 + 27 + 1 + MAX_CITED_EVIDENCE_ID_LENGTH;
/** Core's `SOURCE_LABEL_TOKEN_LIMIT`: a source's tool and scope labels are cut to it; a valid ASCII request label never is. */
const SOURCE_LABEL_TOKEN_LIMIT = 128;
const textTokenLimits = { event_type: 40, original_value: 40, source_tool: SOURCE_LABEL_TOKEN_LIMIT, summary: 200 } as const;
const baseIdPattern = String.raw`(?:(?:int|str)\|[A-Za-z0-9%._~-]+|fields\|[0-9a-f]{24})`;
const evidenceIdPattern = new RegExp(String.raw`^[a-z0-9][a-z0-9_.:-]{0,127}\|(?:` + baseIdPattern +
  String.raw`(?:\|version\|[0-9a-f]{24})?|sha256\|[0-9a-f]{24})$`);
/** A version's evidence ID is its conflict group's base identity plus this suffix. */
const versionSuffix = /\|version\|[0-9a-f]{24}$/;
const cursorPattern = /^(?:[02]\|\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z|1\|)\|(.+)$/;
const viewSourceFields = ["source_id", "product", "source_tool", "scope", "outcome", "failure", "partial_reasons", "coverage"];
const scopeFields = ["controller_id", "site", "location_id"];

/** Core's `EvidenceViewTooLarge`: sources and mapping assertions alone exceed the view's budget, or a view its byte cap. */
export class EvidenceViewTooLargeError extends Error {}

// Core's `estimated_tokens` and `serialized_bytes`, exactly: JSON indented by two spaces as an MCP server sends it.
// A string value costs one token per UTF-8 byte it is sent in; field names cost as words.
const shortEscapes = new Set([0x22, 0x5c, 0x08, 0x09, 0x0a, 0x0c, 0x0d]);
/** UTF-8 bytes `text` takes inside a JSON string as sent: control characters and lone surrogates as `\uXXXX`. */
function sentBytes(text: string): number {
  let total = 0;
  for (const character of text) {
    const point = character.codePointAt(0)!;
    if (shortEscapes.has(point)) total += 2;
    else if (point < 0x20) total += 6;
    else if (point < 0x80) total += 1;
    else if (point < 0x800) total += 2;
    else if (point >= 0xd800 && point <= 0xdfff) total += 6;
    else total += point < 0x10000 ? 3 : 4;
  }
  return total;
}
/** A string value's text: one token per byte as sent, as no token is shorter. */
const textTokens = sentBytes;
const nameParts = /[A-Za-z]+|[0-9]+|[\s\S]/gu;
function nameTokens(name: string): number {
  let total = 0;
  for (const [part] of name.matchAll(nameParts)) {
    const first = part.codePointAt(0)!;
    if ((first >= 65 && first <= 90) || (first >= 97 && first <= 122)) total += Math.ceil(part.length / 4);
    else if (first >= 48 && first <= 57) total += Math.ceil(part.length / 3);
    else total += sentBytes(part);
  }
  return total;
}
// One per digit; a sign and a float's ".0" are allowed for.
const integerTokens = (value: number): number => BigInt(value < 0 ? -value : value).toString().length + 3;
/** Upper bound on the tokens a JSON value takes as indented JSON (Core's `estimated_tokens`). */
export function estimatedTokens(value: unknown): number {
  if (value === null) return 1;
  if (typeof value === "boolean") return 2;
  if (typeof value === "number") return Number.isInteger(value) ? integerTokens(value) : 24;
  if (typeof value === "string") return textTokens(value) + 2;
  if (Array.isArray(value)) return 3 + value.reduce((sum: number, item) => sum + 2 + estimatedTokens(item), 0);
  if (typeof value === "object") {
    return 3 + Object.entries(value as Record<string, unknown>)
      .reduce((sum, [key, item]) => sum + 6 + nameTokens(key) + estimatedTokens(item), 0);
  }
  throw new Error("not a JSON value");
}
/** UTF-8 bytes of a JSON value as sent, a number at its longest form (Core's `serialized_bytes`). */
export function serializedBytes(value: unknown, depth = 0): number {
  if (value === null) return 4;
  if (typeof value === "boolean") return value ? 4 : 5;
  if (typeof value === "number") return Number.isInteger(value) ? integerTokens(value) : 24;
  if (typeof value === "string") return sentBytes(value) + 2;
  // Each member or item on its own line, indented one level deeper, then the closing bracket on its own line.
  const inner = 1 + 2 * (depth + 1), outer = 1 + 2 * depth;
  let members: number[];
  if (Array.isArray(value)) members = value.map((item) => inner + serializedBytes(item, depth + 1));
  else if (typeof value === "object") {
    members = Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => inner + sentBytes(key) + 4 + serializedBytes(item, depth + 1));
  } else throw new Error("not a JSON value");
  return members.length ? 2 + members.reduce((sum, size) => sum + size, 0) + members.length - 1 + outer : 2;
}
const envelopeTokens = estimatedTokens({ success: true, data: null }) - estimatedTokens(null);
/** The longest prefix of `text`, in code points, whose estimated tokens are at most `limit`. */
function cut(text: string, limit: number): string {
  if (textTokens(text) <= limit) return text;
  const points = Array.from(text);
  // Every character costs at least a token, so no longer prefix fits.
  let low = 0, high = Math.min(points.length, limit);
  while (low < high) {
    const middle = Math.floor((low + high + 1) / 2);
    if (textTokens(points.slice(0, middle).join("")) <= limit) low = middle;
    else high = middle - 1;
  }
  return points.slice(0, low).join("");
}

type SelectionKey = [number, string, string];
const rank = (status: string): number => status === "in_window" ? 0 : status === "out_of_window" ? 2 : 1;
const recordKey = (record: EvidenceDocument): SelectionKey => [rank(record.time.status), record.time.utc ?? "", record.evidence_id];
const compareKeys = (a: SelectionKey, b: SelectionKey): number => a[0] - b[0] || compare(a[1], b[1]) || compare(a[2], b[2]);
/** The selection key a view cursor names, or null for anything that is not one. */
function cursorKey(cursor: unknown): SelectionKey | null {
  if (typeof cursor !== "string" || cursor.length > MAX_CURSOR_LENGTH) return null;
  const match = cursorPattern.exec(cursor);
  if (!match || !evidenceIdPattern.test(match[1])) return null;
  const [position, utc] = cursor.split("|", 2);
  return [Number(position), utc, match[1]];
}
function tally(records: EvidenceDocument[]): EvidenceDocument {
  const inWindow = records.filter((record) => record.time.status === "in_window").length;
  const outOfWindow = records.filter((record) => record.time.status === "out_of_window").length;
  return { total: records.length, in_window: inWindow, out_of_window: outOfWindow, untimed: records.length - inWindow - outOfWindow };
}
/** A source in the view, its labels cut to `SOURCE_LABEL_TOKEN_LIMIT` and named in `truncated`. */
function viewSource(source: EvidenceDocument): EvidenceDocument {
  const truncated: Record<string, number> = {};
  const label = (field: string, value: string | null): string | null => {
    if (value === null) return null;
    const kept = cut(value, SOURCE_LABEL_TOKEN_LIMIT);
    if (kept !== value) truncated[field] = Array.from(value).length;
    return kept;
  };
  const shown: EvidenceDocument = Object.fromEntries(viewSourceFields.map((field) => [field, source[field]]));
  shown.source_tool = label("source_tool", source.source_tool);
  shown.scope = Object.fromEntries(scopeFields.map((field) => [field, label(field, source.scope[field] ?? null)]));
  shown.truncated = truncated;
  return shown;
}
/** A record's citation, or null when its identifiers cannot be cited within the record limit. */
function citation(record: EvidenceDocument): EvidenceDocument | null {
  if (record.evidence_id.length > MAX_CITED_EVIDENCE_ID_LENGTH) return null;
  const identifiers = [...record.entities, ...record.mapping.targets].map((entity: EvidenceDocument) => entity.id as string);
  // Every character costs at least a token.
  if (identifiers.reduce((sum, identifier) => sum + Array.from(identifier).length, 0) > RECORD_TOKEN_LIMIT) return null;
  const truncated: Record<string, number> = {};
  const text = (field: keyof typeof textTokenLimits, value: unknown): unknown => {
    if (typeof value !== "string") return value;
    const kept = cut(value, textTokenLimits[field]);
    if (kept !== value) truncated[field] = Array.from(value).length;
    return kept;
  };
  const sourceTool = text("source_tool", record.provenance.source_tool);
  const eventType = text("event_type", record.event_type);
  const originalValue = text("original_value", record.time.original_value);
  const summary = text("summary", record.summary);
  // Versions of one identity name their conflict group, which is the evidence ID without its version suffix;
  // other citations omit the key, so they cost nothing more.
  const base = record.evidence_id.replace(versionSuffix, "");
  if ((record.conflict_group === null) !== (base === record.evidence_id) ||
      (record.conflict_group !== null && record.conflict_group !== base)) {
    fail("a cited version names its own conflict group, and only versions name one");
  }
  const group = record.conflict_group === null ? {} : { conflict_group: record.conflict_group };
  const cited = {
    evidence_id: record.evidence_id, ...group, product: record.provenance.product, source_tool: sourceTool,
    source_record_id: record.provenance.source_record_id,
    time: { status: record.time.status, utc: record.time.utc, boundary_uncertain: record.time.boundary_uncertain,
      original_field: record.time.original_field, original_type: record.time.original_type, original_value: originalValue },
    event_type: eventType, summary,
    entity_ids: record.entities.map((entity: EvidenceDocument) => entity.id),
    mapping: { status: record.mapping.status, target_ids: record.mapping.targets.map((target: EvidenceDocument) => target.id),
      sources: record.mapping.sources },
    truncated,
  };
  return estimatedTokens(cited) <= RECORD_TOKEN_LIMIT ? cited : null;
}
/**
 * Core's bounded client view (`unifi_core.incident_evidence_view.client_view`) of a validated document:
 * coverage unchanged, record citations fitted to `VIEW_TOKEN_BUDGET` and `maxRecords`, resumed after a cursor.
 * Throws `EvidenceViewTooLargeError` when the sources and mapping assertions alone, labels cut, exceed the budget,
 * or when the view would exceed `VIEW_BYTE_LIMIT` as sent.
 */
export async function incidentEvidenceView(
  value: unknown, maxRecords = DEFAULT_MAX_RECORDS_RETURNED, resumeAfter: string | null = null,
): Promise<EvidenceDocument> {
  const doc = await validateIncidentEvidence(value);
  const records: EvidenceDocument[] = doc.records;
  const after = resumeAfter === null ? null : cursorKey(resumeAfter);
  if (resumeAfter !== null && !after) fail("a cursor must be a next_cursor value returned by an evidence view");
  const order = records.map((_, index) => index).sort((a, b) => compareKeys(recordKey(records[a]), recordKey(records[b])));
  const pending = order.filter((index) => !after || compareKeys(recordKey(records[index]), after) > 0);
  const sources = doc.sources.map(viewSource);
  // The selection's numbers and cursor are not known until the end, so its largest possible form is reserved up front.
  const count = Math.max(records.length, MAX_RECORDS_RETURNED);
  const reservedTally = { total: count, in_window: count, out_of_window: count, untimed: count };
  const skeleton = {
    schema: "unifi-incident-evidence-view", schema_version: 1, evidence_schema_version: 1,
    requested_window: doc.requested_window, overall: doc.overall, coverage_complete: doc.coverage_complete,
    budgets: doc.budgets, mappings: doc.mappings, sources, records: [],
    record_selection: { max_records_returned: count, omission: "presentation_limit", resume_after: resumeAfter,
      collected: reservedTally, before_resume: reservedTally, returned: reservedTally, omitted: reservedTally,
      too_large: count, limited_by: "max_records_returned", next_cursor: "-".repeat(MAX_CURSOR_LENGTH) },
  };
  let used = envelopeTokens + estimatedTokens(skeleton);
  if (used > VIEW_TOKEN_BUDGET) {
    throw new EvidenceViewTooLargeError(
      `the evidence view would exceed its ${VIEW_TOKEN_BUDGET}-token output budget without any record ` +
      `(sources: ${sources.length}, mapping assertions: ${(doc.mappings ?? []).length}); narrow the request ` +
      "to fewer sources (one location_id, fewer products or camera_ids) or fewer mapping assertions, " +
      "or use detail=full for the whole document");
  }
  const kept = new Map<number, EvidenceDocument>();
  // Records too large to cite are counted once they lie before a returned record, or when nothing after
  // them is left; otherwise the next view, resuming after the last returned record, counts them.
  let tooLarge = 0, skipped = 0;
  let limitedBy: "max_records_returned" | "output_budget" | null = null;
  for (const index of pending) {
    const cited = citation(records[index]);
    if (!cited) { skipped += 1; continue; }
    if (kept.size === maxRecords) { limitedBy = "max_records_returned"; break; }
    const cost = 2 + estimatedTokens(cited);
    if (used + cost > VIEW_TOKEN_BUDGET) {
      if (kept.size) { limitedBy = "output_budget"; break; }
      // Nothing is returned yet: the citation cannot fit beside the view's sources, so it is too large.
      skipped += 1; continue;
    }
    kept.set(index, cited);
    used += cost;
    tooLarge += skipped; skipped = 0;
  }
  if (limitedBy === null) tooLarge += skipped;
  const keptIndexes = [...kept.keys()].sort((a, b) => a - b);
  const returned = keptIndexes.map((index) => records[index]);
  const last = keptIndexes.map((index) => recordKey(records[index])).sort(compareKeys).at(-1);
  const view = {
    schema: "unifi-incident-evidence-view", schema_version: 1, evidence_schema_version: 1,
    requested_window: doc.requested_window, overall: doc.overall, coverage_complete: doc.coverage_complete,
    budgets: doc.budgets, mappings: doc.mappings, sources,
    records: keptIndexes.map((index) => kept.get(index)),
    record_selection: {
      max_records_returned: maxRecords, omission: "presentation_limit", resume_after: resumeAfter,
      collected: tally(records),
      before_resume: tally(order.filter((index) => after && compareKeys(recordKey(records[index]), after) <= 0).map((index) => records[index])),
      returned: tally(returned),
      omitted: tally(pending.filter((index) => !kept.has(index)).map((index) => records[index])),
      too_large: tooLarge, limited_by: limitedBy,
      // A limit stops the view only after it returned a record.
      next_cursor: limitedBy && last ? last.join("|") : null,
    },
  };
  if (serializedBytes({ success: true, data: view }) > VIEW_BYTE_LIMIT) {
    throw new EvidenceViewTooLargeError(
      `the evidence view would exceed its ${VIEW_BYTE_LIMIT}-byte output limit (sources: ${sources.length}, ` +
      `records: ${keptIndexes.length}); request fewer records with max_records_returned, or use detail=full ` +
      "for the whole document");
  }
  return view;
}

const evidenceTools = { network: "unifi_get_incident_evidence", protect: "protect_get_incident_evidence" } as const;
const requestLimits = { max_window_seconds: 30 * 24 * 3600, max_events: 10_000, max_calls: 100, max_elapsed_ms: 120_000 };
const requestFields = new Set(["start", "end", "location_id", "products", "device_macs", "camera_ids", "mappings",
  "detail", "max_records_returned", "resume_after", ...Object.keys(requestLimits)]);
const MAX_FILTER_IDS = 50, MAX_CAMERA_IDS = 5, MAX_MAPPINGS = 20, MAX_LABEL_LENGTH = 128, MAX_MAPPING_ID_LENGTH = 64;
/**
 * Every source is returned in full, so a call reads at most as many sources as one location's Network,
 * Protect cameras and Access produce; the bounded view's size rests on it.
 */
export const MAX_TIMELINE_SOURCES = 1 + MAX_CAMERA_IDS + 1;
const labelRule = "without control characters, quotes or backslashes";
// Core's `is_label`: labels and mapping identifiers are repeated in the view, so JSON-escaped characters are refused.
const isLabel = (value: unknown, maxLength: number): boolean => typeof value === "string" && value.length > 0 &&
  Array.from(value).length <= maxLength && !/[\u0000-\u001f\u007f"\\]/.test(value);
/** A refused identifier is echoed only in a short, quoted form restricted to harmless characters. */
const boundedLabel = (value: string): string => {
  const characters = Array.from(value);
  return `"${characters.slice(0, 40).join("").replace(/[^A-Za-z0-9._:\- ]/g, "?")}${characters.length > 40 ? "…" : ""}"`;
};
function normalizeBound(value: unknown): string | null {
  if (typeof value !== "string" || !isoPattern.test(value) || !isoPattern.exec(value)?.[6]) return null;
  const parsed = parsedTime({ original_type: "string", original_value: value, clock_uncertainty_ms: null },
    { start: "0001-01-01T00:00:00.000000Z", end: "9999-12-31T23:59:59.999999Z" });
  return parsed.utc;
}
function normalizeMac(value: string): string | null {
  const trimmed = value.trim().toLowerCase();
  if (/^[a-f0-9]{12}$/.test(trimmed)) return trimmed.match(/../g)!.join(":");
  if (/^(?:[a-f0-9]{2}:){5}[a-f0-9]{2}$/.test(trimmed)) return trimmed;
  if (/^(?:[a-f0-9]{2}-){5}[a-f0-9]{2}$/.test(trimmed)) return trimmed.replace(/-/g, ":");
  return null;
}
/** Validated mapping assertions, or the reason they are refused. */
function normalizeMappings(value: unknown): EvidenceDocument[] | null | string {
  if (value === undefined || value === null) return null;
  if (!Array.isArray(value)) return "mappings must be valid exact-identifier assertions";
  if (value.length > MAX_MAPPINGS) return `mappings must list at most ${MAX_MAPPINGS} assertions`;
  if (value.some((assertion) => !validateMappingAssertion(assertion))) return "mappings must be valid exact-identifier assertions";
  const refs = value.flatMap((assertion) => [assertion.entity, assertion.target]);
  if (refs.some((ref) => !isLabel(ref.id, MAX_MAPPING_ID_LENGTH)))
    return `mapping identifiers must be 1-${MAX_MAPPING_ID_LENGTH} characters ${labelRule}`;
  // Records are mapped by identity alone, so an assertion states no role.
  if (refs.some((ref) => ref.role !== undefined && ref.role !== null))
    return "mapping assertions identify entities by kind, id_kind and id only; omit role";
  return value.map((assertion) => ({
    entity: { role: null, ...assertion.entity }, target: { role: null, ...assertion.target }, source: assertion.source,
  }));
}
type TransportFailure = "unavailable" | "unsupported" | "parse_failed" | "timeout" | "auth_failed" | "permission_denied";
function classifyTransport(error: unknown): { kind: TransportFailure; http_status: number | null } {
  try {
    const candidate = error && typeof error === "object" ? error as Record<string, unknown> : {};
    const rawStatus = candidate.status ?? candidate.statusCode ?? candidate.http_status;
    const status = typeof rawStatus === "number" && Number.isInteger(rawStatus) && rawStatus >= 100 && rawStatus <= 599 ? rawStatus : null;
    const name = typeof candidate.name === "string" ? candidate.name : "";
    if (status === 401) return { kind: "auth_failed", http_status: status };
    if (status === 403) return { kind: "permission_denied", http_status: status };
    if ([404, 405, 501].includes(status ?? 0)) return { kind: "unsupported", http_status: status };
    if (["TimeoutError", "AbortError"].includes(name)) return { kind: "timeout", http_status: status };
    return { kind: "unavailable", http_status: status };
  } catch {
    // Some exception implementations expose throwing accessors. Never render one.
  }
  return { kind: "unavailable", http_status: null };
}
async function failedDocument(
  product: "network" | "protect" | "access", failure: { kind: TransportFailure; http_status: number | null },
  window: EvidenceDocument, limits: EvidenceDocument, mappings: EvidenceDocument[] | null,
  locationId: string | null, start: string, end: string,
): Promise<EvidenceDocument> {
  const duration = Number(microsFromUtc(window.end) - microsFromUtc(window.start)) / 1e6;
  const zeros = { received: 0, accepted: 0, in_window: 0, out_of_window: 0, untimed: 0,
    malformed_dropped: 0, duplicates_dropped: 0, conflicting: 0, boundary_uncertain: 0 };
  const source = {
    source_id: `${product}.incident_evidence${locationId ? `.${await digest(locationId)}` : ""}`, product, api_family: null,
    source_tool: product === "access" ? null : evidenceTools[product],
    endpoint: null, scope: { controller_id: null, site: null, location_id: locationId }, query: { start, end },
    collected_at: new Date().toISOString().replace(/\.(\d{3})Z$/, ".$1" + "000Z"), outcome: failure.kind,
    failure, partial_reasons: [],
    coverage: { requested_window: window, queried_window: null, window_coverage: "unknown", observed_first_utc: null,
      observed_last_utc: null, filters: {}, pagination: { offset: null, requested_cap: null, cap: null, returned: 0,
        has_more: null, total_reported: null, post_filtered: false, interrupted: true }, truncation: "unknown",
      retention_coverage: "unknown", counts: zeros, complete: false, population_total: null },
  };
  return { schema: "unifi-incident-evidence", schema_version: 1, requested_window: window,
    budgets: { limits, usage: { events: 0, calls: 0, elapsed_ms: 0 }, exhausted: duration > limits.window_seconds ? ["window"] : [] },
    mappings, sources: [source], records: [], overall: "failed", coverage_complete: false };
}

/** Read-only fanout. Every failure contributes a source to one returned evidence document. */
export async function collectIncidentEvidence(
  args: Record<string, unknown>, targets: EvidenceTarget[],
  call: (target: EvidenceTarget, tool: string, parameters: Record<string, unknown>) => Promise<unknown>,
): Promise<Record<string, unknown>> {
  if (Object.keys(args).some((key) => !requestFields.has(key)))
    return { success: false, error: "Failed to collect location evidence: unsupported argument" };
  const start = normalizeBound(args.start), end = normalizeBound(args.end);
  if (!start || !end || start >= end) return { success: false, error: "Failed to collect location evidence: start and end require ordered ISO 8601 timestamps with UTC offsets" };
  const window = { start, end, start_inclusive: true, end_inclusive: false };
  const limits = { window_seconds: args.max_window_seconds ?? 86_400, events: args.max_events ?? 1000,
    calls: args.max_calls ?? 20, elapsed_ms: args.max_elapsed_ms ?? 30_000 } as EvidenceDocument;
  for (const [field, maximum] of Object.entries(requestLimits)) {
    if (args[field] !== undefined && (!Number.isInteger(args[field]) || (args[field] as number) < 1 || (args[field] as number) > maximum))
      return { success: false, error: `Failed to collect location evidence: ${field} must be an integer from 1 to ${maximum}` };
  }
  const products = args.products === undefined ? ["network", "protect"] : args.products;
  if (!Array.isArray(products) || !products.length || products.some((p) => !["network", "protect", "access"].includes(p)) ||
      new Set(products).size !== products.length)
    return { success: false, error: "Failed to collect location evidence: products must be a unique nonempty list" };
  if (args.location_id !== undefined && args.location_id !== null && !isLabel(args.location_id, MAX_LABEL_LENGTH))
    return { success: false, error: `Failed to collect location evidence: location_id must be 1-${MAX_LABEL_LENGTH} characters ${labelRule}` };
  const detail = args.detail ?? "view";
  if (detail !== "view" && detail !== "full")
    return { success: false, error: "Failed to collect location evidence: detail must be view or full" };
  const maxRecords = args.max_records_returned ?? null;
  if (maxRecords !== null && (!Number.isInteger(maxRecords) || (maxRecords as number) < 1 || (maxRecords as number) > MAX_RECORDS_RETURNED))
    return { success: false, error: `Failed to collect location evidence: max_records_returned must be an integer from 1 to ${MAX_RECORDS_RETURNED}` };
  const resumeAfter = args.resume_after ?? null;
  if (resumeAfter !== null && !cursorKey(resumeAfter))
    return { success: false, error: "Failed to collect location evidence: resume_after must be a next_cursor value returned by an evidence view" };
  if ((maxRecords !== null || resumeAfter !== null) && detail === "full")
    return { success: false, error: "Failed to collect location evidence: max_records_returned and resume_after apply only to detail=view" };
  const mappings = normalizeMappings(args.mappings);
  if (typeof mappings === "string") return { success: false, error: `Failed to collect location evidence: ${mappings}` };
  const rawMacs = args.device_macs ?? [], rawCameras = args.camera_ids ?? [];
  // A count over its limit is reported as such, apart from identifiers that are malformed.
  if (Array.isArray(rawMacs) && rawMacs.length > MAX_FILTER_IDS)
    return { success: false, error: `Failed to collect location evidence: device_macs must list at most ${MAX_FILTER_IDS} MAC addresses` };
  if (!Array.isArray(rawMacs) || rawMacs.some((value) => typeof value !== "string" || !normalizeMac(value)))
    return { success: false, error: "Failed to collect location evidence: device_macs must be MAC addresses (six hex pairs)" };
  if (Array.isArray(rawCameras) && rawCameras.length > MAX_CAMERA_IDS)
    return { success: false, error: `Failed to collect location evidence: camera_ids must list at most ${MAX_CAMERA_IDS} camera IDs` };
  if (!Array.isArray(rawCameras) || rawCameras.some((value) => typeof value !== "string" || !/^[A-Za-z0-9._:-]{1,64}$/.test(value)))
    return { success: false, error: "Failed to collect location evidence: camera_ids must be exact Protect camera IDs" };
  const deviceMacs = [...new Set(rawMacs.map((value: string) => normalizeMac(value)!))].sort(compare);
  const cameraIds = [...new Set(rawCameras as string[])].sort(compare);
  const selected = targets.filter((target) => !args.location_id || target.location_id === args.location_id);
  if (args.location_id && !selected.length)
    return { success: false, error: `Failed to collect location evidence: unknown location_id ${boundedLabel(args.location_id as string)}; ` +
      "location_id is the location's UUID from the location list, not its name" };
  const locations = selected.length ? [...new Set(selected.map((target) => target.location_id))] : [String(args.location_id ?? "")];
  const perLocation = (products as string[]).reduce((sum, product) => sum + (product === "protect" ? Math.max(1, cameraIds.length) : 1), 0);
  if (locations.length * perLocation > MAX_TIMELINE_SOURCES)
    return { success: false, error: `Failed to collect location evidence: a call reads at most ${MAX_TIMELINE_SOURCES} sources, ` +
      `and ${locations.length} locations × ${perLocation} sources each is ${locations.length * perLocation}; ` +
      "select one location_id, or fewer products or camera_ids" };
  const tasks: Array<{ product: "network" | "protect" | "access"; locationId: string | null; target?: EvidenceTarget }> = [];
  for (const location of locations) for (const product of products as Array<"network" | "protect" | "access">) {
    tasks.push({ product, locationId: location || null, target: selected.find((target) => target.location_id === location && target.product === product) });
  }
  const documents = await Promise.all(tasks.map(async ({ product, locationId, target }): Promise<EvidenceDocument> => {
    const failure = (kind: TransportFailure, http_status: number | null = null) =>
      failedDocument(product, { kind, http_status }, window, limits, mappings, locationId, args.start as string, args.end as string);
    if (product === "access") return failure("unsupported");
    if (!target) return failure("unavailable");
    if (!target.available) return failure("unsupported");
    const parameters: Record<string, unknown> = {
      start: args.start, end: args.end, location_id: locationId,
      max_window_seconds: limits.window_seconds, max_events: limits.events, max_calls: limits.calls,
      max_elapsed_ms: limits.elapsed_ms, mappings, detail: "full",
    };
    if (product === "network") parameters.device_macs = deviceMacs;
    else parameters.camera_ids = cameraIds;
    let response: unknown;
    try { response = await call(target, evidenceTools[product], parameters); }
    catch (error) { const classified = classifyTransport(error); return failure(classified.kind, classified.http_status); }
    if (response === null) return failure("unsupported");
    if (response && typeof response === "object" && (response as EvidenceDocument).success === false) return failure("unavailable");
    try {
      if (!response || typeof response !== "object" || (response as EvidenceDocument).success !== true) return failure("parse_failed");
      const doc = await validateIncidentEvidence((response as EvidenceDocument).data);
      if (!equal(doc.requested_window, window) || !equal(doc.budgets.limits, limits) || !equal(doc.mappings, mappings) ||
          doc.sources.some((source: EvidenceDocument) => source.product !== product || source.scope.location_id !== locationId))
        return failure("parse_failed");
      return doc;
    } catch { return failure("parse_failed"); }
  }));
  let combined: EvidenceDocument;
  try { combined = await combineIncidentEvidence(documents); }
  catch { return { success: false, error: "Failed to combine location incident evidence: conflicting or invalid evidence" }; }
  if (detail === "full") return { success: true, data: combined };
  try {
    return { success: true, data: await incidentEvidenceView(combined, (maxRecords as number | null) ?? undefined, resumeAfter as string | null) };
  } catch (error) {
    if (error instanceof EvidenceViewTooLargeError) return { success: false, error: `Failed to collect location evidence: ${error.message}` };
    throw error;
  }
}
