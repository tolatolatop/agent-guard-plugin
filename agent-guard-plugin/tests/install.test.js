const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { installRuntime } = require("../lib/install");

function makeDirs() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "agent-guard-install-"));
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "agent-guard-home-"));
  return { root, home };
}

const pluginRoot = path.resolve(__dirname, "..");

test("install writes Claude Code project settings with hook commands", () => {
  const { root, home } = makeDirs();
  const result = installRuntime(["--runtime", "claude-code", "--scope", "project"], {
    cwd: root,
    homeDir: home,
    pluginRoot,
  });

  const configPath = path.join(root, ".claude", "settings.local.json");
  const config = JSON.parse(fs.readFileSync(configPath, "utf8"));

  assert.equal(result.runtime, "claude-code");
  assert.ok(config.hooks.PreToolUse.length >= 1);
  assert.match(JSON.stringify(config), /claude-codex-bridge\.js/);
});

test("install writes Codex hooks.json", () => {
  const { root, home } = makeDirs();
  installRuntime(["--runtime", "codex", "--scope", "project"], {
    cwd: root,
    homeDir: home,
    pluginRoot,
  });

  const hooksPath = path.join(root, ".codex", "hooks.json");
  const hooks = JSON.parse(fs.readFileSync(hooksPath, "utf8"));

  assert.ok(Array.isArray(hooks.hooks.SessionStart));
  assert.match(JSON.stringify(hooks), /pre-dispatch/);
});

test("install writes OpenCode plugin bridge", () => {
  const { root, home } = makeDirs();
  installRuntime(["--runtime", "opencode", "--scope", "project"], {
    cwd: root,
    homeDir: home,
    pluginRoot,
  });

  const pluginPath = path.join(root, ".opencode", "plugins", "agent-guard.js");
  const source = fs.readFileSync(pluginPath, "utf8");

  assert.match(source, /tool\.execute\.before/);
  assert.match(source, /record-command/);
});
