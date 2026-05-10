const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { recordCommandResult, checkFailureLoop } = require("../lib/failures");
const { loadState } = require("../lib/state");
const { makeTempRepo, writeState } = require("./helpers");

test("record-command stores failed command and moves stage to failure analysis outside RED_TEST", () => {
  const rootDir = makeTempRepo();
  writeState(rootDir, { stage: "GREEN_IMPL" });

  const logPath = ".agent/artifacts/green-test.log";
  fs.writeFileSync(path.join(rootDir, logPath), "expected failure\n");
  const result = recordCommandResult(rootDir, {
    command: "node --test",
    exitCode: 1,
    logPath,
  });

  assert.equal(result.failure.command, "node --test");
  assert.equal(loadState(rootDir).stage, "NEEDS_FAILURE_ANALYSIS");
});

test("repeating same failed command twice without code changes is blocked", () => {
  const rootDir = makeTempRepo();
  writeState(rootDir, { stage: "GREEN_IMPL" });

  const logPath = ".agent/artifacts/red-test.log";
  fs.writeFileSync(path.join(rootDir, logPath), "same failure\n");

  recordCommandResult(rootDir, {
    command: "node --test tests/example.test.js",
    exitCode: 1,
    logPath,
  });
  recordCommandResult(rootDir, {
    command: "node --test tests/example.test.js",
    exitCode: 1,
    logPath,
  });

  const result = checkFailureLoop(rootDir);
  assert.equal(result.decision, "block");
});

test("VERIFY command records final verification result", () => {
  const rootDir = makeTempRepo();
  writeState(rootDir, { stage: "VERIFY" });

  const logPath = ".agent/artifacts/final-verification.log";
  fs.writeFileSync(path.join(rootDir, logPath), "all green\n");

  recordCommandResult(rootDir, {
    command: "node --test",
    exitCode: 0,
    logPath,
  });

  const state = loadState(rootDir);
  assert.equal(state.last_verification.exit_code, 0);
});
