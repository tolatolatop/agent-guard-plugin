---
name: using-workflow
description: Follow the task-state workflow by keeping the active stage, next step, and path scope aligned with the work being executed.
---

# Using Workflow

The workflow is stateful. Treat the current task stage as an execution constraint, not just a label.

## Rules

1. Always know the current stage before editing or running broad commands.
2. Move to the next stage only when the exit conditions are satisfied.
3. Keep the next concrete step explicit and narrow.
4. Respect allowed and forbidden paths for the active step.
5. If the current action does not fit the active stage, transition first.
6. If the next legal step requires creating or updating an artifact, explicitly state the allowed modification scope or directory before writing it.
7. If the task depends on planning or step scope, read `plan-yaml.md` before editing `.agent/plan.yaml`.

## Common Pitfalls

- Implementing before planning or before a failing test exists when the workflow requires one.
- Re-running failing commands without recording analysis.
- Summarizing work while verification is still incomplete.
