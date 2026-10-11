import { describe, expect, it, vi } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import Ajv from "ajv";
import schema from "../../../../tests/fixtures/incident_evidence/incident-evidence.v1.schema.json";
import { canonicalIncidentEvidence, collectIncidentEvidence, combineIncidentEvidence, validateIncidentEvidence } from "../src/incident-evidence";
import { validateEvidenceSchema } from "../src/incident-evidence-schema.js";
import type { EvidenceTarget } from "../src/types";

const corpus = fileURLToPath(String(new URL("../../../../tests/fixtures/incident_evidence/", import.meta.url)));
const read = (group: string, name: string): any => JSON.parse(readFileSync(`${corpus}/${group}/${name}`, "utf8"));
const cases = readdirSync(`${corpus}/cases`).filter((name) => name.endsWith(".json"));
const invalid = readdirSync(`${corpus}/invalid`).filter((name) => name.endsWith(".json"));
const combine = readdirSync(`${corpus}/combine`).filter((name) => name.endsWith(".json"));
const schemaCheck = new Ajv({ strict: false }).compile(schema);

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
    max_window_seconds: 7200, max_events: 500, max_calls: 10, max_elapsed_ms: 60000 };
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
      device_macs: ["aa:bb:cc:00:10:01"] });
    expect(call.mock.calls[1][2]).toMatchObject({ camera_ids: ["cam-fixture-000a"] });
    expect(result).toMatchObject({ success: true, data: { schema: "unifi-incident-evidence", overall: "empty", coverage_complete: true } });
    expect((result.data as any).sources.map((source: any) => source.source_id)).toEqual(["network.events", "protect.events"]);
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
  it("rejects legacy filters, invalid exact IDs, and ambiguous time before reads", async () => {
    const call = vi.fn();
    for (const bad of [
      { start_time: request.start }, { area_hint: "front" }, { device_macs: ["fixture-ap"] },
      { camera_ids: ["front door"] }, { start: "2026-08-08T12:00:00" }, { start: "1786190400" },
      { mappings: [{ entity: { kind: "camera", id_kind: "protect_camera_id", id: "x" }, target: {} }] },
    ]) expect((await collectIncidentEvidence({ ...request, ...bad }, targets, call)).success).toBe(false);
    expect(call).not.toHaveBeenCalled();
  });
});
