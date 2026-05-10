#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const pluginRoot = path.resolve(__dirname, "..", "..");
const cliPath = path.join(pluginRoot, "bin", "agent-guard");

function readHookInput() {
  try {
    const raw = fs.readFileSync(0, "utf8").trim();
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function runGuard(args) {
  const result = spawnSync("node", [cliPath, ...args], {
    cwd: process.cwd(),
    encoding: "utf8",
  });
  const stdout = result.stdout?.trim() || "{}";
  let parsed;
  try {
    parsed = JSON.parse(stdout);
  } catch {
    parsed = { raw: stdout };
  }
  return {
    status: result.status ?? 1,
    stdout,
    stderr: result.stderr?.trim() || "",
    parsed,
  };
}

function failWithReason(reason) {
  process.stderr.write(`${reason}\n`);
  process.exit(2);
}

function relativeArtifactPath(filePath) {
  return path.relative(process.cwd(), filePath).split(path.sep).join("/");
}

function ensureCommandLog(command, payload) {
  const artifactDir = path.join(process.cwd(), ".agent", "artifacts");
  fs.mkdirSync(artifactDir, { recursive: true });
  const fullPath = path.join(artifactDir, `hook-command-${Date.now()}.log`);
  const output = [
    `command: ${command}`,
    payload.tool_response?.stdout || payload.tool_response?.output || "",
    payload.tool_response?.stderr || payload.tool_response?.error || "",
  ]
    .filter(Boolean)
    .join("\n\n");
  fs.writeFileSync(fullPath, `${output}\n`);
  return relativeArtifactPath(fullPath);
}

function extractFilePath(payload) {
  const input = payload.tool_input || {};
  return (
    input.file_path ||
    input.filePath ||
    input.path ||
    input.target_path ||
    input.targetPath ||
    null
  );
}

function extractCommand(payload) {
  const input = payload.tool_input || {};
  if (typeof input.command === "string") {
    return input.command;
  }
  if (Array.isArray(input.command)) {
    return input.command.join(" ");
  }
  if (typeof input.cmd === "string") {
    return input.cmd;
  }
  return null;
}

function extractExitCode(payload) {
  const response = payload.tool_response || {};
  return Number(response.exit_code ?? response.exitCode ?? response.status ?? 0);
}

function handleSessionStart() {
  const result = runGuard(["session-start"]);
  if (result.status !== 0) {
    process.stderr.write(`${result.parsed.error || result.stderr}\n`);
    process.exit(1);
  }
  process.stdout.write(`${result.stdout}\n`);
}

function handlePreWrite(payload) {
  const targetPath = extractFilePath(payload);
  if (!targetPath) {
    process.exit(0);
  }

  const result = runGuard(["can-write", targetPath]);
  if (result.status !== 0) {
    failWithReason(result.parsed.reason || result.parsed.error || result.stderr);
  }
}

function handlePreCommand() {
  const result = runGuard(["check-failure-loop"]);
  if (result.status !== 0) {
    failWithReason(result.parsed.reason || result.parsed.error || result.stderr);
  }
}

function handlePreDispatch(payload) {
  if (extractFilePath(payload)) {
    handlePreWrite(payload);
    return;
  }
  if (extractCommand(payload)) {
    handlePreCommand(payload);
  }
}

function handlePostCommand(payload) {
  const command = extractCommand(payload);
  if (!command) {
    process.exit(0);
  }

  const logPath = ensureCommandLog(command, payload);
  const result = runGuard([
    "record-command",
    "--cmd",
    command,
    "--exit-code",
    String(extractExitCode(payload)),
    "--log",
    logPath,
  ]);
  if (result.status !== 0) {
    process.stderr.write(`${result.parsed.error || result.stderr}\n`);
    process.exit(1);
  }
}

function handleStop() {
  const result = runGuard(["can-finalize"]);
  if (result.status !== 0) {
    const reasons = result.parsed.reasons || [result.parsed.reason || result.parsed.error || result.stderr];
    failWithReason(`agent-guard blocked finalization: ${reasons.join("; ")}`);
  }
}

function main() {
  const action = process.argv[2];
  const payload = readHookInput();

  switch (action) {
    case "session-start":
      handleSessionStart(payload);
      break;
    case "pre-write":
      handlePreWrite(payload);
      break;
    case "pre-command":
      handlePreCommand(payload);
      break;
    case "pre-dispatch":
      handlePreDispatch(payload);
      break;
    case "post-command":
      handlePostCommand(payload);
      break;
    case "stop":
      handleStop(payload);
      break;
    default:
      process.stderr.write(`Unknown bridge action: ${action}\n`);
      process.exit(1);
  }
}

main();
