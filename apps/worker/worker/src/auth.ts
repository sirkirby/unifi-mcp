// src/auth.ts

/**
 * Constant-time string comparison to prevent timing attacks.
 * Pads both strings to the max length, XORs all bytes, no early exit.
 */
export function timingSafeEqual(a: string, b: string): boolean {
  const maxLen = Math.max(a.length, b.length);
  let result = 0;

  for (let i = 0; i < maxLen; i++) {
    const charA = i < a.length ? a.charCodeAt(i) : 0;
    const charB = i < b.length ? b.charCodeAt(i) : 0;
    result |= charA ^ charB;
  }

  // Also fold in length difference to catch length mismatches
  result |= a.length ^ b.length;

  return result === 0;
}

/**
 * Validates a Bearer token from the Authorization header.
 * Extracts the token and compares it to the expected token using
 * constant-time comparison.
 */
export function validateBearerToken(request: Request, expectedToken: string): boolean {
  const authHeader = request.headers.get("Authorization");
  if (!authHeader) {
    return false;
  }

  const parts = authHeader.split(" ");
  if (parts.length !== 2 || parts[0].toLowerCase() !== "bearer") {
    return false;
  }

  const token = parts[1];
  return timingSafeEqual(token, expectedToken);
}

/**
 * Extracts a Bearer token from the Authorization header.
 * Returns the token string, or null if the header is missing or malformed.
 */
export function extractBearerToken(request: Request): string | null {
  const authHeader = request.headers.get("Authorization");
  if (!authHeader) {
    return null;
  }

  const parts = authHeader.split(" ");
  if (parts.length !== 2 || parts[0].toLowerCase() !== "bearer") {
    return null;
  }

  return parts[1] || null;
}

/**
 * Computes a SHA-256 hash of the given token using the Web Crypto API.
 * Returns the hash as a lowercase hex string (64 characters).
 */
export async function hashToken(token: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(token);
  const hashBuffer = await crypto.subtle.digest("SHA-256", data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map((b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * Generates a cryptographically random token of 32 bytes,
 * encoded as URL-safe base64 (no +, /, or = characters).
 */
export function generateToken(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  const base64 = btoa(String.fromCharCode(...bytes));
  // Convert to URL-safe base64 and strip padding
  return base64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");
}
