import { randomUUID } from "node:crypto";

export function generateToken() {
  return randomUUID();
}
