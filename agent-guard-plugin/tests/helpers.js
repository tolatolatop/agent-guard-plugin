const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { ensureAgentFiles, saveState, DEFAULT_STATE } = require("../lib/state");

function makeTempRepo() {
  const rootDir = fs.mkdtempSync(path.join(os.tmpdir(), "agent-guard-"));
  ensureAgentFiles(rootDir);
  return rootDir;
}

function writeState(rootDir, override = {}) {
  const state = {
    ...DEFAULT_STATE,
    ...override,
  };
  saveState(rootDir, state);
  return state;
}

module.exports = {
  makeTempRepo,
  writeState,
};
