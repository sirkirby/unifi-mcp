import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import Ajv from "ajv";
import standaloneCode from "ajv/dist/standalone/index.js";

const source = fileURLToPath(new URL("../../../../tests/fixtures/incident_evidence/incident-evidence.v1.schema.json", import.meta.url));
const output = fileURLToPath(new URL("../src/incident-evidence-schema.js", import.meta.url));
const schema = JSON.parse(readFileSync(source, "utf8"));
const ajv = new Ajv({ strict: false, code: { esm: true, source: true } });
ajv.compile({ ...schema, $id: "urn:worker:incident-evidence" });
ajv.compile({ $id: "urn:worker:mapping-assertion", $defs: schema.$defs, ...schema.$defs.MappingAssertion });
const code = standaloneCode(ajv, { validateEvidenceSchema: "urn:worker:incident-evidence", validateMappingAssertion: "urn:worker:mapping-assertion" })
  .replaceAll('require("ajv/dist/runtime/ucs2length").default', '(str) => Array.from(str).length');
if (code.includes("require(")) throw new Error("Generated validator still depends on runtime imports");
const generated = `// Generated from tests/fixtures/incident_evidence/incident-evidence.v1.schema.json.\n// Run npm run generate:evidence-schema to update. Do not edit manually.\n${code}`;
if (process.argv.includes("--check")) {
  if (readFileSync(output, "utf8") !== generated) {
    process.stderr.write("Incident evidence schema validator is out of date.\n");
    process.exitCode = 1;
  }
} else writeFileSync(output, generated);
