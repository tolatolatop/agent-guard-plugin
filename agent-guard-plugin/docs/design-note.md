# Design Note

The Python rewrite keeps the runtime guard file-backed and CLI-driven, while replacing all previous JS business logic with Python modules managed by `uv`.

Key decisions:

- Persist durable task memory under `.agent/` and fail closed when state is missing or invalid.
- Keep shell hooks as wrappers and move policy into Python modules under `src/agent_guard/`.
- Install Claude Code and Codex by generating command hooks that invoke `uv run --project <plugin-root> agent-guard-bridge ...`.
- Support OpenCode through a minimal generated JS loader that only forwards plugin events to the Python bridge.
- Keep dependencies small: standard library plus `PyYAML` for plan parsing.

Scope of this milestone:

- state initialization and status reporting
- path gating for writes
- command recording and failure-loop detection
- finalization gate checks
- runtime installers for Claude Code, Codex, and OpenCode
