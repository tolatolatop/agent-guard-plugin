const test = require("node:test");
const assert = require("node:assert/strict");
const { decideWrite } = require("../lib/path-policy");
const { DEFAULT_STATE } = require("../lib/state");

test("RED_TEST blocks src writes", () => {
  const result = decideWrite(
    {
      ...DEFAULT_STATE,
      stage: "RED_TEST",
      allowed_paths: ["tests/**"],
      forbidden_paths: ["src/**"],
    },
    "src/auth/reset.js",
  );

  assert.equal(result.decision, "block");
});

test("RED_TEST allows test writes in allowed scope", () => {
  const result = decideWrite(
    {
      ...DEFAULT_STATE,
      stage: "RED_TEST",
      allowed_paths: ["tests/**"],
      forbidden_paths: ["src/**"],
    },
    "tests/auth/test_password_reset.js",
  );

  assert.equal(result.decision, "allow");
});

test("sensitive paths require approval", () => {
  const result = decideWrite(
    {
      ...DEFAULT_STATE,
      stage: "GREEN_IMPL",
      allowed_paths: [".github/**"],
      forbidden_paths: [],
    },
    ".github/workflows/ci.yml",
  );

  assert.equal(result.decision, "block");
});
