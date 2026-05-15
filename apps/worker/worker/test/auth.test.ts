// test/auth.test.ts
import { describe, it, expect } from "vitest";
import {
  timingSafeEqual,
  validateBearerToken,
  extractBearerToken,
  hashToken,
  generateToken,
} from "../src/auth";

// ---------------------------------------------------------------------------
// timingSafeEqual
// ---------------------------------------------------------------------------
describe("timingSafeEqual", () => {
  it("returns true for equal strings", () => {
    expect(timingSafeEqual("hello", "hello")).toBe(true);
  });

  it("returns false for different strings of the same length", () => {
    expect(timingSafeEqual("hello", "world")).toBe(false);
  });

  it("returns false for strings of different lengths", () => {
    expect(timingSafeEqual("short", "longer-string")).toBe(false);
    expect(timingSafeEqual("longer-string", "short")).toBe(false);
  });

  it("returns true for two empty strings", () => {
    expect(timingSafeEqual("", "")).toBe(true);
  });

  it("returns false when one string is empty and the other is not", () => {
    expect(timingSafeEqual("", "nonempty")).toBe(false);
    expect(timingSafeEqual("nonempty", "")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// validateBearerToken
// ---------------------------------------------------------------------------
describe("validateBearerToken", () => {
  function makeRequest(headers: Record<string, string>): Request {
    return new Request("https://example.com", { headers });
  }

  it("returns true when the Bearer token matches", () => {
    const req = makeRequest({ Authorization: "Bearer mysecrettoken" });
    expect(validateBearerToken(req, "mysecrettoken")).toBe(true);
  });

  it("returns false when the Bearer token does not match", () => {
    const req = makeRequest({ Authorization: "Bearer wrongtoken" });
    expect(validateBearerToken(req, "mysecrettoken")).toBe(false);
  });

  it("returns false when the Authorization header is missing", () => {
    const req = makeRequest({});
    expect(validateBearerToken(req, "mysecrettoken")).toBe(false);
  });

  it("returns false for a non-Bearer scheme (e.g., Basic)", () => {
    const req = makeRequest({ Authorization: "Basic dXNlcjpwYXNz" });
    expect(validateBearerToken(req, "dXNlcjpwYXNz")).toBe(false);
  });

  it("returns false for a malformed Authorization header (no space)", () => {
    const req = makeRequest({ Authorization: "BearerNoSpace" });
    expect(validateBearerToken(req, "BearerNoSpace")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// extractBearerToken
// ---------------------------------------------------------------------------
describe("extractBearerToken", () => {
  function makeRequest(headers: Record<string, string>): Request {
    return new Request("https://example.com", { headers });
  }

  it("extracts the Bearer token from the Authorization header", () => {
    const req = makeRequest({ Authorization: "Bearer my-relay-token-abc" });
    expect(extractBearerToken(req)).toBe("my-relay-token-abc");
  });

  it("returns null when the Authorization header is missing", () => {
    const req = makeRequest({});
    expect(extractBearerToken(req)).toBeNull();
  });

  it("returns null for a non-Bearer scheme", () => {
    const req = makeRequest({ Authorization: "Basic dXNlcjpwYXNz" });
    expect(extractBearerToken(req)).toBeNull();
  });

  it("returns null for a malformed header (no space)", () => {
    const req = makeRequest({ Authorization: "BearerNoSpace" });
    expect(extractBearerToken(req)).toBeNull();
  });

  it("is case-insensitive for the Bearer scheme", () => {
    const req = makeRequest({ Authorization: "bearer my-token" });
    expect(extractBearerToken(req)).toBe("my-token");
  });
});

// ---------------------------------------------------------------------------
// hashToken
// ---------------------------------------------------------------------------
describe("hashToken", () => {
  it("returns a 64-character lowercase hex string", async () => {
    const hash = await hashToken("test-token");
    expect(hash).toHaveLength(64);
    expect(hash).toMatch(/^[0-9a-f]{64}$/);
  });

  it("produces the same hash for the same input (deterministic)", async () => {
    const hash1 = await hashToken("consistent-input");
    const hash2 = await hashToken("consistent-input");
    expect(hash1).toBe(hash2);
  });

  it("produces different hashes for different inputs", async () => {
    const hash1 = await hashToken("token-a");
    const hash2 = await hashToken("token-b");
    expect(hash1).not.toBe(hash2);
  });
});

// ---------------------------------------------------------------------------
// generateToken
// ---------------------------------------------------------------------------
describe("generateToken", () => {
  it("produces a URL-safe base64 string (no +, /, or = characters)", () => {
    const token = generateToken();
    expect(token).not.toMatch(/[+/=]/);
  });

  it("uses only URL-safe base64 characters", () => {
    const token = generateToken();
    expect(token).toMatch(/^[A-Za-z0-9\-_]+$/);
  });

  it("generates unique tokens on successive calls", () => {
    const token1 = generateToken();
    const token2 = generateToken();
    expect(token1).not.toBe(token2);
  });

  it("generates a token of the expected length (43 chars for 32 bytes URL-safe base64)", () => {
    const token = generateToken();
    // 32 bytes -> 44 base64 chars -> 43 after stripping one padding '='
    expect(token.length).toBe(43);
  });
});
