---
name: using-workflow
description: Top-level navigation skill that routes the agent to the right workflow skill and hard gate.
---

# Using Workflow

This is the top-level navigation skill for `agent-guard`.

Use this skill first at session start and any time the next action is unclear.

Decision order:

1. Read the current `.agent/state.json` summary from `session-start`.
2. Identify the current `workflow_id`, `stage`, `current_step`, and `next_required_action`.
3. Route to the right specialist skill:
   - `workflow-core.md` for the default coding workflow
   - `research-workflow.md` for `workflow_id = research`
   - `docs-workflow.md` for `workflow_id = docs`
   - `plan-yaml.md` when creating, reading, or updating `.agent/plan.yaml`
   - `failure-analysis.md` when blocked by repeated failures
   - `finalization-checklist.md` before claiming completion
4. Follow hard gates from stage permissions, `check-failure-loop`, and `can-finalize`.

Core navigation rules:

- Never skip required stage transitions.
- Never assume the coding stage machine applies unless the bound workflow is the default coding workflow.
- Never assume completion from intent alone; rely on artifacts and verification.
- Use the current stage's `plan` mode to decide whether planning is denied, created, followed, advanced, or being closed out.
- Prefer the smallest legal next step over broad changes.
- Treat hard CLI gates as authoritative even if the model believes a shortcut is safe.
- If the next legal step requires creating or updating an artifact, explicitly state the allowed modification scope or directory before writing it.
