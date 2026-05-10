const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const SUPPORTED_RUNTIMES = ["claude-code", "codex", "opencode"];
const SUPPORTED_SCOPES = ["project", "user"];

function parseFlags(args) {
  const flags = {};
  for (let index = 0; index < args.length; index += 1) {
    const current = args[index];
    if (!current.startsWith("--")) {
      continue;
    }
    const key = current.slice(2);
    const next = args[index + 1];
    if (!next || next.startsWith("--")) {
      flags[key] = true;
      continue;
    }
    flags[key] = next;
    index += 1;
  }
  return flags;
}

function ensureDir(targetDir) {
  fs.mkdirSync(targetDir, { recursive: true });
}

function readJsonIfExists(filePath, fallback) {
  if (!fs.existsSync(filePath)) {
    return fallback;
  }
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function writeJson(filePath, value) {
  ensureDir(path.dirname(filePath));
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`);
}

function normalizeForShell(value) {
  return `"${String(value).replace(/(["$`\\])/g, "\\$1")}"`;
}

function dedupeHookEntries(entries, marker) {
  return entries.filter((entry) => {
    if (!entry || typeof entry !== "object") {
      return false;
    }
    if (!Array.isArray(entry.hooks)) {
      return true;
    }
    return !entry.hooks.some((hook) => hook?.command && hook.command.includes(marker));
  });
}

function makeCommand(scriptPath, action) {
  return `node ${normalizeForShell(scriptPath)} ${action}`;
}

function claudeConfigFile(scope, cwd, homeDir) {
  return scope === "project"
    ? path.join(cwd, ".claude", "settings.local.json")
    : path.join(homeDir, ".claude", "settings.json");
}

function codexHooksFile(scope, cwd, homeDir) {
  return scope === "project"
    ? path.join(cwd, ".codex", "hooks.json")
    : path.join(homeDir, ".codex", "hooks.json");
}

function opencodePluginFile(scope, cwd, homeDir) {
  return scope === "project"
    ? path.join(cwd, ".opencode", "plugins", "agent-guard.js")
    : path.join(homeDir, ".config", "opencode", "plugins", "agent-guard.js");
}

function buildClaudeHooks(scriptPath) {
  return {
    SessionStart: [
      {
        matcher: "*",
        hooks: [
          {
            type: "command",
            command: makeCommand(scriptPath, "session-start"),
          },
        ],
      },
    ],
    PreToolUse: [
      {
        matcher: "Write|Edit|MultiEdit",
        hooks: [
          {
            type: "command",
            command: makeCommand(scriptPath, "pre-write"),
          },
        ],
      },
      {
        matcher: "Bash",
        hooks: [
          {
            type: "command",
            command: makeCommand(scriptPath, "pre-command"),
          },
        ],
      },
    ],
    PostToolUse: [
      {
        matcher: "Bash",
        hooks: [
          {
            type: "command",
            command: makeCommand(scriptPath, "post-command"),
          },
        ],
      },
    ],
    Stop: [
      {
        matcher: "*",
        hooks: [
          {
            type: "command",
            command: makeCommand(scriptPath, "stop"),
          },
        ],
      },
    ],
  };
}

function mergeClaudeHooks(existingHooks, newHooks, marker) {
  const merged = { ...existingHooks };
  for (const [eventName, entries] of Object.entries(newHooks)) {
    const existingEntries = Array.isArray(merged[eventName]) ? merged[eventName] : [];
    merged[eventName] = [...dedupeHookEntries(existingEntries, marker), ...entries];
  }
  return merged;
}

function installClaudeCode({ cwd, homeDir, scope, pluginRoot }) {
  const configPath = claudeConfigFile(scope, cwd, homeDir);
  const bridgePath = path.join(pluginRoot, "hooks", "runtime", "claude-codex-bridge.js");
  const config = readJsonIfExists(configPath, {});
  const marker = path.join("hooks", "runtime", "claude-codex-bridge.js");
  config.hooks = mergeClaudeHooks(config.hooks || {}, buildClaudeHooks(bridgePath), marker);
  writeJson(configPath, config);

  return {
    runtime: "claude-code",
    scope,
    files_written: [configPath],
    notes: [
      "Installed Claude Code hooks into a settings JSON file.",
      "Claude Code passes hook payloads over stdin and can block PreToolUse/Stop hooks with exit code 2.",
    ],
  };
}

function buildCodexHooks(scriptPath) {
  return {
    hooks: {
      SessionStart: [
        {
          matcher: "*",
          hooks: [
            {
              type: "command",
              command: makeCommand(scriptPath, "session-start"),
            },
          ],
        },
      ],
      PreToolUse: [
        {
          matcher: "Write|Edit|MultiEdit|Bash",
          hooks: [
            {
              type: "command",
              command: makeCommand(scriptPath, "pre-dispatch"),
            },
          ],
        },
      ],
      PostToolUse: [
        {
          matcher: "Bash",
          hooks: [
            {
              type: "command",
              command: makeCommand(scriptPath, "post-command"),
            },
          ],
        },
      ],
      Stop: [
        {
          matcher: "*",
          hooks: [
            {
              type: "command",
              command: makeCommand(scriptPath, "stop"),
            },
          ],
        },
      ],
    },
  };
}

function installCodex({ cwd, homeDir, scope, pluginRoot }) {
  const hooksPath = codexHooksFile(scope, cwd, homeDir);
  const bridgePath = path.join(pluginRoot, "hooks", "runtime", "claude-codex-bridge.js");
  writeJson(hooksPath, buildCodexHooks(bridgePath));

  return {
    runtime: "codex",
    scope,
    files_written: [hooksPath],
    notes: [
      "Installed Codex hooks.json.",
      "Codex hook compatibility follows Claude-style lifecycle hooks, but tool-hook coverage is currently narrower than Claude Code.",
      "Recent Codex releases use hooks.json directly; older versions may also require enabling hooks in ~/.codex/config.toml.",
    ],
  };
}

function buildOpencodePluginSource(pluginRoot) {
  const cliPath = path.join(pluginRoot, "bin", "agent-guard");
  return `import { spawnSync } from "node:child_process"
import fs from "node:fs"
import path from "node:path"

const CLI_PATH = ${JSON.stringify(cliPath)}

function runGuard(args) {
  const result = spawnSync("node", [CLI_PATH, ...args], {
    encoding: "utf8",
    cwd: process.cwd(),
  })

  const stdout = result.stdout?.trim() || "{}"
  let parsed
  try {
    parsed = JSON.parse(stdout)
  } catch {
    parsed = { raw: stdout }
  }

  if (result.status !== 0) {
    const reason = parsed.reason || parsed.reasons?.join("; ") || parsed.error || result.stderr || "agent-guard rejected the action"
    throw new Error(reason)
  }

  return parsed
}

function writeLog(command, output) {
  const agentDir = path.join(process.cwd(), ".agent", "artifacts")
  fs.mkdirSync(agentDir, { recursive: true })
  const fileName = "opencode-command-" + Date.now() + ".log"
  const fullPath = path.join(agentDir, fileName)
  fs.writeFileSync(fullPath, [command, "", output || ""].join("\\n"))
  return path.relative(process.cwd(), fullPath).split(path.sep).join("/")
}

function extractPath(args) {
  return args?.filePath || args?.path || args?.targetPath || args?.newPath || null
}

function extractCommand(args) {
  if (!args) return null
  if (typeof args.command === "string") return args.command
  if (Array.isArray(args.command)) return args.command.join(" ")
  if (typeof args.cmd === "string") return args.cmd
  return null
}

export const AgentGuardPlugin = async ({ client }) => {
  return {
    "session.created": async () => {
      await client.app.log({
        body: {
          service: "agent-guard",
          level: "info",
          message: JSON.stringify(runGuard(["session-start"])),
        },
      })
    },
    "tool.execute.before": async (input) => {
      if (["write", "edit", "patch"].includes(input.tool)) {
        const targetPath = extractPath(input.args)
        if (targetPath) {
          runGuard(["can-write", targetPath])
        }
      }

      if (input.tool === "bash") {
        runGuard(["check-failure-loop"])
      }
    },
    "tool.execute.after": async (input, output) => {
      if (input.tool !== "bash") {
        return
      }

      const command = extractCommand(input.args)
      if (!command) {
        return
      }

      const exitCode = Number(output?.exitCode ?? output?.status ?? 0)
      const logPath = writeLog(command, [output?.stdout || "", output?.stderr || ""].filter(Boolean).join("\\n"))
      runGuard(["record-command", "--cmd", command, "--exit-code", String(exitCode), "--log", logPath])
    },
  }
}
`;
}

function installOpencode({ cwd, homeDir, scope, pluginRoot }) {
  const pluginPath = opencodePluginFile(scope, cwd, homeDir);
  ensureDir(path.dirname(pluginPath));
  fs.writeFileSync(pluginPath, buildOpencodePluginSource(pluginRoot));

  return {
    runtime: "opencode",
    scope,
    files_written: [pluginPath],
    notes: [
      "Installed an OpenCode plugin bridge into the auto-loaded plugins directory.",
      "OpenCode hooks are plugin events, not JSON lifecycle hooks, so the installer generates a JS bridge module.",
      "OpenCode can block tool.execute.before operations, but final-response gating is best-effort because the plugin API differs from Claude/Codex stop hooks.",
    ],
  };
}

function installRuntime(argv, context) {
  const flags = parseFlags(argv);
  const runtime = flags.runtime;
  const scope = flags.scope || "project";
  if (!runtime || !SUPPORTED_RUNTIMES.includes(runtime)) {
    throw new Error(
      `Missing or unsupported --runtime. Expected one of: ${SUPPORTED_RUNTIMES.join(", ")}`,
    );
  }
  if (!SUPPORTED_SCOPES.includes(scope)) {
    throw new Error(`Unsupported --scope. Expected one of: ${SUPPORTED_SCOPES.join(", ")}`);
  }

  const normalizedContext = {
    cwd: context.cwd,
    homeDir: context.homeDir || os.homedir(),
    pluginRoot: context.pluginRoot,
    scope,
  };

  switch (runtime) {
    case "claude-code":
      return installClaudeCode(normalizedContext);
    case "codex":
      return installCodex(normalizedContext);
    case "opencode":
      return installOpencode(normalizedContext);
    default:
      throw new Error(`Unsupported runtime: ${runtime}`);
  }
}

function runInstallCli(argv, context) {
  try {
    const result = installRuntime(argv, context);
    process.stdout.write(`${JSON.stringify({ ok: true, ...result }, null, 2)}\n`);
    process.exit(0);
  } catch (error) {
    process.stdout.write(`${JSON.stringify({ error: error.message }, null, 2)}\n`);
    process.exit(1);
  }
}

module.exports = {
  SUPPORTED_RUNTIMES,
  SUPPORTED_SCOPES,
  installRuntime,
  runInstallCli,
  buildOpencodePluginSource,
};
