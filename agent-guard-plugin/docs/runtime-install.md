# Runtime Hook Installation

Use the shared installer to register `agent-guard` with the target agent runtime:

```bash
uv run install-agent-guard --runtime claude-code --scope project
uv run install-agent-guard --runtime codex --scope project
uv run install-agent-guard --runtime opencode --scope project
```

Supported runtimes:

- `claude-code`
- `codex`
- `opencode`

Supported scopes:

- `project`
- `user`

What the installer writes:

- Claude Code: `.claude/settings.local.json` for project scope or `~/.claude/settings.json` for user scope.
- Codex: `.codex/hooks.json` for project scope or `~/.codex/hooks.json` for user scope.
- OpenCode: `.opencode/plugins/agent-guard.js` for project scope or `~/.config/opencode/plugins/agent-guard.js` for user scope. This is a thin loader that forwards events to Python.

Runtime differences:

- Claude Code uses JSON hook configuration with lifecycle events like `SessionStart`, `PreToolUse`, `PostToolUse`, and `Stop`.
- Codex also uses a Claude-style lifecycle hook file, but hook coverage is currently narrower in practice, especially for non-shell tool calls.
- OpenCode uses plugin events rather than a standalone JSON hook manifest, so the installer generates a tiny JS loader and keeps all guard logic in Python.

Current guard mapping:

- session bootstrap: `session-start`
- write policy gate: `can-write`
- repeated failure gate: `check-failure-loop`
- command recording: `record-command`
- finalization gate: `can-finalize`

Known limitations:

- Codex shell hooks are the most reliable path today; write-hook coverage may vary by version.
- OpenCode can enforce pre-tool checks and command recording, but end-of-response blocking is best-effort because its plugin lifecycle differs from Claude/Codex stop hooks.

Development workflow:

```bash
uv run pytest
uv run agent-guard init
uv run agent-guard status
```
