const test = require("node:test");
const assert = require("node:assert/strict");
const { canFinalize } = require("../lib/gates");
const { makeTempRepo, writeState } = require("./helpers");

test("finalization is blocked when verification is missing", () => {
  const rootDir = makeTempRepo();
  writeState(rootDir, {
    remaining_steps: [],
    can_finalize: true,
  });

  const result = canFinalize(rootDir);
  assert.equal(result.decision, "block");
  assert.match(result.reasons.join("\n"), /verification/i);
});

test("finalization is allowed only when state is complete and verification passed", () => {
  const rootDir = makeTempRepo();
  writeState(rootDir, {
    remaining_steps: [],
    can_finalize: true,
    last_verification: {
      command: "node --test",
      exit_code: 0,
      log_path: ".agent/artifacts/final-verification.log",
      recorded_at: "2026-05-11T10:00:00Z",
    },
  });

  const result = canFinalize(rootDir);
  assert.equal(result.decision, "allow");
});
