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
    if (p.total_reported > (p.offset ?? 0) + p.returned) return "truncated";
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
    const hash = await digest({ source_record_id: rid === null ? null : [typeof rid === "number" ? "int" : "str", rid],
      source_record_id_field: p.source_record_id_field,
      time: [record.time.original_field, record.time.original_type, record.time.original_value],
      event_type: record.event_type, summary: record.summary, entities: record.entities, attributes: record.attributes });
    const base = rid === null ? `${record.source_id}|sha256|${hash}` :
      `${record.source_id}|${typeof rid === "number" ? "int" : "str"}|${encodeURIComponent(String(rid)).replace(/[!'()*]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`)}`;
    const expected = rid === null || record.conflict_group === null ? base : `${base}|version|${hash}`;
    if (record.conflict_group !== null && (rid === null || record.conflict_group !== base)) fail("conflict group");
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

const evidenceTools = { network: "unifi_get_incident_evidence", protect: "protect_get_incident_evidence" } as const;
const requestLimits = { max_window_seconds: 30 * 24 * 3600, max_events: 10_000, max_calls: 100, max_elapsed_ms: 120_000 };
const requestFields = new Set(["start", "end", "location_id", "products", "device_macs", "camera_ids", "mappings", ...Object.keys(requestLimits)]);
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
function normalizeMappings(value: unknown): EvidenceDocument[] | null | undefined {
  if (value === undefined || value === null) return null;
  if (!Array.isArray(value) || value.some((assertion) => !validateMappingAssertion(assertion))) return undefined;
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
      counts: zeros, complete: false, population_total: null },
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
  if (args.location_id !== undefined && args.location_id !== null && (typeof args.location_id !== "string" || !args.location_id || args.location_id.length > 128))
    return { success: false, error: "Failed to collect location evidence: location_id must be a nonempty string" };
  const mappings = normalizeMappings(args.mappings);
  if (mappings === undefined) return { success: false, error: "Failed to collect location evidence: mappings must be valid exact-identifier assertions" };
  const rawMacs = args.device_macs ?? [], rawCameras = args.camera_ids ?? [];
  if (!Array.isArray(rawMacs) || rawMacs.length > 50 || rawMacs.some((value) => typeof value !== "string" || !normalizeMac(value)))
    return { success: false, error: "Failed to collect location evidence: device_macs must be MAC addresses (six hex pairs)" };
  if (!Array.isArray(rawCameras) || rawCameras.length > 50 || rawCameras.some((value) => typeof value !== "string" || !/^[A-Za-z0-9._:-]{1,64}$/.test(value)))
    return { success: false, error: "Failed to collect location evidence: camera_ids must be exact Protect camera IDs" };
  const deviceMacs = [...new Set(rawMacs.map((value: string) => normalizeMac(value)!))].sort(compare);
  const cameraIds = [...new Set(rawCameras as string[])].sort(compare);
  const selected = targets.filter((target) => !args.location_id || target.location_id === args.location_id);
  const locations = selected.length ? [...new Set(selected.map((target) => target.location_id))] : [String(args.location_id ?? "")];
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
      max_elapsed_ms: limits.elapsed_ms, mappings,
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
  try { return { success: true, data: await combineIncidentEvidence(documents) }; }
  catch { return { success: false, error: "Failed to combine location incident evidence: conflicting or invalid evidence" }; }
}
