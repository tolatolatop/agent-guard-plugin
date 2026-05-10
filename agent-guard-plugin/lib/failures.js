const fs = require("node:fs");
const crypto = require("node:crypto");
const path = require("node:path");
const {
  failuresPath,
  loadState,
  saveState,
} = require("./state");
const { appendEvent } = require("./events");

const DEFAULT_REPEAT_THRESHOLD = 2;

function readFailures(rootDir) {
  return JSON.parse(fs.readFileSync(failuresPath(rootDir), "utf8"));
}

function saveFailures(rootDir, failures) {
  fs.writeFileSync(failuresPath(rootDir), `${JSON.stringify(failures, null, 2)}\n`);
  return failures;
}

function hashFailure(command, exitCode, logPath) {
  let logContents = "";
  if (fs.existsSync(logPath)) {
    logContents = fs.readFileSync(logPath, "utf8");
  }
  const digest = crypto
    .createHash("sha256")
    .update(`${command}\n${exitCode}\n${logContents}`)
    .digest("hex");
  return digest;
}

function latestMtime(rootDir) {
  const candidates = ["src", "tests"].map((entry) => path.join(rootDir, entry));
  let latest = 0;

  for (const candidate of candidates) {
    if (!fs.existsSync(candidate)) {
      continue;
    }
    const stack = [candidate];
    while (stack.length > 0) {
      const current = stack.pop();
      const stats = fs.statSync(current);
      latest = Math.max(latest, stats.mtimeMs);
      if (stats.isDirectory()) {
        for (const child of fs.readdirSync(current)) {
          stack.push(path.join(current, child));
        }
      }
    }
  }

  return latest;
}

function recordCommandResult(rootDir, { command, exitCode, logPath }) {
  const state = loadState(rootDir);
  const failureHash = exitCode === 0 ? null : hashFailure(command, exitCode, path.join(rootDir, logPath));
  const failures = readFailures(rootDir);
  const codeFingerprint = latestMtime(rootDir);

  let lastFailure = failures.last_failure;
  if (exitCode === 0) {
    lastFailure = null;
  } else {
    const sameFailure =
      lastFailure &&
      lastFailure.command === command &&
      lastFailure.failure_hash === failureHash &&
      lastFailure.code_fingerprint === codeFingerprint;

    lastFailure = {
      command,
      exit_code: exitCode,
      failure_hash: failureHash,
      repeat_count: sameFailure ? lastFailure.repeat_count + 1 : 1,
      code_changed_since_last_failure: !sameFailure,
      code_fingerprint: codeFingerprint,
      log_path: logPath,
    };
  }

  saveFailures(rootDir, { last_failure: lastFailure });

  const nextState = { ...state };
  const isExpectedRedFailure = state.stage === "RED_TEST" && exitCode !== 0;
  if (!isExpectedRedFailure && exitCode !== 0) {
    nextState.stage = "NEEDS_FAILURE_ANALYSIS";
  }
  if (state.stage === "VERIFY") {
    nextState.last_verification = {
      command,
      exit_code: exitCode,
      log_path: logPath,
      recorded_at: new Date().toISOString(),
    };
  }
  saveState(rootDir, nextState);

  const event = appendEvent(rootDir, {
    hook: "AfterCommand",
    command,
    exit_code: exitCode,
    log_path: logPath,
    stage: nextState.stage,
  });

  return {
    state: nextState,
    failure: lastFailure,
    event,
  };
}

function checkFailureLoop(rootDir, threshold = DEFAULT_REPEAT_THRESHOLD) {
  const failures = readFailures(rootDir);
  const lastFailure = failures.last_failure;
  if (!lastFailure) {
    return {
      decision: "allow",
      reason: "No recorded failure loop.",
    };
  }

  if (
    lastFailure.repeat_count >= threshold &&
    lastFailure.code_changed_since_last_failure === false
  ) {
    return {
      decision: "block",
      reason:
        "Repeated identical failure detected without code changes. Write .agent/artifacts/failure-analysis.md before retrying.",
      failure: lastFailure,
    };
  }

  return {
    decision: "allow",
    reason: "Failure loop threshold not reached.",
    failure: lastFailure,
  };
}

module.exports = {
  DEFAULT_REPEAT_THRESHOLD,
  hashFailure,
  recordCommandResult,
  checkFailureLoop,
};
