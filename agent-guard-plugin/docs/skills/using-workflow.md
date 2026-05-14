---
name: using-workflow
description: Top-level navigation skill that routes the agent to the right workflow skill and hard gate.
---

# Using Workflow

This is the top-level navigation skill for `agent-guard`.

Use this skill first at session start and any time the next action is unclear.

Decision order:

1. Read the current `.agent/state.json` summary from `session-start`.
2. Identify the current `stage`, `current_step`, and `next_required_action`.
3. Route to the right specialist skill:
   - `workflow-core.md` for stage rules and transitions
   - `plan-yaml.md` when creating, reading, or updating `.agent/plan.yaml`
   - `failure-analysis.md` when blocked by repeated failures
   - `finalization-checklist.md` before claiming completion
4. Follow hard gates from stage `write_policy`, `check-failure-loop`, and `can-finalize`.

Core navigation rules:

- Never skip required stage transitions.
- Never assume completion from intent alone; rely on artifacts and verification.
- Prefer the smallest legal next step over broad changes.
- Treat hard CLI gates as authoritative even if the model believes a shortcut is safe.
- If the next legal step requires creating or updating an artifact, explicitly state the allowed modification scope or directory before writing it.
