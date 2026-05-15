import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { generateToken } from "../../src/lib/tokens.mjs";

describe("tokens", () => {
  it("generates a valid UUID v4 token", () => {
    const token = generateToken();
    assert.match(token, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });

  it("generates unique tokens each call", () => {
    const a = generateToken();
    const b = generateToken();
    assert.notEqual(a, b);
  });
});
