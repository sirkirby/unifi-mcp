import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { buildLocationTokenRequest, parseLocationTokenResponse } from "../../src/lib/api.mjs";

describe("api", () => {
  it("builds location token request correctly", () => {
    const req = buildLocationTokenRequest("https://relay.workers.dev", "admin-token-123", "Home Lab");
    assert.equal(req.url, "https://relay.workers.dev/api/locations/token");
    assert.equal(req.method, "POST");
    assert.equal(req.headers.Authorization, "Bearer admin-token-123");
    assert.deepEqual(req.body, { location_name: "Home Lab" });
  });

  it("strips trailing slash from worker URL", () => {
    const req = buildLocationTokenRequest("https://relay.workers.dev/", "token", "Lab");
    assert.equal(req.url, "https://relay.workers.dev/api/locations/token");
  });

  it("parses location token response with token field (worker format)", () => {
    const result = parseLocationTokenResponse({
      token: "tok-abc-123",
      location_id: "loc_xyz",
    });
    assert.equal(result.relayToken, "tok-abc-123");
    assert.equal(result.locationId, "loc_xyz");
  });

  it("parses location token response with relay_token field (spec format)", () => {
    const result = parseLocationTokenResponse({
      relay_token: "tok-abc-123",
      location_id: "loc_xyz",
    });
    assert.equal(result.relayToken, "tok-abc-123");
    assert.equal(result.locationId, "loc_xyz");
  });
});
