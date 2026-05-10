const test = require("node:test");
const assert = require("node:assert/strict");
const { loadState, saveState, DEFAULT_STATE } = require("../lib/state");
const { makeTempRepo } = require("./helpers");

test("state loads defaults after init", () => {
  const rootDir = makeTempRepo();
  const state = loadState(rootDir);
  assert.deepEqual(state, DEFAULT_STATE);
});

test("state saves and reloads updates", () => {
  const rootDir = makeTempRepo();
  const nextState = {
    ...DEFAULT_STATE,
    stage: "RED_TEST",
    current_step: "red-001",
  };

  saveState(rootDir, nextState);
  assert.deepEqual(loadState(rootDir), nextState);
});
