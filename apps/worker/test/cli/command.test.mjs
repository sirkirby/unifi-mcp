import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { resolveCommand } from "../../src/lib/command.mjs";

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
