import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { assertWorkerName, resolveCommand } from "../../src/lib/command.mjs";

describe("resolveCommand", () => {
  it("runs the command directly outside Windows", () => {
    for (const platform of ["linux", "darwin"]) {
      assert.deepEqual(resolveCommand("wrangler", ["whoami"], platform), {
        file: "wrangler",
        args: ["whoami"],
        options: {},
      });
    }
  });

  it("runs the command through the shell on Windows so .cmd shims resolve", () => {
    assert.deepEqual(resolveCommand("npm", ["install", "-g", "wrangler"], "win32"), {
      file: "npm install -g wrangler",
      args: [],
      options: { shell: true },
    });
  });

  it("keeps worker and secret names as single arguments on Windows", () => {
    const resolved = resolveCommand(
      "wrangler",
      ["secret", "put", "AGENT_TOKEN", "--name", "unifi-mcp-relay"],
      "win32",
    );
    assert.equal(resolved.file, "wrangler secret put AGENT_TOKEN --name unifi-mcp-relay");
  });

  it("quotes arguments with spaces or shell metacharacters on Windows", () => {
    const resolved = resolveCommand("wrangler", ["deploy", "--name", 'my worker&"x"'], "win32");
    assert.equal(resolved.file, 'wrangler deploy --name "my worker&""x"""');
  });

  it("defaults to the current platform", () => {
    const resolved = resolveCommand("node", ["--version"]);
    assert.equal(resolved.options.shell === true, process.platform === "win32");
  });
});

describe("assertWorkerName", () => {
  it("accepts Cloudflare worker names", () => {
    for (const name of ["unifi-mcp-relay", "relay2", "My_Relay", "a".repeat(63)]) {
      assert.equal(assertWorkerName(name), name);
    }
  });

  it("refuses names that could carry shell syntax or are not valid Workers names", () => {
    for (const name of ["", "-relay", "my relay", "relay&calc", "%PATH%", "relay\"x", "a".repeat(64), undefined]) {
      assert.throws(() => assertWorkerName(name), /Invalid worker name/);
    }
  });
});
