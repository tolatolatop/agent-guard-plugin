const fs = require("node:fs");
const path = require("node:path");

const AGENT_DIR = ".agent";
const ARTIFACTS_DIR = path.join(AGENT_DIR, "artifacts");

const DEFAULT_STATE = {
  task_id: null,
  stage: "IDLE",
  current_step: null,
  completed_steps: [],
  remaining_steps: [],
  allowed_paths: [],
  forbidden_paths: [],
  can_finalize: false,
  last_verification: null,
  needs_human: false,
};

const DEFAULT_JOBS = { jobs: [] };
const DEFAULT_FAILURES = { last_failure: null };

function statePath(rootDir) {
  return path.join(rootDir, AGENT_DIR, "state.json");
}

function jobsPath(rootDir) {
  return path.join(rootDir, AGENT_DIR, "jobs.json");
}

function failuresPath(rootDir) {
  return path.join(rootDir, AGENT_DIR, "failures.json");
}

function eventsPath(rootDir) {
  return path.join(rootDir, AGENT_DIR, "events.jsonl");
}

function ensureDir(target) {
  fs.mkdirSync(target, { recursive: true });
}

function writeJsonIfMissing(filePath, value) {
  if (!fs.existsSync(filePath)) {
    fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`);
  }
}

function ensureAgentFiles(rootDir) {
  ensureDir(path.join(rootDir, ARTIFACTS_DIR));
  writeJsonIfMissing(statePath(rootDir), DEFAULT_STATE);
  writeJsonIfMissing(jobsPath(rootDir), DEFAULT_JOBS);
  writeJsonIfMissing(failuresPath(rootDir), DEFAULT_FAILURES);
  if (!fs.existsSync(eventsPath(rootDir))) {
    fs.writeFileSync(eventsPath(rootDir), "");
  }
}

function readJson(filePath, label) {
  if (!fs.existsSync(filePath)) {
    throw new Error(`${label} is missing at ${filePath}. Run agent-guard init first.`);
  }

  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch (error) {
    throw new Error(`${label} is invalid JSON: ${error.message}`);
  }
}

function validateState(state) {
  const requiredKeys = [
    "task_id",
    "stage",
    "current_step",
    "completed_steps",
    "remaining_steps",
    "allowed_paths",
    "forbidden_paths",
    "can_finalize",
    "last_verification",
    "needs_human",
  ];

  for (const key of requiredKeys) {
    if (!(key in state)) {
      throw new Error(`state.json is missing required key: ${key}`);
    }
  }

  return state;
}

function loadState(rootDir) {
  return validateState(readJson(statePath(rootDir), "state.json"));
}

function saveState(rootDir, state) {
  validateState(state);
  fs.writeFileSync(statePath(rootDir), `${JSON.stringify(state, null, 2)}\n`);
  return state;
}

function updateState(rootDir, updater) {
  const current = loadState(rootDir);
  const next = updater(current);
  return saveState(rootDir, next);
}

module.exports = {
  AGENT_DIR,
  ARTIFACTS_DIR,
  DEFAULT_STATE,
  DEFAULT_JOBS,
  DEFAULT_FAILURES,
  statePath,
  jobsPath,
  failuresPath,
  eventsPath,
  ensureAgentFiles,
  loadState,
  saveState,
  updateState,
};
