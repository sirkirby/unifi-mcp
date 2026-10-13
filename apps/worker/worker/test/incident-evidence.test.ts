import { describe, expect, it, vi } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import Ajv from "ajv";
import schema from "../../../../tests/fixtures/incident_evidence/incident-evidence.v1.schema.json";
import viewSchema from "../../../../tests/fixtures/incident_evidence/incident-evidence-view.v1.schema.json";
import {
  canonicalIncidentEvidence, collectIncidentEvidence, combineIncidentEvidence, estimatedTokens, EvidenceViewTooLargeError,
  incidentEvidenceView, MAX_TIMELINE_SOURCES, serializedBytes, validateIncidentEvidence, VIEW_BYTE_LIMIT, VIEW_TOKEN_BUDGET,
} from "../src/incident-evidence";
import { validateEvidenceSchema } from "../src/incident-evidence-schema.js";
import type { EvidenceTarget } from "../src/types";

const corpus = fileURLToPath(String(new URL("../../../../tests/fixtures/incident_evidence/", import.meta.url)));
const read = (group: string, name: string): any => JSON.parse(readFileSync(`${corpus}/${group}/${name}`, "utf8"));
const cases = readdirSync(`${corpus}/cases`).filter((name) => name.endsWith(".json"));
const invalid = readdirSync(`${corpus}/invalid`).filter((name) => name.endsWith(".json"));
const combine = readdirSync(`${corpus}/combine`).filter((name) => name.endsWith(".json"));
const views = readdirSync(`${corpus}/views`).filter((name) => name.endsWith(".json"));
const bounded = readdirSync(`${corpus}/view-bounds`).filter((name) => name.endsWith(".json"));
const schemaCheck = new Ajv({ strict: false }).compile(schema);
const viewSchemaCheck = new Ajv({ strict: false }).compile(viewSchema);

function fixtureEvidence(name: string): any { return read("cases", name).expected; }
/** A view as an MCP server sends it fits the token budget and byte cap, and `serializedBytes` never undercounts it. */
function expectFits(view: unknown): void {
  const result = { success: true, data: view };
  expect(estimatedTokens(result)).toBeLessThanOrEqual(VIEW_TOKEN_BUDGET);
  expect(Buffer.byteLength(JSON.stringify(result, null, 2))).toBeLessThanOrEqual(serializedBytes(result));
  expect(serializedBytes(result)).toBeLessThanOrEqual(VIEW_BYTE_LIMIT);
}
function expectedCanonical(value: any): string {
  if (Array.isArray(value)) return `[${value.map(expectedCanonical).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.keys(value).sort().map((key) =>
    `${expectedCanonical(key)}:${expectedCanonical(value[key])}`).join(",")}}`;
  return JSON.stringify(value).replace(/[\u007f-\uffff]/g, (character) =>
    `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`);
}

describe("incident evidence corpus", () => {
  it("ships a validator generated from the committed schema", () => {
    const script = fileURLToPath(String(new URL("../scripts/generate-incident-evidence-schema.mjs", import.meta.url)));
    expect(() => execFileSync(process.execPath, [script, "--check"])).not.toThrow();
  });
  it.each(cases)("accepts %s", async (name) => {
    expect(validateEvidenceSchema(fixtureEvidence(name))).toBe(true);
    await expect(validateIncidentEvidence(fixtureEvidence(name))).resolves.toEqual(fixtureEvidence(name));
    expect(await canonicalIncidentEvidence(fixtureEvidence(name))).toBe(expectedCanonical(fixtureEvidence(name)));
  });
  it.each(invalid)("rejects %s at its declared layer", async (name) => {
    const fixture = read("invalid", name);
    expect(schemaCheck(fixture.evidence)).toBe(fixture.rejected_by === "semantic");
    expect(validateEvidenceSchema(fixture.evidence)).toBe(fixture.rejected_by === "semantic");
    await expect(validateIncidentEvidence(fixture.evidence)).rejects.toThrow(
      fixture.rejected_by === "schema" ? "schema" : /Invalid incident evidence: (?!schema)/,
    );
  });
  it.each(combine)("combines %s", async (name) => {
    const fixture = read("combine", name);
    if (fixture.error) await expect(combineIncidentEvidence(fixture.inputs)).rejects.toThrow();
    else {
      const actual = await combineIncidentEvidence(fixture.inputs);
      expect(actual).toEqual(fixture.expected);
      expect(await canonicalIncidentEvidence(actual)).toBe(expectedCanonical(fixture.expected));
    }
  });
  it.each(views)("projects %s exactly as Core's client view", async (name) => {
    const fixture = read("views", name);
    expect(fixture.views.length).toBeGreaterThan(0);
    for (const { max_records_returned: limit, resume_after: cursor, expected } of fixture.views) {
      const actual = await incidentEvidenceView(fixtureEvidence(name), limit, cursor);
      expect(actual).toEqual(expected);
      expect(expectedCanonical(actual)).toBe(expectedCanonical(expected));
      expect(viewSchemaCheck(actual)).toBe(true);
    }
  });
  it("cites each version's own conflict group right after its evidence ID, and nothing else names one", async () => {
    let versions = 0;
    for (const name of ["conflicting_versions.json", "tool_response_envelopes.json"]) {
      const view = await incidentEvidenceView(fixtureEvidence(name), 50);
      for (const record of view.records) {
        const base = record.evidence_id.replace(/\|version\|[0-9a-f]{24}$/, "");
        if (base === record.evidence_id) {
          expect(Object.keys(record)).not.toContain("conflict_group");
          continue;
        }
        versions += 1;
        expect(Object.keys(record).slice(0, 2)).toEqual(["evidence_id", "conflict_group"]);
        expect(record.conflict_group).toBe(base);
        // The view schema refuses a version without its group, and a group on anything but a version.
        const { conflict_group: _group, ...ungrouped } = record;
        expect(viewSchemaCheck({ ...view, records: [ungrouped] })).toBe(false);
        expect(viewSchemaCheck({ ...view, records: [{ ...record, evidence_id: base }] })).toBe(false);
      }
    }
    // Both identity bases conflict: a typed source record ID and a summary-free tool read.
    expect(versions).toBeGreaterThan(2);
    const fields = (await incidentEvidenceView(fixtureEvidence("tool_response_envelopes.json"), 50)).records
      .filter((record: any) => /\|fields\|[0-9a-f]{24}\|version\|/.test(record.evidence_id));
    expect(fields.length).toBeGreaterThan(1);
  });
  it("refuses a document whose version names another identity's conflict group", async () => {
    const doc = structuredClone(fixtureEvidence("tool_response_envelopes.json"));
    const versions = doc.records.filter((record: any) => record.conflict_group !== null);
    const other = doc.records.find((record: any) => record.conflict_group === null && record.evidence_id_basis !== "content_hash");
    versions[0].conflict_group = other ? other.evidence_id : `${versions[0].source_id}|fields|${"0".repeat(24)}`;
    await expect(validateIncidentEvidence(doc)).rejects.toThrow("conflict group");
  });
  it.each(bounded)("fits every page of %s to Core's output budget exactly", async (name) => {
    const fixture = read("view-bounds", name);
    if (fixture.refusal !== undefined) {
      await expect(incidentEvidenceView(fixture.evidence)).rejects.toThrow(new EvidenceViewTooLargeError(fixture.refusal));
      return;
    }
    const limits = new Set<string>();
    for (const { max_records_returned: limit, resume_after: cursor, expected } of fixture.views) {
      const actual = await incidentEvidenceView(fixture.evidence, limit, cursor);
      expect(expectedCanonical(actual)).toBe(expectedCanonical(expected));
      expect(viewSchemaCheck(actual)).toBe(true);
      expectFits(actual);
      limits.add(String(actual.record_selection.limited_by));
    }
    expect(limits.size).toBeGreaterThan(1);
  });
  it("fits any document's view to the budget, or refuses it, however long its labels or many its sources", async () => {
    // Core's property test, drawn from the largest location: oversized labels in every source and record,
    // assertions with oversized identifiers, and added sources, as a relay outside request validation could send.
    const base = read("view-bounds", "output_budget.json").evidence;
    expect(base.overall).toBe("partial");
    let seed = 794;
    const random = (): number => {
      seed = (seed + 0x6d2b79f5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    const pick = <T,>(values: readonly T[]): T => values[Math.floor(random() * values.length)];
    // Core's alphabet, often repeated in long runs: escaped, whitespace, punctuation and two- to four-byte characters.
    const alphabet = ['"', "\\", "\u0001", "\n", "\t", "\u{1f600}", "\u{20000}", "\u00e9", "\u4e2d", " ", " ", "\u00a0",
      "\u3000", "a", "7", "~", "%", "|"];
    const runs = [...Array(12).fill(1), 16, 300];
    const text = (length: number): string => {
      const characters: string[] = [];
      while (characters.length < length) characters.push(...Array(pick(runs)).fill(pick(alphabet)));
      return characters.slice(0, length).join("");
    };
    const outcomes = { view: 0, cut: 0, refused: 0 };
    for (let draw = 0; draw < 40; draw++) {
      const evidence = structuredClone(base);
      const labels = Object.fromEntries(["controller_id", "site", "location_id", "source_tool"]
        .filter(() => random() < 0.5).map((field) => [field, text(pick([0, 128, 513, 30_000]))]));
      const relabel = (item: any): void => {
        for (const [field, value] of Object.entries(labels)) {
          if (field === "source_tool") item.source_tool = value; else item.scope[field] = value;
        }
      };
      evidence.sources.forEach(relabel);
      evidence.records.forEach((record: any) => relabel(record.provenance));
      const assertions = pick([0, 0, 8, 40]);
      for (let index = 0; index < assertions; index++) evidence.mappings.push({
        entity: { kind: "location", id_kind: "location_id", id: `fixture-${text(pick([1, 64, 3_000]))}`, role: null },
        target: { kind: "location", id_kind: "location_id", id: "fixture-location", role: null }, source: "operator_input" });
      const failed = evidence.sources[0];
      expect(failed.outcome).toBe("unsupported");
      const added = pick([0, 0, 20, 150]);
      for (let index = 0; index < added; index++)
        evidence.sources.push({ ...structuredClone(failed), source_id: `${failed.source_id}.${String(index).padStart(4, "0")}` });
      evidence.sources.sort((a: any, b: any) => (a.source_id < b.source_id ? -1 : 1));
      let view: any;
      try { view = await incidentEvidenceView(evidence, pick([1, 25, 50])); }
      catch (error) {
        expect(error).toBeInstanceOf(EvidenceViewTooLargeError);
        // Labels are cut, never refused: only sources and assertions can fill the budget.
        expect(assertions + added).toBeGreaterThan(0);
        expect((error as Error).message).not.toContain("fixture");
        outcomes.refused += 1;
        continue;
      }
      outcomes.view += 1;
      expect(viewSchemaCheck(view)).toBe(true);
      expectFits(view);
      expect([view.overall, view.coverage_complete]).toEqual([evidence.overall, evidence.coverage_complete]);
      view.sources.forEach((shown: any, index: number) => {
        const source = evidence.sources[index];
        expect([shown.outcome, shown.failure, shown.coverage]).toEqual([source.outcome, source.failure, source.coverage]);
        for (const [field, full] of [["source_tool", source.source_tool], ...Object.entries(source.scope)] as Array<[string, any]>) {
          const kept = field === "source_tool" ? shown.source_tool : shown.scope[field];
          if (field in shown.truncated) {
            expect(full.startsWith(kept) && kept !== full && shown.truncated[field] === Array.from(full).length).toBe(true);
          } else expect(kept).toBe(full);
        }
      });
      outcomes.cut += Number(view.sources.some((source: any) => Object.keys(source.truncated).length));
    }
    expect(Object.values(outcomes).every(Boolean)).toBe(true);
  });
  it("costs every string a token per byte it is sent in, however degenerate", () => {
    const degenerate = ["A" + " ".repeat(4_000_000) + "B", "\t".repeat(50_000), "!".repeat(100_000), "~-.|".repeat(25_000),
      "qxzjvkwQXZJVKW".repeat(7_000), "\u00a0".repeat(50_000), "\u3000".repeat(50_000), "\u4e2d\u6587".repeat(25_000),
      "\u{1f600}\u{1f9ea}".repeat(12_500), "\u{20000}".repeat(25_000), "\u0001\"\\".repeat(10_000)];
    for (const value of degenerate) {
      const sent = Buffer.byteLength(JSON.stringify(value));
      expect([estimatedTokens(value), serializedBytes(value)]).toEqual([sent, sent]);
    }
    const nested = { success: true, data: { records: [{ summary: degenerate[0], ids: ["a", 7, -12, 1.5, null, false] }], empty: {} } };
    // Exact but for numbers, counted at their longest form: 7 and -12 as digits plus three, 1.5 as 24 bytes.
    expect(serializedBytes(nested) - Buffer.byteLength(JSON.stringify(nested, null, 2))).toBe(3 + 2 + 21);
  });
  it("refuses a cursor that no view returned", async () => {
    await expect(incidentEvidenceView(fixtureEvidence("healthy_empty.json"), 2, "0|not-a-time|network.events|int|7"))
      .rejects.toThrow("cursor");
  });
  it("accepts Python integral-float digests after JavaScript parses the wire numbers", async () => {
    const wire = readFileSync(`${corpus}/cases/canonical_numbers.json`, "utf8");
    expect(wire).toContain('"score": 1.0');
    const document = JSON.parse(wire).expected;
    expect(document.records[0].attributes.score).toBe(1);
    await expect(validateIncidentEvidence(document)).resolves.toEqual(document);
    const integerWire = wire.replaceAll('"score": 1.0', '"score": 1');
    await expect(validateIncidentEvidence(JSON.parse(integerWire).expected)).resolves.toEqual(document);
  });
  it("requires source proof after post-filtering even when the reported total is exhausted", async () => {
    const altered = structuredClone(fixtureEvidence("healthy_empty.json"));
    const source = altered.sources[0];
    source.coverage.pagination.post_filtered = true;
    source.coverage.pagination.has_more = null;
    source.coverage.pagination.total_reported = 0;
    await expect(validateIncidentEvidence(altered)).rejects.toThrow();
  });
  it("checks source identity and collection time even when no record cites the source", async () => {
    const invalidId = structuredClone(fixtureEvidence("healthy_empty.json"));
    invalidId.sources[0].source_id = "INVALID SOURCE";
    await expect(validateIncidentEvidence(invalidId)).rejects.toThrow();
    const invalidTime = structuredClone(fixtureEvidence("healthy_empty.json"));
    invalidTime.sources[0].collected_at = "2026-02-30T13:05:00.000000Z";
    await expect(validateIncidentEvidence(invalidTime)).rejects.toThrow();
  });
});

describe("location evidence collection", () => {
  const targets: EvidenceTarget[] = [
    { location_id: "fixture-1", product: "network", available: true },
    { location_id: "fixture-1", product: "protect", available: true },
  ];
  const request = { start: "2026-08-08T12:00:00Z", end: "2026-08-08T13:00:00Z",
    max_window_seconds: 7200, max_events: 500, max_calls: 10, max_elapsed_ms: 60000, detail: "full" };
  function productDocument(product: string): any {
    const evidence = structuredClone(fixtureEvidence("healthy_empty.json"));
    evidence.sources = evidence.sources.filter((source: any) => source.product === product);
    evidence.sources[0].scope.location_id = "fixture-1";
    return evidence;
  }
  it("collects numeric evidence without replacing it with a parse failure", async () => {
    const document = structuredClone(fixtureEvidence("canonical_numbers.json"));
    for (const source of document.sources) source.scope.location_id = "fixture-1";
    for (const record of document.records) record.provenance.scope.location_id = "fixture-1";
    const call = vi.fn(async () => ({ success: true, data: document }));
    const result = await collectIncidentEvidence({ ...request, products: ["protect"] }, targets, call);
    expect(result.success).toBe(true);
    expect((result.data as any).sources[0].failure).toBeNull();
    expect((result.data as any).records).toEqual(document.records);
  });
  it("sends exact windows and budgets and returns one combined contract document", async () => {
    const call = vi.fn(async (target: EvidenceTarget, _tool: string, _parameters: Record<string, unknown>) =>
      ({ success: true, data: productDocument(target.product) }));
    const result = await collectIncidentEvidence({ ...request, device_macs: ["AA-BB-CC-00-10-01"], camera_ids: ["cam-fixture-000a"] }, targets, call);
    expect(call).toHaveBeenCalledTimes(2);
    expect(call.mock.calls.map((args) => args[1])).toEqual(["unifi_get_incident_evidence", "protect_get_incident_evidence"]);
    expect(call.mock.calls[0][2]).toMatchObject({ start: request.start, end: request.end, max_events: 500,
      device_macs: ["aa:bb:cc:00:10:01"], detail: "full" });
    expect(call.mock.calls[1][2]).toMatchObject({ camera_ids: ["cam-fixture-000a"] });
    expect(result).toMatchObject({ success: true, data: { schema: "unifi-incident-evidence", overall: "empty", coverage_complete: true } });
    expect((result.data as any).sources.map((source: any) => source.source_id)).toEqual(["network.events", "protect.events"]);
  });
  it("returns the client view of the combined document by default", async () => {
    const call = vi.fn(async (target: EvidenceTarget, _tool: string, _parameters: Record<string, unknown>) => {
      const document = structuredClone(fixtureEvidence("network_protect_real_shapes.json"));
      document.sources = document.sources.filter((source: any) => source.product === target.product);
      document.records = document.records.filter((record: any) => record.provenance.product === target.product);
      for (const source of document.sources) source.scope.location_id = "fixture-1";
      for (const record of document.records) record.provenance.scope.location_id = "fixture-1";
      document.overall = "complete";
      return { success: true, data: document };
    });
    const { detail: _, ...viewRequest } = request;
    const full = await collectIncidentEvidence({ ...viewRequest, detail: "full" }, targets, call);
    expect(full).toMatchObject({ success: true, data: { schema: "unifi-incident-evidence", overall: "complete" } });
    expect((full.data as any).records).toHaveLength(5);
    for (const limit of [undefined, 2]) {
      const result = await collectIncidentEvidence({ ...viewRequest, ...(limit ? { max_records_returned: limit } : {}) }, targets, call);
      expect(result.success).toBe(true);
      expect(result.data).toEqual(await incidentEvidenceView(full.data, limit));
      expect(viewSchemaCheck(result.data)).toBe(true);
      expect((result.data as any).record_selection.max_records_returned).toBe(limit ?? 25);
    }
    expect(call.mock.calls.every((args) => args[2]?.detail === "full")).toBe(true);
    const first = await collectIncidentEvidence({ ...viewRequest, max_records_returned: 2 }, targets, call);
    const cursor = (first.data as any).record_selection.next_cursor;
    const resumed = await collectIncidentEvidence({ ...viewRequest, max_records_returned: 2, resume_after: cursor }, targets, call);
    expect(resumed.data).toEqual(await incidentEvidenceView(full.data, 2, cursor));
    expect((resumed.data as any).record_selection.before_resume.total).toBe(2);
    expect(call.mock.calls.every((args) => !("resume_after" in args[2]))).toBe(true);
  });
  it("carries failed products inside the document, including Access", async () => {
    const result = await collectIncidentEvidence({ ...request, products: ["network", "protect", "access"] },
      [targets[0], { ...targets[1], available: false }], async () => ({ success: false, error: "private controller text" }));
    expect(result).toMatchObject({ success: true, data: { schema: "unifi-incident-evidence", overall: "failed", coverage_complete: false } });
    expect((result.data as any).sources.map((source: any) => [source.product, source.outcome])).toEqual([
      ["access", "unsupported"], ["network", "unavailable"], ["protect", "unsupported"],
    ]);
    expect(JSON.stringify(result)).not.toContain("private controller text");
  });
  it("classifies null as unsupported and invalid evidence as parse_failed", async () => {
    const result = await collectIncidentEvidence(request, targets,
      async (target) => target.product === "network" ? null : { success: true, data: {} });
    expect((result.data as any).sources.map((source: any) => source.outcome)).toEqual(["unsupported", "parse_failed"]);
  });
  it("keeps a valid empty source partial when another location fails", async () => {
    const result = await collectIncidentEvidence(request, targets,
      async (target) => target.product === "network" ? { success: true, data: productDocument("network") } : null);
    expect(result).toMatchObject({ success: true, data: { overall: "partial", coverage_complete: false } });
  });
  it("refuses an unknown location before any read and says the id is the location UUID", async () => {
    const call = vi.fn();
    const result = await collectIncidentEvidence({ ...request, location_id: "fixture-missing" }, targets, call);
    expect(call).not.toHaveBeenCalled();
    expect(result).toEqual({ success: false, error: expect.stringContaining('unknown location_id "fixture-missing"') });
    expect((result as any).error).toContain("UUID");
    expect((result as any).error).toContain("not its name");
  });
  it("echoes an unknown location_id only in a bounded, sanitized form", async () => {
    const call = vi.fn();
    const long = await collectIncidentEvidence({ ...request, location_id: `fixture-${"a".repeat(100)}` }, targets, call);
    expect((long as any).error).toContain(`"fixture-${"a".repeat(32)}…"`);
    expect((long as any).error).not.toContain("a".repeat(33));
    const odd = await collectIncidentEvidence({ ...request, location_id: "Home <b>Lab</b>\u00e9" }, targets, call);
    expect((odd as any).error).toContain('"Home ?b?Lab??b??"');
    expect(call).not.toHaveBeenCalled();
  });
  it("still reads a known location_id", async () => {
    const call = vi.fn(async () => null);
    const result = await collectIncidentEvidence({ ...request, location_id: "fixture-1" }, targets, call);
    expect(result).toMatchObject({ success: true });
    expect(call).toHaveBeenCalledTimes(2);
  });
  it("keeps failures from two locations as distinct sources", async () => {
    const result = await collectIncidentEvidence({ ...request, products: ["network"] },
      [targets[0], { ...targets[0], location_id: "fixture-2" }], async () => ({ success: false, error: "opaque" }));
    expect(result).toMatchObject({ success: true, data: { overall: "failed", coverage_complete: false } });
    const sources = (result.data as any).sources;
    expect(sources).toHaveLength(2);
    expect(new Set(sources.map((source: any) => source.source_id)).size).toBe(2);
    expect(sources.map((source: any) => source.outcome)).toEqual(["unavailable", "unavailable"]);
  });
  it("classifies typed transport failures without copying their messages", async () => {
    const result = await collectIncidentEvidence(request, targets, async (target) => {
      const error = new Error("private controller text") as Error & { status?: number };
      if (target.product === "network") error.name = "TimeoutError";
      else error.status = 403;
      throw error;
    });
    expect((result.data as any).sources.map((source: any) => source.outcome)).toEqual(["timeout", "permission_denied"]);
    expect(JSON.stringify(result)).not.toContain("private controller text");
  });
  it("refuses overlapping source IDs across locations", async () => {
    const result = await collectIncidentEvidence({ ...request, products: ["network"] },
      [targets[0], { ...targets[0], location_id: "fixture-2" }], async (target) => {
        const doc = productDocument("network");
        doc.sources[0].scope.location_id = target.location_id;
        return { success: true, data: doc };
      });
    expect(result).toMatchObject({ success: false, error: "Failed to combine location incident evidence: conflicting or invalid evidence" });
  });
  it("reports a count over its limit as such, as every other surface does", async () => {
    const call = vi.fn();
    const assertion = { entity: { kind: "camera", id_kind: "protect_camera_id", id: "cam-fixture-000a" },
      target: { kind: "network_device", id_kind: "mac", id: "02:00:00:00:00:01" }, source: "operator_input" };
    const cases: Array<[Record<string, unknown>, string]> = [
      [{ camera_ids: ["c1", "c2", "c3", "c4", "c5", "c6"] }, "camera_ids must list at most 5 camera IDs"],
      [{ camera_ids: ["front door"] }, "camera_ids must be exact Protect camera IDs"],
      [{ mappings: Array.from({ length: 21 }, () => assertion) }, "mappings must list at most 20 assertions"],
      [{ mappings: [{ ...assertion, source: "guessed" }] }, "mappings must be valid exact-identifier assertions"],
      [{ device_macs: Array.from({ length: 51 }, () => "02:00:00:00:00:01") }, "device_macs must list at most 50 MAC addresses"],
      [{ device_macs: ["fixture-ap"] }, "device_macs must be MAC addresses (six hex pairs)"],
    ];
    for (const [bad, message] of cases) {
      const result = await collectIncidentEvidence({ ...request, ...bad }, targets, call);
      expect(result).toEqual({ success: false, error: `Failed to collect location evidence: ${message}` });
    }
    expect(call).not.toHaveBeenCalled();
  });
  it("bounds labels and mapping identifiers as Core does, without echoing them", async () => {
    const call = vi.fn();
    const assertion = (id: string, extra: Record<string, unknown> = {}) => ({ entity: { kind: "network_device", id_kind: "mac",
      id: "02:00:00:00:00:01", ...extra }, target: { kind: "location", id_kind: "location_id", id }, source: "operator_input" });
    for (const [bad, message] of [
      [{ location_id: 'fixture "a"' }, "location_id must be 1-128 characters without control characters, quotes or backslashes"],
      [{ location_id: "x".repeat(129) }, "location_id must be 1-128 characters"],
      [{ mappings: [assertion("fixture-" + "~".repeat(60))] }, "mapping identifiers must be 1-64 characters"],
      [{ mappings: [assertion("fixture\\a")] }, "mapping identifiers must be 1-64 characters"],
      [{ mappings: [assertion("fixture-a", { role: "uplink" })] }, "omit role"],
      [{ resume_after: "fixture-cursor" }, "resume_after must be a next_cursor value"],
      [{ detail: "full", resume_after: "1||network.events|int|7" }, "apply only to detail=view"],
    ] as Array<[Record<string, unknown>, string]>) {
      const result = await collectIncidentEvidence({ ...request, ...bad }, targets, call);
      expect(result.success).toBe(false);
      expect(result.error).toContain(message);
      expect(result.error).not.toContain("fixture");
    }
    expect(call).not.toHaveBeenCalled();
    const accepted = await collectIncidentEvidence({ ...request, location_id: "fixture-1",
      mappings: [assertion("fixture-location-\u00e9 #2")] }, targets, async () => null);
    expect(accepted.success).toBe(true);
  });
  it("cuts and marks a relay's oversized site, keeping its view within budget", async () => {
    const network = productDocument("network");
    network.sources[0].scope.site = "-".repeat(30_000);
    const result: any = await collectIncidentEvidence({ ...request, detail: "view", products: ["network"] }, targets,
      async () => ({ success: true, data: network }));
    expect(result.success).toBe(true);
    const [source] = result.data.sources;
    expect(source.truncated).toEqual({ site: 30_000 });
    expect(source.scope.site).toBe("-".repeat(128));
    expect(source.outcome).toBe("empty");
    expect(estimatedTokens(result)).toBeLessThanOrEqual(VIEW_TOKEN_BUDGET);
  });
  it("cuts and marks four million spaces in a relay's summary and site, keeping its view within budget", async () => {
    const spaces = "A" + " ".repeat(4_000_000) + "B";
    const network = structuredClone(fixtureEvidence("network_protect_real_shapes.json"));
    network.sources = network.sources.filter((source: any) => source.product === "network");
    network.records = network.records.filter((record: any) => record.provenance.product === "network");
    network.records[0].summary = spaces;
    for (const item of [network.sources[0], ...network.records.map((record: any) => record.provenance)]) {
      item.scope.location_id = "fixture-1";
      item.scope.site = " ".repeat(4_000_000);
    }
    const result: any = await collectIncidentEvidence({ ...request, detail: "view", products: ["network"] }, targets,
      async () => ({ success: true, data: network }));
    expect(result.success).toBe(true);
    const [source] = result.data.sources;
    expect([source.truncated, source.scope.site]).toEqual([{ site: 4_000_000 }, " ".repeat(128)]);
    const record = result.data.records.find((shown: any) => shown.evidence_id === network.records[0].evidence_id);
    expect([record.truncated, record.summary]).toEqual([{ summary: spaces.length }, spaces.slice(0, 200)]);
    expectFits(result.data);
    expect(Buffer.byteLength(JSON.stringify(result, null, 2))).toBeLessThan(10_000);
  });
  it("refuses a view its sources alone would overfill, and still returns detail=full", async () => {
    const network = productDocument("network");
    network.sources = Array.from({ length: 150 }, (_, index) => ({
      ...structuredClone(network.sources[0]), source_id: `network.events.${String(index).padStart(4, "0")}` }));
    const relay = async () => ({ success: true, data: network });
    expect(await collectIncidentEvidence({ ...request, detail: "view", products: ["network"] }, targets, relay)).toEqual({
      success: false, error: "Failed to collect location evidence: the evidence view would exceed its 20000-token output " +
        "budget without any record (sources: 150, mapping assertions: 0); narrow the request to fewer sources (one " +
        "location_id, fewer products or camera_ids) or fewer mapping assertions, or use detail=full for the whole document" });
    const full: any = await collectIncidentEvidence({ ...request, products: ["network"] }, targets, relay);
    expect(full.success && full.data.sources.length).toBe(150);
  });
  it("reads at most as many sources as one location produces", async () => {
    const many = Array.from({ length: 100 }, (_, index) => [
      { location_id: `fixture-${index}`, product: "network" as const, available: true },
      { location_id: `fixture-${index}`, product: "protect" as const, available: true },
    ]).flat();
    const call = vi.fn();
    const refused = await collectIncidentEvidence(request, many, call);
    expect(refused).toEqual({ success: false, error: `Failed to collect location evidence: a call reads at most ${MAX_TIMELINE_SOURCES} sources, ` +
      "and 100 locations × 2 sources each is 200; select one location_id, or fewer products or camera_ids" });
    expect(call).not.toHaveBeenCalled();
    const cameras = ["cam-fixture-000a", "cam-fixture-000b", "cam-fixture-000c", "cam-fixture-000d", "cam-fixture-000e"];
    expect((await collectIncidentEvidence({ ...request, camera_ids: cameras, products: ["network", "protect", "access"] },
      many.slice(0, 2), async () => null)).success).toBe(true);
    expect((await collectIncidentEvidence({ ...request, camera_ids: cameras }, many.slice(0, 4), call)).success).toBe(false);
    const three = await collectIncidentEvidence({ ...request, detail: "view" }, many.slice(0, 6), async () => null);
    expect(three.success).toBe(true);
    expect(estimatedTokens(three)).toBeLessThanOrEqual(VIEW_TOKEN_BUDGET);
    expect(call).not.toHaveBeenCalled();
  });
  it("rejects legacy filters, invalid exact IDs, and ambiguous time before reads", async () => {
    const call = vi.fn();
    for (const bad of [
      { start_time: request.start }, { area_hint: "front" }, { device_macs: ["fixture-ap"] },
      { camera_ids: ["front door"] }, { start: "2026-08-08T12:00:00" }, { start: "1786190400" },
      { mappings: [{ entity: { kind: "camera", id_kind: "protect_camera_id", id: "x" }, target: {} }] },
      { camera_ids: ["c1", "c2", "c3", "c4", "c5", "c6"] }, { detail: "summary" }, { max_records_returned: 5 },
      { detail: "view", max_records_returned: 0 }, { detail: "view", max_records_returned: 51 },
      { mappings: Array.from({ length: 21 }, () => ({
        entity: { kind: "camera", id_kind: "protect_camera_id", id: "x" },
        target: { kind: "network_device", id_kind: "mac", id: "02:00:00:00:00:01" }, source: "operator_input" })) },
    ]) expect((await collectIncidentEvidence({ ...request, ...bad }, targets, call)).success).toBe(false);
    expect(call).not.toHaveBeenCalled();
  });
});
