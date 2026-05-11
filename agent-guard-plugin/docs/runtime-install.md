# Runtime Hook Installation

Use the shared installer to register `agent-guard` with the target agent runtime:

```bash
uv run install-agent-guard --runtime claude-code --scope project
uv run install-agent-guard --runtime codex --scope project
uv run install-agent-guard --runtime opencode --scope project
uv run agent-guard uninstall --runtime codex --scope project
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

Protected runtime files:

- `.agent/state.json` is now a hard-protected file.
- Agents must not edit it directly.
- State transitions should happen through `agent-guard` commands such as `start-task`, `reset-task`, and `record-command`.

Known limitations:

- Codex shell hooks are the most reliable path today; write-hook coverage may vary by version.
- OpenCode can enforce pre-tool checks and command recording, but end-of-response blocking is best-effort because its plugin lifecycle differs from Claude/Codex stop hooks.

Development workflow:

```bash
uv run pytest
uv run agent-guard init
uv run agent-guard wizard
uv run agent-guard status
uv run agent-guard session-start
uv run agent-guard reset-task next-requirement
```

Interactive wizard:

- `uv run agent-guard wizard`

The wizard bootstraps a new task interactively:

- ensures `.agent/` exists
- collects `task_id`, goal, stage, current step, and path scopes
- writes `state.json`
- can generate a starter `.agent/plan.yaml`

Artifact retention:

- `events.jsonl` is the full lightweight command/event index.
- successful commands usually stay in `events.jsonl` only
- `artifacts/` is reserved for retained evidence such as:
  - `red-test.log`
  - `final-verification.log`
  - `command-failure.log`
  - `failure-analysis.md`
  - `review.json`

`session-start` now returns two layers of prompt-ready guidance:

- a prominent `meta_skill` navigator pointing at `docs/skills/workflow-navigator.md`
- a `workflow` block with current-stage goal, legal transitions, action constraints, and skill references

The intent is to inject only a concise navigator into the visible prompt, while leaving the full workflow and specialist skills on disk for on-demand loading.

Uninstall workflow:

- `uv run agent-guard uninstall --runtime claude-code --scope project`
- `uv run agent-guard uninstall --runtime codex --scope user`
- `uv run agent-guard uninstall --runtime opencode --scope project`

The uninstall command is interactive by default. It prints the files it will update or delete, then asks for confirmation before making changes.

Task reset workflow:

- `uv run agent-guard reset-task <new-task-id>`
- `uv run agent-guard next-task <new-task-id>`

Reset is intentionally gated. It only succeeds when the current task is already complete:

- `stage == DONE`, or
- `stage == READY_TO_SUMMARIZE` and `can_finalize == true`

When reset succeeds, the plugin archives the current task under `.agent/archive/<timestamp>-<task-id>/` and then clears live jobs, failures, events, plan, and artifacts before initializing the next task in `CLARIFYING`.
