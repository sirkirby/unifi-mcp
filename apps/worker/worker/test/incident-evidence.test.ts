import { describe, expect, it, vi } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import Ajv from "ajv";
import schema from "../../../../tests/fixtures/incident_evidence/incident-evidence.v1.schema.json";
import viewSchema from "../../../../tests/fixtures/incident_evidence/incident-evidence-view.v1.schema.json";
import {
  canonicalIncidentEvidence, collectIncidentEvidence, combineIncidentEvidence, estimatedTokens, incidentEvidenceView,
  MAX_TIMELINE_SOURCES, validateIncidentEvidence, VIEW_TOKEN_BUDGET,
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
  it.each(bounded)("fits every page of %s to Core's output budget exactly", async (name) => {
    const fixture = read("view-bounds", name);
    const limits = new Set<string>();
    for (const { max_records_returned: limit, resume_after: cursor, expected } of fixture.views) {
      const actual = await incidentEvidenceView(fixture.evidence, limit, cursor);
      expect(expectedCanonical(actual)).toBe(expectedCanonical(expected));
      expect(viewSchemaCheck(actual)).toBe(true);
      expect(estimatedTokens({ success: true, data: actual })).toBeLessThanOrEqual(VIEW_TOKEN_BUDGET);
      limits.add(String(actual.record_selection.limited_by));
    }
    expect(limits.size).toBeGreaterThan(1);
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
  it("represents no matching relays with explicit unavailable sources", async () => {
    const call = vi.fn();
    const result = await collectIncidentEvidence({ ...request, location_id: "fixture-missing" }, targets, call);
    expect(call).not.toHaveBeenCalled();
    expect((result.data as any).sources.map((source: any) => source.outcome)).toEqual(["unavailable", "unavailable"]);
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
