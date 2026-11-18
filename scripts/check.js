"use strict";
const { spawnSync } = require("node:child_process");
const path = require("node:path");
const root = path.resolve(__dirname, "..");
const checks = ["examples/offline-demo.js", "test_decision_layer.js", "test_side_pot_contract.js", "test_preflop_participation.js"];
let failed = 0;
for (const file of checks) {
  const result = spawnSync(process.execPath, [file], { cwd: root, encoding: "utf8", timeout: 60000, maxBuffer: 1024 * 1024 });
  if (result.status !== 0) {
    failed++;
    console.error(`FAIL ${file}: ${(result.error?.message || result.stderr || result.stdout || "abnormal exit").slice(0, 1800)}`);
  } else {
    console.log(`PASS ${file}`);
  }
}
console.log(`Checks: ${checks.length}; passed: ${checks.length - failed}; failed: ${failed}`);
process.exitCode = failed ? 1 : 0;
